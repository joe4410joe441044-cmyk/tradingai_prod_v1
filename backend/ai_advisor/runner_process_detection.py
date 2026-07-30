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
            return UnitClassification.INDETERMINATE
        values = {}
        for line in completed.stdout.splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in values:
                return UnitClassification.INDETERMINATE
            values[key] = value
        if set(values) != {"LoadState", "ActiveState", "SubState"}:
            return UnitClassification.INDETERMINATE
        return classify_unit(
            load_state=values["LoadState"],
            active_state=values["ActiveState"],
            sub_state=values["SubState"],
        )
    except Exception:
        return UnitClassification.INDETERMINATE


def read_process_metadata(proc_path: Path) -> ProcessMetadata:
    pid = int(proc_path.name)
    status_values = {}
    for line in (proc_path / "status").read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"Name", "PPid"}:
            status_values[key] = value.strip()
    if set(status_values) != {"Name", "PPid"}:
        raise ValueError("process status unavailable")
    comm = status_values["Name"]
    exe = os.readlink(proc_path / "exe")
    if not (
        Path(comm).name.lower().startswith("python")
        or Path(exe).name.lower().startswith("python")
    ):
        return ProcessMetadata(
            pid=pid,
            ppid=int(status_values["PPid"]),
            comm=comm,
            exe=exe,
            argv=(),
        )
    raw_argv = (proc_path / "cmdline").read_bytes()
    if not raw_argv:
        raise ValueError("process argv unavailable")
    decoded = raw_argv.decode("utf-8", errors="strict")
    argv = tuple(argument for argument in decoded.split("\0") if argument)
    if not argv:
        raise ValueError("process argv unavailable")
    return ProcessMetadata(
        pid=pid,
        ppid=int(status_values["PPid"]),
        comm=comm,
        exe=exe,
        argv=argv,
    )


def detect_existing_runner(
    *,
    unit: UnitClassification,
    proc_root: Path = Path("/proc"),
    self_pid: int | None = None,
    parent_pid: int | None = None,
) -> RunnerDetection:
    if unit is UnitClassification.ACTIVE:
        return RunnerDetection.RUNNER_PRESENT
    if unit is UnitClassification.INDETERMINATE:
        return RunnerDetection.INDETERMINATE
    current_pid = os.getpid() if self_pid is None else self_pid
    current_parent = os.getppid() if parent_pid is None else parent_pid
    process_results = []
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
        return RunnerDetection.INDETERMINATE
    for proc_path in proc_paths:
        pid = int(proc_path.name)
        if pid in {current_pid, current_parent}:
            continue
        try:
            metadata = read_process_metadata(proc_path)
        except FileNotFoundError:
            if proc_path.exists():
                return RunnerDetection.INDETERMINATE
            continue
        except Exception:
            return RunnerDetection.INDETERMINATE
        process_results.append(
            classify_process(
                metadata,
                self_pid=current_pid,
                parent_pid=current_parent,
            )
        )
    return combine_detection(unit, process_results)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.parse_args(argv)
    result = detect_existing_runner(unit=read_unit_classification())
    sys.stdout.write(result.value + "\n")
    return {
        RunnerDetection.RUNNER_ABSENT: 0,
        RunnerDetection.RUNNER_PRESENT: 40,
        RunnerDetection.INDETERMINATE: 41,
    }[result]


if __name__ == "__main__":
    raise SystemExit(main())
