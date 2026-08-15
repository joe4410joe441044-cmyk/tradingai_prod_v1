"""Fail-closed, read-only preflight for the isolated live Runner."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Sequence

LIVE_UNIT = "tradingai-ai-advisor-live-validation.service"
RUNNER_MODULE = "backend.ai_advisor.isolated_smoke_runner"
_RUNNING_SUBSTATES = frozenset({"start", "start-post", "running"})


class UnitClassification(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    NOT_FOUND = "NOT_FOUND"
    INDETERMINATE = "INDETERMINATE"


class RunnerDetection(str, Enum):
    RUNNER_PRESENT = "RUNNER_PRESENT"
    RUNNER_ABSENT = "RUNNER_ABSENT"
    INDETERMINATE = "INDETERMINATE"


class DetectionReason(str, Enum):
    UNIT_ACTIVE = "UNIT_ACTIVE"
    NO_RUNNER_CANDIDATE = "NO_RUNNER_CANDIDATE"
    EXACT_MODULE_MATCH = "EXACT_MODULE_MATCH"
    SYSTEMCTL_EXECUTION_FAILURE = "SYSTEMCTL_EXECUTION_FAILURE"
    SYSTEMCTL_TIMEOUT = "SYSTEMCTL_TIMEOUT"
    SYSTEMD_METADATA_INVALID = "SYSTEMD_METADATA_INVALID"
    PROCESS_ENUMERATION_FAILURE = "PROCESS_ENUMERATION_FAILURE"
    PYTHON_CANDIDATE_EXE_UNREADABLE = "PYTHON_CANDIDATE_EXE_UNREADABLE"
    PYTHON_CANDIDATE_CMDLINE_UNREADABLE = "PYTHON_CANDIDATE_CMDLINE_UNREADABLE"
    PYTHON_CANDIDATE_METADATA_INVALID = "PYTHON_CANDIDATE_METADATA_INVALID"
    PYTHON_CANDIDATE_COMM_EXE_CONFLICT = "PYTHON_CANDIDATE_COMM_EXE_CONFLICT"
    UNIT_PROCESS_CONTRADICTION = "UNIT_PROCESS_CONTRADICTION"


@dataclass(frozen=True)
class DetectionResult:
    classification: RunnerDetection
    reason: DetectionReason
    pid: int | None = None


@dataclass(frozen=True)
class UnitResult:
    classification: UnitClassification
    reason: DetectionReason | None = None


@dataclass(frozen=True)
class ProcessMetadata:
    pid: int
    ppid: int | None
    comm: str | None
    exe: str | None
    argv: tuple[str, ...] | None


def classify_unit(
    *,
    load_state: str | None,
    active_state: str | None,
    sub_state: str | None,
) -> UnitClassification:
    if not all(
        isinstance(value, str) and value
        for value in (
            load_state,
            active_state,
            sub_state,
        )
    ):
        return UnitClassification.INDETERMINATE
    if load_state == "not-found":
        return (
            UnitClassification.NOT_FOUND
            if active_state == "inactive" and sub_state == "dead"
            else UnitClassification.INDETERMINATE
        )
    if load_state != "loaded":
        return UnitClassification.INDETERMINATE
    if active_state == "active" and sub_state in _RUNNING_SUBSTATES:
        return UnitClassification.ACTIVE
    if active_state == "inactive" and sub_state == "dead":
        return UnitClassification.INACTIVE
    return UnitClassification.INDETERMINATE


def _is_python(metadata: ProcessMetadata) -> bool | None:
    if metadata.comm is None and metadata.exe is None:
        return None
    comm_is_python = (
        None
        if metadata.comm is None
        else Path(metadata.comm).name.lower().startswith("python")
    )
    exe_is_python = (
        None
        if metadata.exe is None
        else Path(metadata.exe).name.lower().startswith("python")
    )
    if (
        comm_is_python is not None
        and exe_is_python is not None
        and comm_is_python != exe_is_python
    ):
        return None
    return bool(comm_is_python or exe_is_python)


def classify_process(
    metadata: ProcessMetadata,
    *,
    self_pid: int,
    parent_pid: int,
) -> RunnerDetection:
    if (
        not isinstance(metadata.pid, int)
        or isinstance(metadata.pid, bool)
        or metadata.pid <= 0
    ):
        return RunnerDetection.INDETERMINATE
    if metadata.pid in {self_pid, parent_pid}:
        return RunnerDetection.RUNNER_ABSENT
    if (
        metadata.ppid is None
        or not isinstance(metadata.ppid, int)
        or isinstance(metadata.ppid, bool)
        or metadata.ppid < 0
    ):
        return RunnerDetection.INDETERMINATE
    python_process = _is_python(metadata)
    if python_process is None:
        return RunnerDetection.INDETERMINATE
    if python_process is False:
        return RunnerDetection.RUNNER_ABSENT
    if metadata.argv is None:
        return RunnerDetection.INDETERMINATE
    for index, argument in enumerate(metadata.argv[:-1]):
        if argument == "-m" and metadata.argv[index + 1] == RUNNER_MODULE:
            return RunnerDetection.RUNNER_PRESENT
    return RunnerDetection.RUNNER_ABSENT


def classify_process_result(
    metadata: ProcessMetadata,
    *,
    self_pid: int,
    parent_pid: int,
) -> DetectionResult:
    classification = classify_process(
        metadata,
        self_pid=self_pid,
        parent_pid=parent_pid,
    )
    if classification is RunnerDetection.RUNNER_PRESENT:
        reason = DetectionReason.EXACT_MODULE_MATCH
    elif classification is RunnerDetection.RUNNER_ABSENT:
        reason = DetectionReason.NO_RUNNER_CANDIDATE
    elif metadata.comm is not None and metadata.exe is not None:
        reason = DetectionReason.PYTHON_CANDIDATE_COMM_EXE_CONFLICT
    else:
        reason = DetectionReason.PYTHON_CANDIDATE_METADATA_INVALID
    return DetectionResult(classification, reason, metadata.pid)


def combine_detection(
    unit: UnitClassification,
    processes: Iterable[RunnerDetection],
) -> RunnerDetection:
    process_results = tuple(processes)
    if unit is UnitClassification.INDETERMINATE:
        return RunnerDetection.INDETERMINATE
    if unit is UnitClassification.ACTIVE:
        return RunnerDetection.RUNNER_PRESENT
    if any(result is RunnerDetection.INDETERMINATE for result in process_results):
        return RunnerDetection.INDETERMINATE
    if any(result is RunnerDetection.RUNNER_PRESENT for result in process_results):
        return RunnerDetection.INDETERMINATE
    return RunnerDetection.RUNNER_ABSENT


def read_unit_classification(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> UnitClassification:
    return read_unit_result(runner=runner).classification


def read_unit_result(
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> UnitResult:
    try:
        completed = runner(
            [
                "systemctl",
                "show",
                LIVE_UNIT,
                "-p",
                "LoadState",
                "-p",
                "ActiveState",
                "-p",
                "SubState",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        if completed.returncode not in {0, 1} or completed.stderr:
            return UnitResult(
                UnitClassification.INDETERMINATE,
                DetectionReason.SYSTEMCTL_EXECUTION_FAILURE,
            )
        values = {}
        for line in completed.stdout.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in values:
                return UnitResult(
                    UnitClassification.INDETERMINATE,
                    DetectionReason.SYSTEMD_METADATA_INVALID,
                )
            values[key] = value
        if set(values) != {"LoadState", "ActiveState", "SubState"}:
            return UnitResult(
                UnitClassification.INDETERMINATE,
                DetectionReason.SYSTEMD_METADATA_INVALID,
            )
        classification = classify_unit(
            load_state=values["LoadState"],
            active_state=values["ActiveState"],
            sub_state=values["SubState"],
        )
        return UnitResult(
            classification,
            (
                DetectionReason.SYSTEMD_METADATA_INVALID
                if classification is UnitClassification.INDETERMINATE
                else None
            ),
        )
    except subprocess.TimeoutExpired:
        return UnitResult(
            UnitClassification.INDETERMINATE,
            DetectionReason.SYSTEMCTL_TIMEOUT,
        )
    except Exception:
        return UnitResult(
            UnitClassification.INDETERMINATE,
            DetectionReason.SYSTEMCTL_EXECUTION_FAILURE,
        )


def read_process_metadata(proc_path: Path) -> ProcessMetadata:
    pid = int(proc_path.name)
    comm = (proc_path / "comm").read_text(encoding="utf-8").strip()
    if not comm:
        raise ValueError("process comm unavailable")
    if not Path(comm).name.lower().startswith("python"):
        return ProcessMetadata(
            pid=pid,
            ppid=0,
            comm=comm,
            exe=None,
            argv=(),
        )
    status_values = {}
    for line in (proc_path / "status").read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator and key == "PPid":
            status_values[key] = value.strip()
    if set(status_values) != {"PPid"}:
        raise ValueError("process status unavailable")
    ppid = int(status_values["PPid"])
    exe = os.readlink(proc_path / "exe")
    raw_argv = (proc_path / "cmdline").read_bytes()
    if not raw_argv:
        raise ValueError("process argv unavailable")
    decoded = raw_argv.decode("utf-8", errors="strict")
    argv = tuple(argument for argument in decoded.split("\0") if argument)
    if not argv:
        raise ValueError("process argv unavailable")
    return ProcessMetadata(
        pid=pid,
        ppid=ppid,
        comm=comm,
        exe=exe,
        argv=argv,
    )


def _indeterminate_reason_for_error(
    proc_path: Path,
    error: Exception,
) -> DetectionReason:
    if isinstance(error, UnicodeDecodeError):
        return DetectionReason.PYTHON_CANDIDATE_METADATA_INVALID
    filename = (
        Path(error.filename).name
        if isinstance(error, OSError) and error.filename
        else ""
    )
    if filename == "exe":
        return DetectionReason.PYTHON_CANDIDATE_EXE_UNREADABLE
    if filename == "cmdline":
        return DetectionReason.PYTHON_CANDIDATE_CMDLINE_UNREADABLE
    if (proc_path / "comm").exists():
        try:
            comm = (proc_path / "comm").read_text(encoding="utf-8").strip()
        except Exception:
            return DetectionReason.PYTHON_CANDIDATE_METADATA_INVALID
        if Path(comm).name.lower().startswith("python"):
            return DetectionReason.PYTHON_CANDIDATE_METADATA_INVALID
    return DetectionReason.PYTHON_CANDIDATE_METADATA_INVALID


def detect_existing_runner_result(
    *,
    unit: UnitClassification,
    unit_reason: DetectionReason | None = None,
    proc_root: Path = Path("/proc"),
    self_pid: int | None = None,
    parent_pid: int | None = None,
) -> DetectionResult:
    if unit is UnitClassification.ACTIVE:
        return DetectionResult(
            RunnerDetection.RUNNER_PRESENT,
            DetectionReason.UNIT_ACTIVE,
        )
    if unit is UnitClassification.INDETERMINATE:
        return DetectionResult(
            RunnerDetection.INDETERMINATE,
            unit_reason or DetectionReason.SYSTEMD_METADATA_INVALID,
        )
    current_pid = os.getpid() if self_pid is None else self_pid
    current_parent = os.getppid() if parent_pid is None else parent_pid
    try:
        proc_paths = sorted(
            (
                path
                for path in proc_root.iterdir()
                if path.name.isascii() and path.name.isdigit()
            ),
            key=lambda path: int(path.name),
        )
    except Exception:
        return DetectionResult(
            RunnerDetection.INDETERMINATE,
            DetectionReason.PROCESS_ENUMERATION_FAILURE,
        )
    for proc_path in proc_paths:
        pid = int(proc_path.name)
        if pid in {current_pid, current_parent}:
            continue
        try:
            metadata = read_process_metadata(proc_path)
        except FileNotFoundError as error:
            if not proc_path.exists():
                continue
            return DetectionResult(
                RunnerDetection.INDETERMINATE,
                _indeterminate_reason_for_error(proc_path, error),
                pid,
            )
        except Exception as error:
            return DetectionResult(
                RunnerDetection.INDETERMINATE,
                _indeterminate_reason_for_error(proc_path, error),
                pid,
            )
        process_result = classify_process_result(
            metadata,
            self_pid=current_pid,
            parent_pid=current_parent,
        )
        if process_result.classification is RunnerDetection.INDETERMINATE:
            return DetectionResult(
                RunnerDetection.INDETERMINATE,
                process_result.reason,
                pid,
            )
        if process_result.classification is RunnerDetection.RUNNER_PRESENT:
            return DetectionResult(
                RunnerDetection.INDETERMINATE,
                DetectionReason.UNIT_PROCESS_CONTRADICTION,
                pid,
            )
    return DetectionResult(
        RunnerDetection.RUNNER_ABSENT,
        DetectionReason.NO_RUNNER_CANDIDATE,
    )


def detect_existing_runner(
    *,
    unit: UnitClassification,
    proc_root: Path = Path("/proc"),
    self_pid: int | None = None,
    parent_pid: int | None = None,
) -> RunnerDetection:
    return detect_existing_runner_result(
        unit=unit,
        proc_root=proc_root,
        self_pid=self_pid,
        parent_pid=parent_pid,
    ).classification


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.parse_args(argv)
    unit_result = read_unit_result()
    result = detect_existing_runner_result(
        unit=unit_result.classification,
        unit_reason=unit_result.reason,
    )
    sys.stdout.write(f"{result.classification.value} reason={result.reason.value}\n")
    return {
        RunnerDetection.RUNNER_ABSENT: 0,
        RunnerDetection.RUNNER_PRESENT: 40,
        RunnerDetection.INDETERMINATE: 41,
    }[result.classification]


if __name__ == "__main__":
    raise SystemExit(main())
