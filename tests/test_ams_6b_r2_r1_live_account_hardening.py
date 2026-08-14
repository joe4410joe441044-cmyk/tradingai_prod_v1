from datetime import datetime, timedelta, timezone

import pytest

from backend.auto_market_selection import ExistingKucoinLiveAccountAuthority
from tests.test_ams_5b_live_read_only import SAFETY


NOW = datetime(2026, 8, 9, 6, tzinfo=timezone.utc)
UNSET = object()


class Exchange:
    def __init__(self, *, account=UNSET, positions=UNSET, orders=UNSET):
        self.account = account if account is not UNSET else {
            "source": "KUCOIN_FUTURES_READ_ONLY",
            "equity": "1000",
            "availableBalance": "800",
            "lastSync": NOW.timestamp(),
        }
        self.positions = (
            {"symbol": "XBTUSDTM", "qty": 0}
            if positions is UNSET else positions
        )
        self.orders = orders if orders is not UNSET else {
            "success": True, "count": 0, "orders": [],
            "timestamp": NOW.timestamp(),
        }
        self.calls = []

    def get_account_overview(self):
        self.calls.append("GET account")
        return self._result(self.account)

    def get_positions(self):
        self.calls.append("GET positions")
        return self._result(self.positions)

    def get_open_orders(self):
        self.calls.append("GET orders")
        return self._result(self.orders)

    @staticmethod
    def _result(value):
        if isinstance(value, BaseException):
            raise value
        return value

    def create_order(self):
        raise AssertionError("mutation called")

    def cancel_order(self):
        raise AssertionError("mutation called")


def authority(exchange=None, **changes):
    values = {
        "safety_provider": lambda: SAFETY,
        "clock": lambda: NOW,
        "exposure_provider": lambda positions, account: {
            "currentExposure": "0", "remainingExposure": "200",
        },
    }
    values.update(changes)
    return ExistingKucoinLiveAccountAuthority(exchange or Exchange(), **values)


POLICY = {
    "riskBudget": "4", "maxPositionNotional": "100",
    "totalExposurePercent": "20", "positionCount": 0,
    "pendingOrderCount": 0, "mmRegime": "NORMAL",
    "policyVersion": "live-mm/v1",
}


@pytest.mark.parametrize("positions,state", [
    ({"symbol": "XBTUSDTM", "qty": 0}, "FLAT"),
    ({"symbol": "XBTUSDTM", "qty": 1}, "OPEN"),
    ([{"symbol": "A", "qty": 0}, {"symbol": "B", "qty": 2}], "OPEN"),
])
def test_valid_position_states(positions, state):
    snapshot = authority(Exchange(positions=positions)).read()
    assert snapshot.open_position_state == state
    assert ("LIVE_POSITION_OPEN" in snapshot.reason_codes) is (state == "OPEN")


@pytest.mark.parametrize("positions", [
    None, "", [], {}, "0", {"qty": "NaN"}, {"qty": "Infinity"},
    [{"qty": 0}, {}],
])
def test_malformed_position_is_unknown_not_flat(positions):
    snapshot = authority(Exchange(positions=positions)).read()
    assert snapshot.open_position_state == "UNKNOWN"
    assert "LIVE_POSITION_UNKNOWN" in snapshot.reason_codes
    assert not snapshot.authority_fresh and not snapshot.ready


def test_position_api_failure_is_unknown_and_error_is_redacted():
    snapshot = authority(Exchange(
        positions=PermissionError("401 key=KEY secret=SECRET passphrase=PHRASE")
    )).read()
    serialized = str(snapshot.to_dict())
    assert snapshot.open_position_state == "UNKNOWN"
    assert all(value not in serialized for value in ("KEY", "SECRET", "PHRASE"))


@pytest.mark.parametrize("count,orders,state", [
    (0, [], "NONE"),
    (1, [{}], "EXISTS"),
])
def test_valid_pending_order_states(count, orders, state):
    response = {"success": True, "count": count, "orders": orders}
    snapshot = authority(Exchange(orders=response)).read()
    assert snapshot.pending_order_state == state
    assert ("LIVE_PENDING_ORDER_EXISTS" in snapshot.reason_codes) is (state == "EXISTS")


