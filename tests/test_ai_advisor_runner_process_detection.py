import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from backend.ai_advisor.runner_process_detection import (
    RUNNER_MODULE,
    ProcessMetadata,
    RunnerDetection,
    UnitClassification,
    classify_process,
    classify_unit,
    combine_detection,
    detect_existing_runner,
    main,
    read_unit_classification,
)


def metadata(
    *,
    pid=100,
    ppid=10,
    comm="python",
    exe="/usr/bin/python3",
    argv=("/usr/bin/python3", "-m", RUNNER_MODULE),
):
    return ProcessMetadata(
        pid=pid,
        ppid=ppid,
        comm=comm,
        exe=exe,
        argv=argv,
    )


class RunnerProcessDetectionTest(unittest.TestCase):
    def test_shell_heredoc_grep_and_pgrep_text_are_not_runner(self):
        values = (
            metadata(comm="bash", exe="/bin/bash", argv=("bash", "-c", RUNNER_MODULE)),
            metadata(comm="sh", exe="/bin/sh", argv=("sh", RUNNER_MODULE)),
            metadata(comm="grep", exe="/usr/bin/grep", argv=("grep", RUNNER_MODULE)),
            metadata(comm="pgrep", exe="/usr/bin/pgrep", argv=("pgrep", RUNNER_MODULE)),
        )
        for value in values:
            with self.subTest(comm=value.comm):
                self.assertEqual(
                    classify_process(value, self_pid=1, parent_pid=2),
                    RunnerDetection.RUNNER_ABSENT,
                )

    def test_self_and_parent_are_excluded(self):
        for pid in (10, 11):
            with self.subTest(pid=pid):
                self.assertEqual(
                    classify_process(
                        metadata(pid=pid),
                        self_pid=10,
                        parent_pid=11,
                    ),
                    RunnerDetection.RUNNER_ABSENT,
                )

    def test_python_c_and_partial_module_are_not_runner(self):
        values = (
            ("python", "-c", f"print('{RUNNER_MODULE}')"),
            ("python", "-m", RUNNER_MODULE + ".other"),
            ("python", "--label=" + RUNNER_MODULE),
            ("python", "-m", "backend.ai_advisor.other", RUNNER_MODULE),
        )
        for argv in values:
            with self.subTest(argv=argv):
                self.assertEqual(
                    classify_process(
                        metadata(argv=argv),
                        self_pid=1,
                        parent_pid=2,
                    ),
                    RunnerDetection.RUNNER_ABSENT,
                )

    def test_python_comm_or_executable_is_accepted_when_other_is_unavailable(self):
        for value in (
            metadata(comm="python3", exe=None),
            metadata(comm=None, exe="/usr/bin/python3"),
        ):
            with self.subTest(comm=value.comm, exe=value.exe):
                self.assertEqual(
                    classify_process(value, self_pid=1, parent_pid=2),
                    RunnerDetection.RUNNER_PRESENT,
                )

    def test_conflicting_comm_and_executable_are_indeterminate(self):
        for value in (
            metadata(comm="worker", exe="/usr/bin/python3"),
            metadata(comm="python3", exe="/usr/bin/not-python"),
        ):
            with self.subTest(comm=value.comm, exe=value.exe):
                self.assertEqual(
                    classify_process(value, self_pid=1, parent_pid=2),
                    RunnerDetection.INDETERMINATE,
                )

    def test_exact_python_module_is_runner(self):
        self.assertEqual(
            classify_process(metadata(), self_pid=1, parent_pid=2),
            RunnerDetection.RUNNER_PRESENT,
        )

    def test_invalid_or_unavailable_process_metadata_is_indeterminate(self):
        values = (
            metadata(pid=0),
            metadata(ppid=None),
            metadata(comm=None, exe=None),
            metadata(argv=None),
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(
                    classify_process(value, self_pid=1, parent_pid=2),
                    RunnerDetection.INDETERMINATE,
                )

    def test_unit_classification_is_strict(self):
        self.assertEqual(
            classify_unit(
                load_state="loaded",
                active_state="active",
                sub_state="running",
            ),
            UnitClassification.ACTIVE,
        )
        self.assertEqual(
            classify_unit(
                load_state="loaded",
                active_state="inactive",
                sub_state="dead",
            ),
            UnitClassification.INACTIVE,
        )
        self.assertEqual(
            classify_unit(
                load_state="not-found",
                active_state="inactive",
                sub_state="dead",
            ),
            UnitClassification.NOT_FOUND,
        )
        for values in (
            (None, "inactive", "dead"),
            ("loaded", "failed", "failed"),
            ("not-found", "active", "running"),
        ):
            with self.subTest(values=values):
                self.assertEqual(
                    classify_unit(
                        load_state=values[0],
                        active_state=values[1],
                        sub_state=values[2],
                    ),
                    UnitClassification.INDETERMINATE,
                )

    def test_final_combination_is_fail_closed(self):
        self.assertEqual(
            combine_detection(UnitClassification.ACTIVE, ()),
            RunnerDetection.RUNNER_PRESENT,
        )
        for unit in (UnitClassification.INACTIVE, UnitClassification.NOT_FOUND):
            with self.subTest(unit=unit):
                self.assertEqual(
                    combine_detection(unit, (RunnerDetection.RUNNER_ABSENT,)),
                    RunnerDetection.RUNNER_ABSENT,
                )
                self.assertEqual(
                    combine_detection(unit, (RunnerDetection.RUNNER_PRESENT,)),
                    RunnerDetection.INDETERMINATE,
                )
        self.assertEqual(
            combine_detection(UnitClassification.INDETERMINATE, ()),
            RunnerDetection.INDETERMINATE,
        )

    def test_primary_unit_result_does_not_scan_processes(self):
        missing_proc = Path("/definitely-not-a-proc-directory")
        self.assertEqual(
            detect_existing_runner(
                unit=UnitClassification.ACTIVE,
                proc_root=missing_proc,
            ),
            RunnerDetection.RUNNER_PRESENT,
        )
        self.assertEqual(
            detect_existing_runner(
                unit=UnitClassification.INDETERMINATE,
                proc_root=missing_proc,
            ),
            RunnerDetection.INDETERMINATE,
        )

    def test_proc_cmdline_or_exe_failure_is_indeterminate(self):
        with tempfile.TemporaryDirectory() as directory:
            proc_root = Path(directory)
            process = proc_root / "100"
            process.mkdir()
            (process / "status").write_text(
                "Name:\tpython\nPPid:\t10\n",
                encoding="utf-8",
            )
            self.assertEqual(
                detect_existing_runner(
                    unit=UnitClassification.INACTIVE,
                    proc_root=proc_root,
                    self_pid=1,
                    parent_pid=2,
                ),
                RunnerDetection.INDETERMINATE,
            )

    def test_non_python_proc_does_not_require_cmdline(self):
        with tempfile.TemporaryDirectory() as directory:
            proc_root = Path(directory)
            process = proc_root / "100"
            process.mkdir()
            (process / "status").write_text(
                "Name:\tbash\nPPid:\t10\n",
                encoding="utf-8",
            )
            with patch(
                "backend.ai_advisor.runner_process_detection.os.readlink",
                return_value="/usr/bin/bash",
            ):
                self.assertEqual(
                    detect_existing_runner(
                        unit=UnitClassification.INACTIVE,
                        proc_root=proc_root,
                        self_pid=1,
                        parent_pid=2,
                    ),
                    RunnerDetection.RUNNER_ABSENT,
                )

    def test_unit_reader_rejects_errors_and_duplicate_metadata(self):
        cases = (
            subprocess.CompletedProcess((), 2, "", "denied"),
            subprocess.CompletedProcess(
                (),
                0,
                "LoadState=loaded\nLoadState=loaded\n"
                "ActiveState=inactive\nSubState=dead\n",
                "",
            ),
        )
        for completed in cases:
            with self.subTest(returncode=completed.returncode):
                self.assertEqual(
                    read_unit_classification(runner=lambda *args, **kwargs: completed),
                    UnitClassification.INDETERMINATE,
                )

    def test_main_maps_indeterminate_to_fail_closed_exit(self):
        with (
            patch(
                "backend.ai_advisor.runner_process_detection.read_unit_classification",
                return_value=UnitClassification.INDETERMINATE,
            ),
            patch(
                "backend.ai_advisor.runner_process_detection.detect_existing_runner",
                return_value=RunnerDetection.INDETERMINATE,
            ),
            patch("sys.stdout", StringIO()),
        ):
            self.assertEqual(main([]), 41)

    def test_source_has_no_kill_credential_or_environment_access(self):
        source = (
            Path(__file__).parents[1] / "backend/ai_advisor/runner_process_detection.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("os.environ", source)
        self.assertNotIn("kill(", source)
        self.assertNotIn("credential", source.lower())


if __name__ == "__main__":
    unittest.main()
