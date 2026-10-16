"""D-LIVE-11A durable Small Account configuration write contract."""
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend.money_management.config_persistence import (
    CONFIG_PERSISTENCE_SCHEMA_VERSION,
    MoneyManagementConfigCorruptError,
    MoneyManagementConfigStore,
    build_envelope,
    load_or_default_money_management_config,
)
from backend.money_management.loss_application_registration import (
    MoneyManagementConfigProvider,
    build_default_money_management_config,
)
from backend.money_management.loss_http_api import (
    MoneyManagementApiBoundaryException,
    MoneyManagementHttpBoundary,
)
from backend.money_management.loss_runtime_hook import (
    MoneyManagementRuntimeHookRegistration,
)
from backend.money_management.order_sizing import (
    OrderSizingAuthority,
    SizingRejected,
)
from tests.test_money_management_api import ready_boundary

_XRP = "XRPUSDTM"
_APPROVED_PROFILE = {
    "small_account_minimum_contract_mode": True,
    "small_account_allowed_symbol": _XRP,
    "small_account_max_contracts": Decimal("1"),
    "small_account_max_risk_percent": Decimal("2.0"),
    "small_account_max_absolute_risk_usdt": Decimal("0.158"),
    "small_account_max_leverage": Decimal("3"),
    "small_account_require_isolated": True,
    "small_account_require_flat_before_entry": True,
    "small_account_require_no_pending": True,
    "small_account_require_manual_selection": True,
}


def _assert_approved_profile(config):
    for field, expected in _APPROVED_PROFILE.items():
        assert getattr(config, field) == expected, field


def _store(tmp_path):
    return MoneyManagementConfigStore(path=tmp_path / "money_management_config.json")


def _boundary_with_store(store):
    boundary, app, dispatcher, lifecycle, clock = ready_boundary()
    app.state.money_management = replace(
        app.state.money_management,
        base_config_provider=MoneyManagementConfigProvider(
            load_or_default_money_management_config(store=store)
        ),
    )
    return (
        MoneyManagementHttpBoundary(
            app, dispatcher, timestamp_source=clock, config_store=store
        ),
        app,
        dispatcher,
        lifecycle,
        clock,
    )


class _SideEffectBot:
    def __init__(self):
        self.lifecycle_state = "RUNNING"
        self.config = {"mode": "paper"}
        self.calls = []

    def start(self, *args, **kwargs):
        self.calls.append("start")

    def arm(self, *args, **kwargs):
        self.calls.append("arm")

    def create_order(self, *args, **kwargs):
        self.calls.append("create_order")

    def set_money_management_runtime_hook(self, callback):
        return True


def small_account_authority(**changes):
    values = dict(
        symbol=_XRP,
        price="1.5205",
        equity="7.91836966",
        available="7.91836966",
        risk_percent="0.5",
        sl_percent="1",
        leverage="3",
        fixed_notional="0",
        position_cap="1000",
        symbol_capacity="1000",
        total_capacity="1000",
        multiplier="10",
        minimum="1",
        step="1",
        maximum="1000000",
        small_account_mode=True,
        small_account_allowed_symbol=_XRP,
        small_account_max_contracts="1",
        small_account_max_risk_percent="2",
        small_account_max_absolute_risk_usdt="0.158",
        small_account_max_leverage="3",
        live=True,
        entry_authority="MANUAL",
        configured_symbol=_XRP,
        loop_enabled=False,
        position_flat=True,
        pending_known=True,
        pending=False,
        margin_mode_known=True,
        margin_mode="ISOLATED",
        margin_mode_compatible=True,
        leverage_explicit=True,
    )
    values.update(changes)
    return OrderSizingAuthority(**values)


# --------------------------------------------------------------------------
# WRITE CONTRACT
# --------------------------------------------------------------------------


def test_mode_false_to_true_succeeds_and_get_returns_true():
    boundary, app, *_ = ready_boundary()
    assert boundary.get_configuration().to_dict()[
        "smallAccountMinimumContractMode"
    ] is False

    result = boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )

    assert result.applied
    assert result.configuration.small_account_minimum_contract_mode is True
    rendered = boundary.get_configuration().to_dict()
    assert rendered["smallAccountMinimumContractMode"] is True
    _assert_approved_profile(
        app.state.money_management.base_config_provider.get_config()
    )


def test_revision_increments_and_persists_change():
    boundary, *_ = ready_boundary()
    result = boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    assert result.configuration.revision == 2
    assert boundary.configuration_revision == 2


def test_stale_revision_rejects_without_mutation():
    boundary, app, *_ = ready_boundary()
    boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    before = boundary.get_configuration()
    with pytest.raises(MoneyManagementApiBoundaryException) as raised:
        boundary.update_configuration(
            {"smallAccountMinimumContractMode": False, "expectedRevision": 1}
        )
    assert raised.value.error.status_code == 409
    assert raised.value.error.code == "CONFIGURATION_REVISION_CONFLICT"
    assert boundary.get_configuration() == before


