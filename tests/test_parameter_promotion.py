"""E-PARAM-5 focused tests: canonical PENDING -> EFFECTIVE promotion.

These tests prove the safe promotion boundary and its invariants:

- STOPPED and RUNNING+FLAT promotion;
- OPEN POSITION deferred promotion (open trade keeps its entry revision);
- PAPER / LIVE promotion isolation;
- promotion persistence and fail-closed behavior;
- configured / effective / runtime revision distinction and monotonicity;
- runtime revision value consistency with the resolver snapshot;
- immutable entry snapshots.
"""

from pathlib import Path

import pytest

from backend.strategy.parameters.model import ParameterStatus
from backend.strategy.parameters.promotion_service import (
    ParameterPromotionService,
    PromotionOutcome,
)
from backend.strategy.parameters.resolver import CanonicalParameterResolver
from backend.strategy.parameters.runtime_registry import (
    get_runtime_snapshot,
    record_runtime_snapshot,
    reset_runtime_snapshots,
)
from backend.strategy.parameters.settings_service import (
    ParameterSettingsService,
    UpdateOutcome,
)
from backend.strategy.parameters.store import (
    StoreFailureCode,
    StoreSaveResult,
    StoreSaveStatus,
)

SCOPE = "PAPER"
LIVE = "LIVE"


@pytest.fixture(autouse=True)
def _clean_runtime_registry():
    reset_runtime_snapshots()
    yield
    reset_runtime_snapshots()


def _service(tmp_path: Path) -> ParameterSettingsService:
    return ParameterSettingsService(base_directory=tmp_path)


def _write(service, scope, mutate):
    configuration = service.configuration(scope)
    parameters = dict(configuration["parameters"])
    mutate(parameters)
    result = service.update_configuration(
        scope=scope,
        parameters=parameters,
        expected_revision=configuration["configuredRevision"],
        confirm_live=scope == LIVE,
    )
    assert result.outcome is UpdateOutcome.ACCEPTED, result.payload
    return result.payload


def _set_composite(parameters):
    parameters["minimumCompositeScore"] = 0.42


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_write_is_pending_until_safely_promoted(tmp_path):
    service = _service(tmp_path)
    before = service.configuration(SCOPE)
    assert before["configuredRevision"] == 1
    assert before["effectiveRevision"] == 1
    assert before["pending"] is False

    payload = _write(service, SCOPE, _set_composite)
    assert payload["configuredRevision"] == 2
    assert payload["effectiveRevision"] == 1
    assert payload["status"] == "PENDING"

    configuration = service.configuration(SCOPE)
    assert configuration["configuredRevision"] == 2
    assert configuration["effectiveRevision"] == 1
    assert configuration["pending"] is True
    assert configuration["status"] == "PENDING"

    # The effective values are still the previous revision.
    effective = service.effective(SCOPE)
    assert effective["effectiveRevision"] == 1
    assert effective["parameters"]["minimumCompositeScore"] != 0.42

    promotion = service.promote_if_safe(SCOPE, safe_to_promote=True)
    assert promotion["outcome"] == PromotionOutcome.PROMOTED.value
    assert promotion["promoted"] is True

    configuration = service.configuration(SCOPE)
    assert configuration["configuredRevision"] == 2
    assert configuration["effectiveRevision"] == 2
    assert configuration["pending"] is False
    assert configuration["status"] == "ACTIVE"

    effective = service.effective(SCOPE)
    assert effective["effectiveRevision"] == 2
    assert effective["parameters"]["minimumCompositeScore"] == 0.42


def test_stopped_promotion(tmp_path):
    """A valid pending revision promotes while the bot is STOPPED."""

    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)
    result = service.promote_if_safe(
        SCOPE, safe_to_promote=True, open_position=False
    )
    assert result["outcome"] == PromotionOutcome.PROMOTED.value
    assert service.configuration(SCOPE)["effectiveRevision"] == 2


def test_running_flat_promotion_and_runtime_consistency(tmp_path):
    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)
    result = service.promote_if_safe(
        SCOPE, safe_to_promote=True, open_position=False
    )
    assert result["outcome"] == PromotionOutcome.PROMOTED.value

    # Runtime revision equals the revision actually resolved for consumption.
    snapshot = CanonicalParameterResolver(base_directory=tmp_path).resolve_paper()
    assert snapshot.effectiveRevision == 2
    assert snapshot.configuredRevision == 2
    assert snapshot.parameters["minimumCompositeScore"] == 0.42
    assert snapshot.parameter_value("minimumCompositeScore") == 0.42

    record_runtime_snapshot("PAPER", snapshot)
    runtime = service.runtime(SCOPE)
    assert runtime["effectiveRevision"] == 2
    assert runtime["parameters"]["minimumCompositeScore"] == 0.42
    assert get_runtime_snapshot("PAPER")["effectiveRevision"] == 2


def test_open_position_deferred_then_promoted(tmp_path):
    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)

    deferred = service.promote_if_safe(
        SCOPE, safe_to_promote=False, open_position=True
    )
    assert deferred["outcome"] == PromotionOutcome.DEFERRED_OPEN_POSITION.value
    assert deferred["promoted"] is False
    # The open position keeps its entry revision (R1).
    assert service.configuration(SCOPE)["effectiveRevision"] == 1
    assert service.effective(SCOPE)["effectiveRevision"] == 1
    assert service.effective(SCOPE)["parameters"][
        "minimumCompositeScore"
    ] != 0.42

    # Position closes; next safe flat boundary promotes R2.
    promoted = service.promote_if_safe(
        SCOPE, safe_to_promote=True, open_position=False
    )
    assert promoted["outcome"] == PromotionOutcome.PROMOTED.value
    assert service.effective(SCOPE)["effectiveRevision"] == 2
    assert service.effective(SCOPE)["parameters"][
        "minimumCompositeScore"
    ] == 0.42


