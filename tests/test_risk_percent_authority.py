"""WORK AA: canonical MM risk-percent authority."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.bot_manager.bot_manager import BotManager
from backend.money_management.risk_percent_authority import (
    RiskPercentAuthorityError,
    resolve_executability_risk_percent,
    resolve_risk_percent_authority,
    status_risk_percent_authority,
)


def test_resolve_risk_rejects_payload_mismatch():
    mm = SimpleNamespace(risk_per_trade_pct=Decimal("1"))
    with pytest.raises(RiskPercentAuthorityError, match="MISMATCH"):
        resolve_risk_percent_authority({"risk_percent": 0.5}, mm)


def test_resolve_risk_accepts_matching_payload():
    mm = SimpleNamespace(risk_per_trade_pct=Decimal("1"))
    assert resolve_risk_percent_authority({"risk_percent": 1}, mm) == 1.0


def test_resolve_risk_unavailable_without_mm():
    with pytest.raises(RiskPercentAuthorityError, match="UNAVAILABLE"):
        resolve_risk_percent_authority({"risk_percent": 1}, None)


def test_executability_prefers_mm_over_legacy_default():
    mm = SimpleNamespace(risk_per_trade_pct=Decimal("1"))
    value = resolve_executability_risk_percent(
        config={"mode": "paper"},
        mm_config=mm,
        live_runtime=False,
    )
    assert value == Decimal("1")


def test_executability_legacy_default_only_without_mm():
    value = resolve_executability_risk_percent(
        config={"mode": "paper"},
        mm_config=None,
        live_runtime=False,
    )
    assert value == Decimal("0.5")


def test_executability_live_fails_closed_without_mm_or_config():
    with pytest.raises(RuntimeError, match="UNAVAILABLE"):
        resolve_executability_risk_percent(
            config={"mode": "live"},
            mm_config=None,
            live_runtime=True,
        )


def test_status_stopped_prefers_mm():
    mm = SimpleNamespace(risk_per_trade_pct=Decimal("1"))
    result = status_risk_percent_authority(
        engine_risk_percent=0.5,
        mm_config=mm,
        running=False,
    )
    assert result == {"value": 1.0, "source": "MONEY_MANAGEMENT"}


def test_status_running_prefers_engine():
    mm = SimpleNamespace(risk_per_trade_pct=Decimal("1"))
    result = status_risk_percent_authority(
        engine_risk_percent=0.5,
        mm_config=mm,
        running=True,
    )
    assert result == {"value": 0.5, "source": "RUNTIME_ENGINE"}


def manager_with(config, mm=None):
    manager = BotManager.__new__(BotManager)
    manager.config = config
    manager.money_management_config_provider = (lambda: mm) if mm is not None else None
    manager._running = False
    return manager


def test_bot_manager_executability_uses_mm_when_available():
    mm = SimpleNamespace(risk_per_trade_pct=Decimal("1"))
    settings = manager_with({"mode": "paper"}, mm)._production_ams_executability_settings()
    assert settings["risk_percent"] == Decimal("1")


def test_bot_manager_status_helper_stopped_uses_mm():
    mm = SimpleNamespace(risk_per_trade_pct=Decimal("1"))
    manager = manager_with({"mode": "live", "risk_percent": 0.5}, mm)
    result = manager._status_risk_percent_authority(0.5)
    assert result["source"] == "MONEY_MANAGEMENT"
    assert result["value"] == 1.0