def test_failed_update_leaves_revision_and_configuration_unchanged():
    boundary, app, *_ = ready_boundary()
    before = boundary.get_configuration()
    with pytest.raises(MoneyManagementApiBoundaryException):
        boundary.update_configuration(
            {
                "smallAccountMinimumContractMode": True,
                "smallAccountMaxRiskPercent": "2.01",
                "expectedRevision": 1,
            }
        )
    assert boundary.configuration_revision == 1
    assert boundary.get_configuration() == before
    assert (
        app.state.money_management.base_config_provider.get_config()
        .small_account_minimum_contract_mode
        is False
    )


def test_unrelated_money_management_fields_are_preserved():
    boundary, app, *_ = ready_boundary()
    boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    config = app.state.money_management.base_config_provider.get_config()
    assert config.total_exposure_pct == Decimal("20")
    assert config.risk_per_trade_pct == Decimal("0.50")
    assert config.maximum_position_notional == Decimal("100")
    assert config.single_symbol_exposure_pct == Decimal("10")
    assert config.maximum_leverage == Decimal("5")
    assert config.daily_loss_warning_pct == Decimal("1.00")
    assert config.daily_loss_block_pct == Decimal("1.50")
    assert config.compounding_enabled is False
    rendered = boundary.get_configuration().to_dict()
    assert rendered["totalExposurePercent"] == "20"
    assert rendered["riskPerTradePercent"] == "0.50"
    assert rendered["dailyWarningPercent"] == "1.00"


def test_mode_true_to_false_preserves_stored_profile():
    boundary, app, *_ = ready_boundary()
    boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    result = boundary.update_configuration(
        {"smallAccountMinimumContractMode": False, "expectedRevision": 2}
    )
    assert result.applied
    assert result.configuration.small_account_minimum_contract_mode is False
    config = app.state.money_management.base_config_provider.get_config()
    assert config.small_account_minimum_contract_mode is False
    assert config.small_account_allowed_symbol == _XRP
    assert config.small_account_max_contracts == Decimal("1")
    assert config.small_account_max_risk_percent == Decimal("2.0")
    assert config.small_account_max_absolute_risk_usdt == Decimal("0.158")
    assert config.small_account_max_leverage == Decimal("3")


def test_unsupported_fields_are_rejected():
    boundary, *_ = ready_boundary()
    for payload in (
        {"smallAccountUnsupported": True},
        {"smallAccountMinimumContractMode": True, "bogus": 1},
        {"small_account_minimum_contract_mode": True},
    ):
        with pytest.raises(MoneyManagementApiBoundaryException) as raised:
            boundary.update_configuration({**payload, "expectedRevision": 1})
        assert raised.value.error.status_code == 422


@pytest.mark.parametrize(
    "payload",
    (
        {"smallAccountMinimumContractMode": "true"},
        {"smallAccountMinimumContractMode": 1},
        {"smallAccountRequireIsolated": "false"},
        {"smallAccountMaxContracts": "1.5"},
        {"smallAccountMaxContracts": 0},
        {"smallAccountMaxContracts": "NaN"},
        {"smallAccountMaxLeverage": "Infinity"},
        {"smallAccountMaxRiskPercent": "-1"},
        {"smallAccountAllowedSymbol": ""},
        {"smallAccountAllowedSymbol": None},
        {"smallAccountAllowedSymbol": "UNKNOWN"},
        {"smallAccountAllowedSymbol": "NOT AVAILABLE"},
    ),
)
def test_malformed_small_account_values_are_rejected(payload):
    boundary, *_ = ready_boundary()
    with pytest.raises(MoneyManagementApiBoundaryException) as raised:
        boundary.update_configuration({**payload, "expectedRevision": 1})
    assert raised.value.error.status_code == 422


def test_symbol_normalization_accepts_canonical_forms():
    boundary, app, *_ = ready_boundary()
    result = boundary.update_configuration(
        {
            "smallAccountMinimumContractMode": True,
            "smallAccountAllowedSymbol": "xrpusdt",
            "expectedRevision": 1,
        }
    )
    assert result.applied
    assert (
        app.state.money_management.base_config_provider.get_config()
        .small_account_allowed_symbol
        == _XRP
    )