def test_running_but_not_safe_defers(tmp_path):
    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)
    result = service.promote_if_safe(
        SCOPE, safe_to_promote=False, open_position=False
    )
    assert result["outcome"] == PromotionOutcome.DEFERRED_NOT_SAFE.value
    assert service.effective(SCOPE)["effectiveRevision"] == 1


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def test_paper_live_promotion_isolation(tmp_path):
    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)

    # A PAPER pending revision never promotes LIVE.
    live = service.promote_if_safe(LIVE, safe_to_promote=True)
    assert live["outcome"] == PromotionOutcome.NO_PENDING.value
    assert service.effective(LIVE)["effectiveRevision"] == 1

    assert service.promote_if_safe(
        SCOPE, safe_to_promote=True
    )["outcome"] == PromotionOutcome.PROMOTED.value

    # A LIVE pending revision never promotes PAPER.
    _write(service, LIVE, lambda values: values.update(
        {"minimumCompositeScore": 0.61}
    ))
    paper_effective = service.effective(SCOPE)["effectiveRevision"]
    assert service.promote_if_safe(
        SCOPE, safe_to_promote=True
    )["outcome"] == PromotionOutcome.NO_PENDING.value
    assert service.effective(SCOPE)["effectiveRevision"] == paper_effective

    assert service.promote_if_safe(
        LIVE, safe_to_promote=True
    )["outcome"] == PromotionOutcome.PROMOTED.value
    assert service.effective(LIVE)["effectiveRevision"] == 2


# ---------------------------------------------------------------------------
# Persistence / fail-closed
# ---------------------------------------------------------------------------


def test_promotion_persists_effective_and_preserves_configured_audit(tmp_path):
    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)
    assert service.promote_if_safe(
        SCOPE, safe_to_promote=True
    )["outcome"] == PromotionOutcome.PROMOTED.value

    # Fresh service (fresh store) observes the promoted effective record.
    reloaded = _service(tmp_path)
    effective = reloaded.effective(SCOPE)
    assert effective["effectiveRevision"] == 2
    assert effective["parameters"]["minimumCompositeScore"] == 0.42

    # Historical configured revision metadata is preserved for audit.
    from backend.strategy.parameters.model import ParameterScope

    configured = reloaded.store.load(ParameterScope.PAPER).parameter_set
    assert configured.configuredRevision == 2
    assert configured.status is ParameterStatus.PENDING


def test_promotion_fail_closed_on_persistence_failure(tmp_path):
    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)

    store = service.promotion.store

    def failing_save(parameter_set, variant=None):
        return StoreSaveResult(
            StoreSaveStatus.FAILED,
            StoreFailureCode.WRITE_FAILED,
            "simulated failure",
        )

    original = store.save
    store.save = failing_save
    try:
        result = service.promote_if_safe(SCOPE, safe_to_promote=True)
    finally:
        store.save = original

    assert result["outcome"] == PromotionOutcome.PERSISTENCE_FAILURE.value
    assert result["promoted"] is False
    # Effective authority is unchanged (still R1).
    assert service.effective(SCOPE)["effectiveRevision"] == 1
    assert service.configuration(SCOPE)["effectiveRevision"] == 1


def test_promotion_fail_closed_on_corrupt_configured(tmp_path):
    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)
    configured_path = service.store.path_for("PAPER")
    configured_path.write_bytes(b"{not-json")

    result = service.promote_if_safe(SCOPE, safe_to_promote=True)
    assert result["outcome"] == PromotionOutcome.REVISION_INCONSISTENCY.value
    assert result["promoted"] is False
    assert service.effective(SCOPE)["effectiveRevision"] == 1


def test_no_revision_churn_on_repeated_promotion(tmp_path):
    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)
    first = service.promote_if_safe(SCOPE, safe_to_promote=True)
    assert first["outcome"] == PromotionOutcome.PROMOTED.value
    assert first["effectiveRevision"] == 2

    for _ in range(3):
        repeated = service.promote_if_safe(SCOPE, safe_to_promote=True)
        assert repeated["outcome"] == PromotionOutcome.NO_PENDING.value
        assert repeated["promoted"] is False

    configuration = service.configuration(SCOPE)
    assert configuration["configuredRevision"] == 2
    assert configuration["effectiveRevision"] == 2


def test_promotion_service_no_pending_without_write(tmp_path):
    service = ParameterPromotionService(base_directory=tmp_path)
    result = service.promote_pending("PAPER", safe_to_promote=True)
    assert result.outcome is PromotionOutcome.NO_PENDING
    assert result.promoted is False


def test_promotion_rejects_unknown_scope(tmp_path):
    service = ParameterPromotionService(base_directory=tmp_path)
    result = service.promote_pending("BOTH", safe_to_promote=True)
    assert result.outcome is PromotionOutcome.INVALID_SCOPE


# ---------------------------------------------------------------------------
# Snapshot immutability
# ---------------------------------------------------------------------------


def test_entry_snapshot_is_immutable(tmp_path):
    service = _service(tmp_path)
    _write(service, SCOPE, _set_composite)
    service.promote_if_safe(SCOPE, safe_to_promote=True)
    snapshot = CanonicalParameterResolver(base_directory=tmp_path).resolve_paper()
    with pytest.raises(TypeError):
        snapshot.parameters["minimumCompositeScore"] = 0.99
    with pytest.raises(TypeError):
        snapshot.runtimeParameters["minimumCompositeScore"] = {}
    assert snapshot.effectiveRevision == 2
