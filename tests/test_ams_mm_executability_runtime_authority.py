from decimal import Decimal

import pytest

from backend.bot_manager.bot_manager import BotManager
from backend.money_management.capital_eligibility import (
    evaluate_market_capital_eligibility,
)
from tests.test_ams_0d_foundation import NOW, capital, client_for, contract_payload


def manager_with(config):
    manager = BotManager.__new__(BotManager)
    manager.config = config
    return manager


def test_live_runtime_uses_canonical_risk_sl_and_leverage():
    settings = manager_with({
        "mode": "live",
        "liveRuntimeStartAllowed": True,
        "risk_percent": 0.10,
        "sl_percent": 0.50,
        "effective_leverage": 1,
    })._production_ams_executability_settings()

    assert settings == {
        "risk_percent": Decimal("0.1"),
        "stop_loss_percent": Decimal("0.5"),
        "effective_leverage": Decimal("1"),
    }
    assert settings["risk_percent"] != Decimal("0.5")
    assert settings["stop_loss_percent"] != Decimal("1")


def test_changed_runtime_settings_replace_defaults_without_mutation():
    config = {
        "mode": "live",
        "liveRuntimeStartAllowed": True,
        "risk_percent": "0.50",
        "sl_percent": "2.00",
        "effective_leverage": "3",
    }
    original = dict(config)
    settings = manager_with(config)._production_ams_executability_settings()

    assert settings == {
        "risk_percent": Decimal("0.50"),
        "stop_loss_percent": Decimal("2.00"),
        "effective_leverage": Decimal("3"),
    }
    assert config == original


@pytest.mark.parametrize("missing", [
    "risk_percent", "sl_percent", "effective_leverage",
])
def test_live_runtime_missing_authority_fails_closed(missing):
    config = {
        "mode": "live",
        "liveRuntimeStartAllowed": True,
        "risk_percent": "0.10",
        "sl_percent": "0.50",
        "effective_leverage": "1",
    }
    config.pop(missing)
    with pytest.raises(RuntimeError, match="AUTO_EXECUTABILITY"):
        manager_with(config)._production_ams_executability_settings()


@pytest.mark.parametrize("field,value", [
    ("risk_percent", 0),
    ("sl_percent", "not-a-number"),
    ("effective_leverage", -1),
])
def test_live_runtime_invalid_authority_fails_closed(field, value):
    config = {
        "mode": "live",
        "liveRuntimeStartAllowed": True,
        "risk_percent": "0.10",
        "sl_percent": "0.50",
        "effective_leverage": "1",
    }
    config[field] = value
    with pytest.raises(RuntimeError, match="AUTO_EXECUTABILITY"):
        manager_with(config)._production_ams_executability_settings()


def test_legacy_initialization_may_use_safe_defaults():
    assert manager_with({"mode": "paper"})._production_ams_executability_settings() == {
        "risk_percent": Decimal("0.5"),
        "stop_loss_percent": Decimal("1"),
        "effective_leverage": Decimal("1"),
    }


def test_runtime_risk_and_sl_change_executability_through_existing_mm_sizing():
    metadata = client_for({
        "code": "200000",
        "data": [contract_payload(
            symbol="TESTUSDTM",
            baseCurrency="TEST",
            multiplier="1",
            lotSize=10,
            lastTradePrice="1",
        )],
    }).get_active_contracts(evaluated_at=NOW)[0]
    authority = capital(
        available_capital=Decimal("100"),
        capital_basis=Decimal("100"),
        risk_budget=Decimal("10"),
        max_position_notional=Decimal("100"),
        total_exposure_percent=Decimal("100"),
    )

    conservative = evaluate_market_capital_eligibility(
        metadata,
        authority,
        risk_percent=Decimal("0.10"),
        stop_loss_percent=Decimal("2.00"),
        effective_cost_percent=Decimal("0.2"),
        effective_leverage=Decimal("1"),
        evaluated_at=NOW,
    )
    permissive = evaluate_market_capital_eligibility(
        metadata,
        authority,
        risk_percent=Decimal("0.50"),
        stop_loss_percent=Decimal("0.50"),
        effective_cost_percent=Decimal("0.2"),
        effective_leverage=Decimal("3"),
        evaluated_at=NOW,
    )

    assert conservative.position_feasible is False
    assert "MINIMUM_ORDER_NOT_FEASIBLE" in conservative.reason_codes
    assert permissive.position_feasible is True
    assert permissive.approved_quantity_preview >= metadata.minimum_quantity
    assert permissive.to_dict()["effectiveLeverage"] == "3"
    assert conservative.to_dict()["orderCreated"] is False
    assert permissive.to_dict()["orderCreated"] is False


def test_invalid_leverage_authority_blocks_candidate_without_roundup():
    metadata = client_for({
        "code": "200000", "data": [contract_payload()],
    }).get_active_contracts(evaluated_at=NOW)[0]
    result = evaluate_market_capital_eligibility(
        metadata,
        capital(),
        risk_percent=Decimal("0.5"),
        stop_loss_percent=Decimal("1"),
        effective_cost_percent=Decimal("0.2"),
        effective_leverage=Decimal("0"),
        evaluated_at=NOW,
    )

    assert result.eligible is False
    assert result.approved_quantity_preview is None
    assert result.reason_codes == ("LEVERAGE_AUTHORITY_INVALID",)
