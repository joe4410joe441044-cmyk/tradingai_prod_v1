from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.auto_market_selection import ExistingKucoinLiveAccountAuthority
from backend.money_management.capital_eligibility import CapitalEligibilityContract
from tests.test_ams_5b_live_read_only import SAFETY


NOW = datetime(2026, 8, 9, 5, tzinfo=timezone.utc)


class Exchange:
    def __init__(self, *, overview=None, positions=None, orders=None):
        self.overview = overview or {
            "source": "KUCOIN_FUTURES_READ_ONLY", "equity": "1000",
            "availableBalance": "800", "lastSync": NOW.timestamp(),
        }
        self.positions = {"symbol": "XBTUSDTM", "qty": 0} if positions is None else positions
        self.orders = orders or {"success": True, "count": 0, "orders": []}
        self.calls = []

    def get_account_overview(self): self.calls.append("GET account"); return self.overview
    def get_positions(self): self.calls.append("GET positions"); return self.positions
    def get_open_orders(self): self.calls.append("GET orders"); return self.orders
    def create_order(self): raise AssertionError("private mutation called")
    def cancel_order(self): raise AssertionError("private mutation called")


def authority(exchange, **changes):
    values = dict(
        safety_provider=lambda: SAFETY, clock=lambda: NOW,
        exposure_provider=lambda positions, account: {
            "currentExposure": "0", "remainingExposure": "200",
        },
    )
    values.update(changes)
    return ExistingKucoinLiveAccountAuthority(exchange, **values)


def test_existing_get_authority_reads_equity_available_position_orders_and_exposure():
    exchange = Exchange()
    snapshot = authority(exchange).read()
    assert snapshot.capital_authority == "REAL_LIVE_ACCOUNT"
    assert snapshot.equity == Decimal("1000") and snapshot.available_capital == Decimal("800")
    assert snapshot.open_position_state == "FLAT" and snapshot.pending_order_state == "NONE"
    assert snapshot.current_exposure == 0 and snapshot.remaining_exposure == 200
    assert snapshot.authority_fresh and snapshot.ready
    assert exchange.calls == ["GET account", "GET positions", "GET orders"]


def test_open_and_pending_states_are_authoritative():
    snapshot = authority(Exchange(
        positions={"symbol": "XBTUSDTM", "qty": 1},
        orders={"success": True, "count": 1, "orders": [{}]},
    )).read()
    assert snapshot.open_position_state == "OPEN"
    assert snapshot.pending_order_state == "EXISTS"


@pytest.mark.parametrize("method,reason,state", [
    ("get_positions", "LIVE_POSITION_AUTHORITY_UNKNOWN", "UNKNOWN"),
    ("get_open_orders", "LIVE_PENDING_ORDER_AUTHORITY_UNKNOWN", "UNKNOWN"),
])
def test_unknown_is_never_coerced_to_flat_or_none(method, reason, state):
    exchange = Exchange()
    setattr(exchange, method, lambda: (_ for _ in ()).throw(RuntimeError("secret detail")))
    snapshot = authority(exchange).read()
    assert reason in snapshot.reason_codes
    if method == "get_positions": assert snapshot.open_position_state == state
    else: assert snapshot.pending_order_state == state
    assert "secret detail" not in str(snapshot.to_dict())


def test_stale_or_missing_exposure_fails_closed():
    old = {"source": "KUCOIN_FUTURES_READ_ONLY", "equity": 1000,
           "availableBalance": 800, "lastSync": (NOW-timedelta(minutes=2)).timestamp()}
    snapshot = authority(Exchange(overview=old), exposure_provider=None).read()
    assert not snapshot.ready
    assert "LIVE_MM_AUTHORITY_NOT_READY" in snapshot.reason_codes
    assert "LIVE_EXPOSURE_AUTHORITY_UNAVAILABLE" in snapshot.reason_codes


def test_capital_contract_reuses_mm_builder_without_order_surface():
    adapter = authority(Exchange())
    snapshot = adapter.read()
    contract = adapter.build_capital_eligibility(snapshot, policy={
        "riskBudget": "4", "maxPositionNotional": "100",
        "totalExposurePercent": "20", "positionCount": 0,
        "pendingOrderCount": 0, "mmRegime": "NORMAL", "policyVersion": "live-mm/v1",
    })
    assert isinstance(contract, CapitalEligibilityContract)
    assert contract.capital_authority == "MONEY_MANAGEMENT"
    assert contract.equity == snapshot.equity


def test_unsafe_preflight_aborts_before_any_private_get():
    exchange = Exchange()
    adapter = authority(exchange, safety_provider=lambda: {**SAFETY, "dryRun": False})
    with pytest.raises(RuntimeError, match="LIVE_ACCOUNT_READ_PREFLIGHT_BLOCKED"):
        adapter.read()
    assert exchange.calls == []
