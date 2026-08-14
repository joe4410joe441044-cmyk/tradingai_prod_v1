from datetime import datetime, timedelta, timezone

import pytest

from backend.auto_market_selection import ExistingKucoinLiveAccountAuthority
from tests.test_ams_6b_r2_r1_live_account_hardening import Exchange, POLICY, authority


NOW = datetime(2026, 8, 9, 6, tzinfo=timezone.utc)


@pytest.mark.parametrize("positions", [
    None, {}, [], {"qty": None}, {"qty": True}, {"qty": "NaN"},
    {"qty": "Infinity"}, {"unexpected": 0},
])
def test_malformed_position_is_unknown_and_entry_is_blocked(positions):
    adapter = authority(Exchange(positions=positions))
    snapshot = adapter.read()
    contract = adapter.build_capital_eligibility(snapshot, policy=POLICY)
    assert snapshot.open_position_state == "UNKNOWN"
    assert "LIVE_POSITION_MALFORMED" in snapshot.reason_codes
    assert not contract.execution_entry_allowed


def test_signed_nonzero_position_is_open_and_entry_is_blocked():
    adapter = authority(Exchange(positions={"qty": "-2"}))
    snapshot = adapter.read()
    contract = adapter.build_capital_eligibility(snapshot, policy=POLICY)
    assert snapshot.open_position_state == "OPEN"
    assert "LIVE_POSITION_OPEN" in snapshot.reason_codes
    assert not contract.execution_entry_allowed


@pytest.mark.parametrize("orders", [
    None, {}, {"success": True, "orders": []},
    {"success": True, "count": "0", "orders": []},
    {"success": True, "count": -1, "orders": []},
    {"success": True, "count": 0, "orders": {}},
])
def test_malformed_pending_is_unknown_and_entry_is_blocked(orders):
    adapter = authority(Exchange(orders=orders))
    snapshot = adapter.read()
    contract = adapter.build_capital_eligibility(snapshot, policy=POLICY)
    assert snapshot.pending_order_state == "UNKNOWN"
    assert "LIVE_PENDING_ORDER_MALFORMED" in snapshot.reason_codes
    assert not contract.execution_entry_allowed


@pytest.mark.parametrize("error,code", [
    (PermissionError("401 key=KEY secret=SECRET"), "AUTHENTICATION_FAILED"),
    (TimeoutError("passphrase=PHRASE"), "REQUEST_TIMEOUT"),
    (RuntimeError("HTTP 503 credential=TOKEN"), "HTTP_ERROR"),
    (ValueError("malformed JSON secret=SECRET"), "LIVE_ACCOUNT_UNAVAILABLE"),
])
def test_failure_classification_is_stable_redacted_and_closed(error, code):
    adapter = authority(Exchange(orders=error))
    snapshot = adapter.read()
    assert code in snapshot.reason_codes
    assert snapshot.pending_order_state == "UNKNOWN"
    assert not snapshot.ready
    serialized = str(snapshot.to_dict())
    assert all(secret not in serialized for secret in ("KEY", "SECRET", "PHRASE", "TOKEN"))


@pytest.mark.parametrize("offset,reason", [
    (timedelta(seconds=1), "LIVE_ACCOUNT_STALE"),
    (-timedelta(minutes=1), "LIVE_ACCOUNT_STALE"),
])
def test_future_or_stale_account_timestamp_fails_closed(offset, reason):
    account = {
        "source": "KUCOIN_FUTURES_READ_ONLY", "equity": "1000",
        "availableBalance": "800", "lastSync": (NOW + offset).timestamp(),
    }
    snapshot = authority(Exchange(account=account)).read()
    assert reason in snapshot.reason_codes
    assert not snapshot.authority_fresh


def test_position_pending_staleness_and_cross_snapshot_mismatch_fail_closed():
    old = (NOW - timedelta(seconds=31)).timestamp()
    adapter = authority(Exchange(
        positions={"qty": 0, "timestamp": old},
        orders={"success": True, "count": 0, "orders": [], "timestamp": old},
    ))
    snapshot = adapter.read()
    contract = adapter.build_capital_eligibility(snapshot, policy=POLICY)
    assert "LIVE_POSITION_STALE" in snapshot.reason_codes
    assert "LIVE_PENDING_ORDER_STALE" in snapshot.reason_codes
    assert "LIVE_SNAPSHOT_MISMATCH" in snapshot.reason_codes
    assert not snapshot.snapshot_consistent
    assert not contract.execution_entry_allowed


def test_valid_flat_none_preserves_mm_ownership_and_live_input_identity():
    adapter = authority()
    snapshot = adapter.read()
    contract = adapter.build_capital_eligibility(snapshot, policy=POLICY)
    assert snapshot.open_position_state == "FLAT"
    assert snapshot.pending_order_state == "NONE"
    assert snapshot.to_dict()["authorityEvaluatedAt"]
    assert snapshot.source_authority == "REAL_LIVE_ACCOUNT"
    assert contract.capital_authority == "MONEY_MANAGEMENT"
    assert contract.input_authority == "REAL_LIVE_ACCOUNT"
    assert contract.execution_entry_allowed


def test_explicit_kucoin_position_authority_shape_can_confirm_flat():
    class ExplicitAuthorityExchange(Exchange):
        def get_positions(self):
            raise AssertionError("legacy ambiguous position path used")

        def get_position_authority_snapshot(self):
            self.calls.append("GET positions authority")
            return {"qty": 0, "evaluatedAt": NOW.timestamp()}

    snapshot = authority(ExplicitAuthorityExchange()).read()
    assert snapshot.open_position_state == "FLAT"
    assert snapshot.position_evaluated_at == NOW
    assert snapshot.position_fresh