# --------------------------------------------------------------------------
# SAFETY
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    (
        {"smallAccountMaxContracts": "2"},
        {"smallAccountMaxRiskPercent": "2.01"},
        {"smallAccountMaxRiskPercent": "5"},
        {"smallAccountMaxAbsoluteRiskUsdt": "0.159"},
        {"smallAccountMaxAbsoluteRiskUsdt": None},
        {"smallAccountMaxLeverage": "4"},
        {"smallAccountRequireIsolated": False},
        {"smallAccountRequireFlatBeforeEntry": False},
        {"smallAccountRequireNoPending": False},
        {"smallAccountRequireManualSelection": False},
        {"smallAccountAllowedSymbol": "BTCUSDTM"},
        {"smallAccountAllowedSymbol": "ETHUSDT"},
    ),
)
def test_unsafe_small_account_candidates_fail_closed(payload):
    boundary, app, *_ = ready_boundary()
    with pytest.raises(MoneyManagementApiBoundaryException) as raised:
        boundary.update_configuration(
            {
                "smallAccountMinimumContractMode": True,
                **payload,
                "expectedRevision": 1,
            }
        )
    assert raised.value.error.status_code == 422
    assert (
        app.state.money_management.base_config_provider.get_config()
        .small_account_minimum_contract_mode
        is False
    )


def test_cross_field_validation_applies_to_merged_candidate():
    boundary, *_ = ready_boundary()
    # Absolute cap omitted: canonical default profile (0.158) is merged and safe.
    result = boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    assert result.applied
    # Explicitly widening a previously approved value must be rejected.
    with pytest.raises(MoneyManagementApiBoundaryException):
        boundary.update_configuration(
            {"smallAccountMaxLeverage": "4", "expectedRevision": 2}
        )


# --------------------------------------------------------------------------
# PERSISTENCE
# --------------------------------------------------------------------------


def test_missing_file_loads_canonical_default_off(tmp_path):
    store = _store(tmp_path)
    assert store.load() is None
    config = load_or_default_money_management_config(store=store)
    assert config.small_account_minimum_contract_mode is False
    assert config.small_account_allowed_symbol == _XRP
    assert config.small_account_max_absolute_risk_usdt == Decimal("0.158")


def test_mode_on_persists_and_reloads(tmp_path):
    store = _store(tmp_path)
    boundary, *_ = _boundary_with_store(store)
    result = boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    assert result.applied
    state = store.load()
    assert state is not None
    _assert_approved_profile(state.config)
    reloaded = load_or_default_money_management_config(store=store)
    assert reloaded.small_account_minimum_contract_mode is True

    restarted, *_ = _boundary_with_store(store)
    assert restarted.configuration_revision == state.config_revision
    assert (
        restarted.get_configuration().small_account_minimum_contract_mode is True
    )


def test_mode_off_persists_while_profile_remains_stored(tmp_path):
    store = _store(tmp_path)
    boundary, *_ = _boundary_with_store(store)
    boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    boundary.update_configuration(
        {"smallAccountMinimumContractMode": False, "expectedRevision": 2}
    )
    state = store.load()
    assert state.config.small_account_minimum_contract_mode is False
    assert state.config.small_account_allowed_symbol == _XRP
    assert state.config.small_account_max_risk_percent == Decimal("2.0")


def test_revision_is_durable_across_restart(tmp_path):
    store = _store(tmp_path)
    boundary, *_ = _boundary_with_store(store)
    boundary.update_configuration(
        {"dailyWarningPercent": "0.50", "expectedRevision": 1}
    )
    boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 2}
    )
    assert store.load().config_revision == 3
    restarted, *_ = _boundary_with_store(store)
    assert restarted.configuration_revision == 3
    with pytest.raises(MoneyManagementApiBoundaryException) as raised:
        restarted.update_configuration(
            {"smallAccountMinimumContractMode": False, "expectedRevision": 1}
        )
    assert raised.value.error.code == "CONFIGURATION_REVISION_CONFLICT"


def test_failed_update_does_not_persist(tmp_path):
    store = _store(tmp_path)
    boundary, *_ = _boundary_with_store(store)
    with pytest.raises(MoneyManagementApiBoundaryException):
        boundary.update_configuration(
            {
                "smallAccountMinimumContractMode": True,
                "smallAccountMaxRiskPercent": "3",
                "expectedRevision": 1,
            }
        )
    assert store.load() is None


@pytest.mark.parametrize(
    "content",
    (
        "{not valid json",
        "[]",
        json.dumps({"schemaVersion": 999, "configRevision": 1}),
        json.dumps(
            {
                "schemaVersion": CONFIG_PERSISTENCE_SCHEMA_VERSION,
                "configRevision": 1,
                "updatedAt": "2026-01-01T00:00:00Z",
                "config": {"profile": "CAPITAL_PROTECTION_STANDARD"},
            }
        ),
    ),
)
def test_corrupt_or_unknown_schema_fails_closed(tmp_path, content):
    store = _store(tmp_path)
    store.path.write_text(content, encoding="utf-8")
    with pytest.raises(MoneyManagementConfigCorruptError):
        store.load()
    config = load_or_default_money_management_config(store=store)
    assert config.small_account_minimum_contract_mode is False


