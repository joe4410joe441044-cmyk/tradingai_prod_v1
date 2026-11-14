import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import subprocess
import sys

import pytest

from backend.money_management import config_persistence
from backend.money_management.config_persistence import (
    CONFIG_PATH_ENVIRONMENT_VARIABLE,
    MoneyManagementConfigStore,
    build_envelope,
)
from backend.money_management.loss_application_registration import (
    build_default_money_management_config,
)
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


def _approved_small_account_config():
    return replace(
        build_default_money_management_config(),
        small_account_minimum_contract_mode=True,
        small_account_allowed_symbol="XRPUSDTM",
        small_account_max_contracts=Decimal("1"),
        small_account_max_risk_percent=Decimal("2.0"),
        small_account_max_absolute_risk_usdt=Decimal("0.158"),
        small_account_max_leverage=Decimal("3"),
        small_account_require_isolated=True,
        small_account_require_flat_before_entry=True,
        small_account_require_no_pending=True,
        small_account_require_manual_selection=True,
    )


def test_mm_config_store_prefers_explicit_external_path_over_release_location(
    tmp_path, monkeypatch
):
    external = tmp_path / "external" / "money_management_config.json"
    external.parent.mkdir()
    release_app = tmp_path / "releases" / "abc123" / "app"
    (release_app / "backend" / "money_management").mkdir(parents=True)

    monkeypatch.delenv(CONFIG_PATH_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(
        config_persistence,
        "__file__",
        str(release_app / "backend" / "money_management" / "config_persistence.py"),
    )

    release_default = release_app / "logs" / "runtime" / "money_management_config.json"
    assert config_persistence.resolve_default_config_path() == release_default

    monkeypatch.setenv(CONFIG_PATH_ENVIRONMENT_VARIABLE, str(external))

    store = MoneyManagementConfigStore()
    assert store.path == external
    assert store.path != release_default

    assert not release_default.parent.exists()
    assert store.save(_approved_small_account_config(), 2) == external
    assert external.is_file()
    assert not release_default.parent.exists()


def test_external_persisted_config_preserves_revision_and_approved_profile(
    tmp_path, monkeypatch
):
    external = tmp_path / "external" / "money_management_config.json"
    external.parent.mkdir()
    updated_at = datetime(2026, 10, 16, 19, 33, 45, 286865, tzinfo=timezone.utc)
    external.write_text(
        json.dumps(build_envelope(_approved_small_account_config(), 2, updated_at)),
        encoding="utf-8",
    )
    monkeypatch.setenv(CONFIG_PATH_ENVIRONMENT_VARIABLE, str(external))

    state = MoneyManagementConfigStore().load()

    assert state is not None
    assert state.config_revision == 2
    config = state.config
    assert config.small_account_minimum_contract_mode is True
    assert config.small_account_allowed_symbol == "XRPUSDTM"
    assert config.small_account_max_contracts == Decimal("1")
    assert config.small_account_max_risk_percent == Decimal("2.0")
    assert config.small_account_max_absolute_risk_usdt == Decimal("0.158")
    assert config.small_account_max_leverage == Decimal("3")
    assert config.small_account_require_isolated is True


def test_tracked_systemd_contract_externalizes_mm_config_path():
    lines = (
        REPOSITORY_ROOT / "systemd" / "tradingbot.service.d" / "money-management.conf"
    ).read_text(encoding="utf-8").splitlines()

    assert "[Service]" in lines
    assert "Environment=MONEY_MANAGEMENT_ENABLED=true" in lines
    assert "Environment=MONEY_MANAGEMENT_PERSISTENCE_ENABLED=true" in lines
    assert (
        "Environment=MONEY_MANAGEMENT_PERSISTENCE_PATH="
        "/home/joe4410joe/tradingai_prod_v1/logs/runtime"
    ) in lines
    assert (
        "Environment=TRADINGAI_MONEY_MANAGEMENT_CONFIG_PATH="
        "/home/joe4410joe/tradingai_prod_v1/logs/runtime/money_management_config.json"
    ) in lines
