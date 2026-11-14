from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.accounts.models import AccountId
from backend.execution.hyro_mcp_mock import (
    DummyTokenMockTransport, MOCK_HYRO_TOOL_PROFILE, MockHyroMcpServer,
)
from backend.execution.hyro_mcp_read_adapter import (
    HyroMcpAccountScope, HyroMcpReadAdapter,
)
from backend.execution.read_only_observations import ReadDataQuality, ReadErrorCode

NOW = datetime(2026, 11, 14, 3, 0, tzinfo=timezone.utc)
STAMP = "2026-11-14T03:00:00Z"
ACCOUNT = AccountId("acc_20000000000040008000000000000002")
SCOPE = HyroMcpAccountScope(ACCOUNT, "hyro-challenge-ref-001")
TOOLS = MOCK_HYRO_TOOL_PROFILE

def envelope(**extra):
    return {"account_ref": SCOPE.external_account_ref, "platform": SCOPE.platform,
            "observed_at": STAMP, **extra}

def base_responses():
    return {
        (TOOLS.account_identity, None): envelope(stage="ONE_STEP"),
        (TOOLS.account_summary, None): envelope(currency="USDT", balance="100000.00000001",
            equity="99991.123456789", available_balance="90000.1",
            open_position_count=1, open_order_count=0),
        (TOOLS.positions, None): envelope(items=[{"symbol": "BTCUSDT", "side": "BUY",
            "size": "0.001", "avg_price": "60000.01", "mark_price": "60001.02",
            "unrealised_pnl": "0.00101", "position_value": "60.00102", "leverage": "1"}],
            page_complete=True),
        (TOOLS.open_orders, None): envelope(items=[], page_complete=True),
        (TOOLS.conditional_orders, None): envelope(items=[{"order_id": "cond-1", "symbol": "BTCUSDT",
            "side": "SELL", "order_type": "STOP", "price": "59000", "qty": "0.001",
            "leaves_qty": "0.001", "cum_exec_qty": "0", "reduce_only": True,
            "position_idx": 0}], page_complete=True),
    }

def adapter(responses=None, token="dummy-token-not-a-secret"):
    server = MockHyroMcpServer.with_responses(responses or base_responses())
    return HyroMcpReadAdapter(DummyTokenMockTransport(server, token), tools=TOOLS), server

def test_normalizes_all_five_reads_and_only_complete_empty_is_zero():
    subject, server = adapter()
    result = subject.read(SCOPE, now=NOW)
    assert result.overall_quality is ReadDataQuality.COMPLETE
    assert result.summary.value.balance == Decimal("100000.00000001")
    assert result.summary.value.equity == Decimal("99991.123456789")
    assert result.positions.value[0].size == Decimal("0.001")
    assert result.open_orders.confirmed_empty is True
    assert result.conditional_orders.confirmed_empty is False
    assert len(result.conditional_orders.value) == 1
    assert {name for name, _ in server.calls} == subject.allowed_tool_names
    assert "mock.hyro.submit_order" not in {name for name, _ in server.calls}

def test_account_mismatch_rejects_before_other_reads():
    responses = base_responses(); responses[(TOOLS.account_identity, None)] = envelope(account_ref="other")
    subject, server = adapter(responses)
    result = subject.read(SCOPE, now=NOW)
    assert result.identity.failure.code is ReadErrorCode.INVALID_BINDING
    assert result.summary.failure.code is ReadErrorCode.INVALID_BINDING
    assert len(server.calls) == 1

def test_stale_source_is_not_promoted_to_complete():
    responses = base_responses()
    for key, value in list(responses.items()): responses[key] = {**value, "observed_at": "2026-11-14T02:00:00Z"}
    result = adapter(responses)[0].read(SCOPE, now=NOW)
    assert result.overall_quality is ReadDataQuality.STALE
    assert result.summary.failure.code is ReadErrorCode.STALE_DATA

def test_mid_pagination_failure_is_partial_not_empty_success():
    responses = base_responses()
    responses[(TOOLS.open_orders, None)] = envelope(items=[{"order_id": "open-1", "symbol": "ETHUSDT",
        "side": "BUY", "order_type": "LIMIT", "status": "New", "price": "3000", "qty": "1"}],
        page_complete=False, next_cursor="page-2")
    subject, _ = adapter(responses)
    result = subject.read(SCOPE, now=NOW)
    assert result.open_orders.quality is ReadDataQuality.PARTIAL
    assert result.open_orders.failure.code is ReadErrorCode.PAGINATION_INCOMPLETE
    assert len(result.open_orders.value) == 1
    assert result.open_orders.confirmed_empty is False

def test_unadvertised_conditional_read_is_unsupported_not_zero():
    subject, server = adapter(); server.advertised_tools.remove(TOOLS.conditional_orders)
    result = subject.read(SCOPE, now=NOW)
    assert result.conditional_orders.quality is ReadDataQuality.FAILED
    assert result.conditional_orders.failure.code is ReadErrorCode.UNSUPPORTED_CAPABILITY
    assert result.conditional_orders.confirmed_empty is False

def test_write_tool_is_rejected_even_when_server_advertises_it():
    subject, server = adapter()
    assert "mock.hyro.submit_order" in server.list_tools()
    with pytest.raises(PermissionError, match="READ_ALLOWLIST"):
        subject.invoke_tool("mock.hyro.submit_order", {"symbol": "BTCUSDT"})
    assert server.calls == []

def test_dummy_credential_is_masked_from_repr_and_failure():
    token = "force-failure-dummy-token"
    subject, _ = adapter(token=token)
    assert token not in repr(subject.transport)
    result = subject.read(SCOPE, now=NOW)
    assert result.identity.failure.code is ReadErrorCode.TRANSPORT_FAILURE
    assert token not in result.identity.failure.safe_message

def test_account_switch_old_response_is_rejected_by_scope():
    responses = base_responses()
    subject, _ = adapter(responses)
    switched = HyroMcpAccountScope(AccountId("acc_30000000000040008000000000000003"), "new-account")
    result = subject.read(switched, now=NOW)
    assert result.identity.quality is ReadDataQuality.FAILED
    assert result.identity.failure.code is ReadErrorCode.INVALID_BINDING

def test_missing_balance_remains_partial_and_rules_cannot_treat_it_as_complete():
    responses = base_responses(); responses[(TOOLS.account_summary, None)] = envelope(
        currency="USDT", balance=None, equity="99991", available_balance="90000",
        open_position_count=0, open_order_count=0)
    result = adapter(responses)[0].read(SCOPE, now=NOW)
    assert result.summary.quality is ReadDataQuality.PARTIAL
    assert result.summary.value.balance is None
    assert "balance" in result.summary.value.missing_fields