@pytest.mark.parametrize("orders", [
    {"success": True, "orders": []},
    {"success": True, "count": None, "orders": []},
    {"success": True, "count": "0", "orders": []},
    {"success": True, "count": -1, "orders": []},
    {"success": True, "count": 0, "orders": {}},
    {"success": True, "count": 1, "orders": []},
    None,
])
def test_malformed_orders_are_unknown_not_none(orders):
    snapshot = authority(Exchange(orders=orders)).read()
    assert snapshot.pending_order_state == "UNKNOWN"
    assert "LIVE_PENDING_ORDER_UNKNOWN" in snapshot.reason_codes
    assert not snapshot.authority_fresh and not snapshot.ready


@pytest.mark.parametrize("failure", [
    PermissionError("401 authentication failure"),
    TimeoutError("private read timeout"),
    RuntimeError("HTTP 503"),
    ValueError("malformed JSON"),
])
def test_private_failure_classes_fail_closed(failure):
    snapshot = authority(Exchange(orders=failure)).read()
    assert snapshot.pending_order_state == "UNKNOWN"
    assert not snapshot.ready


@pytest.mark.parametrize("changes", [
    {"positions": {"symbol": "XBTUSDTM", "qty": 1}},
    {"positions": None},
    {"orders": {"success": True, "count": 1, "orders": [{}]}},
    {"orders": {"success": True, "orders": []}},
])
def test_unsafe_position_or_orders_make_mm_contract_non_executable(changes):
    adapter = authority(Exchange(**changes))
    contract = adapter.build_capital_eligibility(adapter.read(), policy=POLICY)
    assert not contract.execution_entry_allowed
    assert contract.remaining_position_capacity is None


def test_stale_and_incomplete_account_make_mm_contract_non_executable():
    for account in (
        {"source": "KUCOIN_FUTURES_READ_ONLY", "equity": 1000,
         "availableBalance": 800, "lastSync": (NOW - timedelta(minutes=2)).timestamp()},
        {"source": "KUCOIN_FUTURES_READ_ONLY", "lastSync": NOW.timestamp()},
    ):
        adapter = authority(Exchange(account=account))
        snapshot = adapter.read()
        contract = adapter.build_capital_eligibility(snapshot, policy=POLICY)
        assert not contract.execution_entry_allowed
        assert contract.remaining_position_capacity is None


def test_timestamps_freshness_and_live_provenance_are_explicit():
    adapter = authority()
    snapshot = adapter.read()
    contract = adapter.build_capital_eligibility(snapshot, policy=POLICY)
    assert snapshot.account_evaluated_at == NOW
    assert snapshot.position_evaluated_at == NOW
    assert snapshot.pending_orders_evaluated_at == NOW
    assert snapshot.account_fresh and snapshot.position_fresh
    assert snapshot.pending_orders_fresh and snapshot.authority_fresh
    assert snapshot.snapshot_consistent and snapshot.snapshot_skew == timedelta(0)
    assert contract.execution_entry_allowed
    assert contract.remaining_position_capacity == 1
    assert contract.capital_authority == "MONEY_MANAGEMENT"
    assert contract.capital_source == "LIVE_ACCOUNT"


def test_configured_snapshot_skew_fails_closed_without_guessing_threshold():
    orders = {
        "success": True, "count": 0, "orders": [],
        "timestamp": (NOW - timedelta(seconds=5)).timestamp(),
    }
    adapter = authority(
        Exchange(orders=orders), maximum_snapshot_skew=timedelta(seconds=1)
    )
    snapshot = adapter.read()
    contract = adapter.build_capital_eligibility(snapshot, policy=POLICY)
    assert snapshot.snapshot_skew == timedelta(seconds=5)
    assert not snapshot.snapshot_consistent
    assert "LIVE_ACCOUNT_SNAPSHOT_INCONSISTENT" in snapshot.reason_codes
    assert not snapshot.authority_fresh
    assert not contract.execution_entry_allowed
    assert contract.remaining_position_capacity is None


def test_read_only_surface_has_no_live_action():
    exchange = Exchange()
    snapshot = authority(exchange).read()
    assert snapshot.ready
    assert exchange.calls == ["GET account", "GET positions", "GET orders"]
