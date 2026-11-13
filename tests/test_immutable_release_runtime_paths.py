import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.money_management.loss_application_settings import (
    LossLimitApplicationSettingsError,
    resolve_money_management_timeline_directory,
)
from backend.supervisor.audit_store import (
    DEFAULT_SUPERVISOR_AUDIT_PATH,
    SupervisorBoundaryError,
    resolve_supervisor_audit_path,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _import_log_buffer(environment):
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.utils.log_buffer import LOG_DIR; print(LOG_DIR)",
        ],
        cwd=REPOSITORY_ROOT,
        env={
            **os.environ,
            **environment,
            "PYTHONPATH": str(REPOSITORY_ROOT),
            "TRADINGAI_ISOLATED_STDIO_ONLY": "true",
        },
        text=True,
        capture_output=True,
    )


def test_configured_log_directory_resolves_outside_release(tmp_path):
    destination = tmp_path / "logs"
    destination.mkdir()

    result = _import_log_buffer({"TRADINGAI_LOG_DIR": str(destination)})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(destination)


@pytest.mark.parametrize("value", ("", "logs"))
def test_configured_log_directory_rejects_empty_or_relative(value):
    result = _import_log_buffer({"TRADINGAI_LOG_DIR": value})

    assert result.returncode != 0
    assert "configured log directory" in result.stderr


def test_configured_log_directory_rejects_symlink(tmp_path):
    destination = tmp_path / "real"
    destination.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(destination, target_is_directory=True)

    result = _import_log_buffer({"TRADINGAI_LOG_DIR": str(alias)})

    assert result.returncode != 0
    assert "configured log directory is unsafe" in result.stderr


def test_supervisor_audit_path_resolves_external_existing_parent(tmp_path):
    path = tmp_path / "runtime" / "supervisor_audit.sqlite3"
    path.parent.mkdir()

    assert resolve_supervisor_audit_path(
        {"AI_SUPERVISOR_AUDIT_PATH": str(path)}
    ) == path


def test_supervisor_audit_path_preserves_canonical_default():
    assert resolve_supervisor_audit_path({}) == DEFAULT_SUPERVISOR_AUDIT_PATH


@pytest.mark.parametrize("value", ("", "logs/runtime/audit.sqlite3"))
def test_supervisor_audit_path_rejects_empty_or_relative(value):
    with pytest.raises(SupervisorBoundaryError):
        resolve_supervisor_audit_path({"AI_SUPERVISOR_AUDIT_PATH": value})


def test_supervisor_audit_path_rejects_symlink_parent(tmp_path):
    destination = tmp_path / "real"
    destination.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(destination, target_is_directory=True)

    with pytest.raises(SupervisorBoundaryError):
        resolve_supervisor_audit_path(
            {"AI_SUPERVISOR_AUDIT_PATH": str(alias / "audit.sqlite3")}
        )


def test_timeline_uses_validated_mm_persistence_directory(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    environment = {
        "MONEY_MANAGEMENT_ENABLED": "true",
        "MONEY_MANAGEMENT_PERSISTENCE_ENABLED": "true",
        "MONEY_MANAGEMENT_PERSISTENCE_PATH": str(runtime),
        "MONEY_MANAGEMENT_RUNTIME_ROOT": str(runtime),
    }

    assert resolve_money_management_timeline_directory(environ=environment) == runtime

    environment["MONEY_MANAGEMENT_PERSISTENCE_PATH"] = str(tmp_path)
    with pytest.raises(LossLimitApplicationSettingsError):
        resolve_money_management_timeline_directory(environ=environment)


def test_main_wires_validated_timeline_directory():
    source = (REPOSITORY_ROOT / "backend" / "main.py").read_text(encoding="utf-8")

    assert "timeline_directory=resolve_money_management_timeline_directory()" in source
