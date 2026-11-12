import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.money_management.loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
)
from backend.money_management.loss_application_registration import (
    shutdown_money_management_application,
    startup_money_management_application,
)
from backend.money_management.loss_persistence_adapter import (
    SaveStatus,
    save_loss_state,
)
from backend.money_management.loss_application_settings import (
    LossLimitApplicationSettingsError,
    resolve_loss_limit_application_configuration,
)
from tests.test_money_management_loss_persistence_contract import state


def _environment(persistence: Path, runtime_root: Path | None = None) -> dict[str, str]:
    result = {
        "MONEY_MANAGEMENT_ENABLED": "true",
        "MONEY_MANAGEMENT_PERSISTENCE_ENABLED": "true",
        "MONEY_MANAGEMENT_PERSISTENCE_PATH": str(persistence),
    }
    if runtime_root is not None:
        result["MONEY_MANAGEMENT_RUNTIME_ROOT"] = str(runtime_root)
    return result


def test_canonical_source_root_remains_the_default_boundary(tmp_path):
    runtime = tmp_path / "logs" / "runtime"
    runtime.mkdir(parents=True)
    configured = resolve_loss_limit_application_configuration(
        environ=_environment(runtime), repository_root=tmp_path,
    )
    assert configured.persistence_path == runtime.resolve()


def test_versioned_source_accepts_separate_explicit_runtime_root(tmp_path):
    source_root = tmp_path / "releases" / "candidate" / "app"
    source_root.mkdir(parents=True)
    runtime_root = tmp_path / "shared-runtime"
    persistence = runtime_root / "money-management"
    persistence.mkdir(parents=True)
    configured = resolve_loss_limit_application_configuration(
        environ=_environment(persistence, runtime_root),
        repository_root=source_root,
    )
    assert configured.persistence_path == persistence.resolve()


def test_versioned_source_starts_real_lifecycle_with_separate_runtime_root(tmp_path):
    source_root = tmp_path / "releases" / "candidate" / "app"
    source_root.mkdir(parents=True)
    runtime_root = tmp_path / "shared-runtime"
    runtime_root.mkdir()
    assert save_loss_state(state(), runtime_root).status is SaveStatus.SAVED
    configured = resolve_loss_limit_application_configuration(
        environ=_environment(runtime_root, runtime_root),
        repository_root=source_root,
    )
    app = SimpleNamespace(state=SimpleNamespace())
    registration = startup_money_management_application(app, configuration=configured)
    assert registration.composition_status is CompositionReadinessStatus.READY
    assert registration.safe_status.lifecycle_state is ApplicationLifecycleState.RUNNING
    assert registration.safe_status.runtime_available is True
    shutdown_money_management_application(app)


@pytest.mark.parametrize("runtime_root", ["relative/runtime", "", "/"])
def test_explicit_runtime_root_rejects_unsafe_values(tmp_path, runtime_root):
    persistence = tmp_path / "runtime"
    persistence.mkdir()
    environment = _environment(persistence)
    environment["MONEY_MANAGEMENT_RUNTIME_ROOT"] = runtime_root
    with pytest.raises(LossLimitApplicationSettingsError):
        resolve_loss_limit_application_configuration(
            environ=environment, repository_root=tmp_path / "source",
        )


def test_explicit_runtime_root_must_exist(tmp_path):
    missing = tmp_path / "missing-runtime"
    with pytest.raises(LossLimitApplicationSettingsError, match="runtime root unavailable"):
        resolve_loss_limit_application_configuration(
            environ=_environment(missing, missing),
            repository_root=tmp_path / "source",
        )


def test_explicit_runtime_root_rejects_symlink_loop(tmp_path):
    loop = tmp_path / "loop"
    os.symlink(loop, loop)
    with pytest.raises(LossLimitApplicationSettingsError, match="runtime root unavailable"):
        resolve_loss_limit_application_configuration(
            environ=_environment(loop, loop),
            repository_root=tmp_path / "source",
        )


def test_traversal_outside_explicit_runtime_root_is_rejected(tmp_path):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(
        LossLimitApplicationSettingsError,
        match="persistence path is outside runtime data",
    ):
        resolve_loss_limit_application_configuration(
            environ=_environment(runtime_root / ".." / "outside", runtime_root),
            repository_root=tmp_path / "source",
        )


def test_symlink_escape_outside_explicit_runtime_root_is_rejected(tmp_path):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = runtime_root / "linked-outside"
    os.symlink(outside, link)
    with pytest.raises(
        LossLimitApplicationSettingsError,
        match="persistence path is outside runtime data",
    ):
        resolve_loss_limit_application_configuration(
            environ=_environment(link, runtime_root),
            repository_root=tmp_path / "source",
        )