def test_unsafe_persisted_config_fails_closed(tmp_path):
    store = _store(tmp_path)
    unsafe = replace(
        build_default_money_management_config(),
        small_account_minimum_contract_mode=True,
        small_account_max_risk_percent=Decimal("5"),
    )
    envelope = build_envelope(unsafe, 2, datetime.now(timezone.utc))
    store.path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(MoneyManagementConfigCorruptError):
        store.load()
    assert (
        load_or_default_money_management_config(store=store)
        .small_account_minimum_contract_mode
        is False
    )


def test_persistence_contains_no_credentials(tmp_path):
    store = _store(tmp_path)
    boundary, *_ = _boundary_with_store(store)
    boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    raw = store.path.read_text(encoding="utf-8")
    envelope = json.loads(raw)
    assert set(envelope) == {
        "schemaVersion",
        "configRevision",
        "updatedAt",
        "config",
    }
    assert set(envelope["config"]) == set(
        build_default_money_management_config().to_dict()
    )
    lowered = raw.lower()
    for token in (
        "api_key",
        "apikey",
        "secret",
        "passphrase",
        "password",
        "token",
        "credential",
        "private",
    ):
        assert token not in lowered


def test_default_construction_never_writes_production_path():
    resolved = MoneyManagementConfigStore().path
    assert resolved == Path(os.environ["TRADINGAI_MONEY_MANAGEMENT_CONFIG_PATH"])
    boundary, *_ = ready_boundary()
    boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    assert not resolved.exists()
    production = (
        Path(__file__).resolve().parents[1]
        / "logs"
        / "runtime"
        / "money_management_config.json"
    )
    assert resolved != production
    assert not production.exists()


# --------------------------------------------------------------------------
# SIDE EFFECTS
# --------------------------------------------------------------------------


def test_configuration_mutation_does_not_start_arm_or_trade():
    boundary, app, *_ = ready_boundary()
    bot = _SideEffectBot()
    bot.lifecycle_state = "STOPPED"
    registration = app.state.money_management_runtime_hook
    app.state.money_management_runtime_hook = MoneyManagementRuntimeHookRegistration(
        registration.hook, bot, registration.registered_at
    )
    result = boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    assert result.applied
    assert bot.calls == []
    assert bot.lifecycle_state == "STOPPED"


def test_configuration_mutation_makes_no_exchange_call(monkeypatch):
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        Mock(side_effect=AssertionError("REAL_NETWORK_FORBIDDEN")),
    )
    boundary, *_ = ready_boundary()
    result = boundary.update_configuration(
        {"smallAccountMinimumContractMode": True, "expectedRevision": 1}
    )
    assert result.applied
    assert result.reevaluated


# --------------------------------------------------------------------------
# SIZING REGRESSION
# --------------------------------------------------------------------------


def test_one_contract_special_path_passes():
    result = small_account_authority().size()
    assert result["contracts"] == "1"
    assert result["sizingPolicyMode"] == "SMALL_ACCOUNT_MINIMUM_CONTRACT"
    assert result["smallAccountExceptionApplied"] is True


def test_two_contract_special_path_rejects():
    with pytest.raises(SizingRejected):
        small_account_authority().validate(
            2, sizing_policy_mode="SMALL_ACCOUNT_MINIMUM_CONTRACT"
        )


def test_normal_mm_off_behaviour_unchanged():
    with pytest.raises(SizingRejected, match="NO_VALID_QUANTITY_FOR_RISK_POLICY"):
        small_account_authority(small_account_mode=False).size()


def test_manual_only_is_preserved():
    with pytest.raises(SizingRejected, match="REQUIRES_MANUAL"):
        small_account_authority(entry_authority="BOT").size()


def test_auto_and_loop_are_rejected():
    with pytest.raises(SizingRejected, match="LOOP_BLOCKED"):
        small_account_authority(loop_enabled=True).size()


def test_explicit_leverage_three_is_preserved():
    result = small_account_authority(leverage="3").size()
    assert result["contracts"] == "1"
    with pytest.raises(SizingRejected, match="LEVERAGE_UNKNOWN"):
        small_account_authority(leverage_explicit=False).size()


def test_approved_risk_and_absolute_caps_are_preserved():
    with pytest.raises(SizingRejected, match="RISK_PERCENT_EXCEEDED"):
        small_account_authority(small_account_max_risk_percent="1").size()
    with pytest.raises(SizingRejected, match="ABSOLUTE_RISK_EXCEEDED"):
        small_account_authority(
            small_account_max_absolute_risk_usdt="0.1"
        ).size()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
