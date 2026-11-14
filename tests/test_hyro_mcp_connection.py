from datetime import datetime, timezone

from backend.accounts.models import AccountId
from backend.execution.hyro_mcp_connection import (
    HyroMcpConnectionBoundary,
    HyroMcpConnectionConfig,
    HyroMcpConnectionStatus,
)
from backend.execution.hyro_mcp_mock import (
    DummyTokenMockTransport,
    MOCK_HYRO_TOOL_PROFILE,
    MockHyroMcpServer,
)
from backend.execution.hyro_mcp_read_adapter import HyroMcpAccountScope
from backend.execution.read_only_observations import ReadDataQuality, ReadErrorCode

NOW = datetime(2026, 11, 14, 4, 0, tzinfo=timezone.utc)
STAMP = "2026-11-14T04:00:00Z"
DUMMY_TOKEN = "fixture-dummy-token-do-not-use"
SCOPE = HyroMcpAccountScope(
    AccountId("acc_20000000000040008000000000000002"),
    "fixture-account-ref",
)
TOOLS = MOCK_HYRO_TOOL_PROFILE


def envelope(**extra):
    return {
        "account_ref": SCOPE.external_account_ref,
        "platform": SCOPE.platform,
        "observed_at": STAMP,
        **extra,
    }


def responses():
    return {
        (TOOLS.account_identity, None): envelope(),
        (TOOLS.account_summary, None): envelope(
            currency="USDT", balance="100000", equity="100000",
            available_balance="100000", open_position_count=0, open_order_count=0,
        ),
        (TOOLS.positions, None): envelope(items=[], page_complete=True),
        (TOOLS.open_orders, None): envelope(items=[], page_complete=True),
        (TOOLS.conditional_orders, None): envelope(items=[{
            "order_id": "fixture-condition-1", "symbol": "BTCUSDT", "side": "SELL",
            "order_type": "STOP", "price": "59000", "qty": "0.001",
        }], page_complete=True),
    }


def ready_config(**overrides):
    values = {
        "server_url": "https://fixture.invalid/mcp",
        "transport": "MOCK_IN_PROCESS",
        "auth_scheme": "DUMMY_TOKEN_REFERENCE",
        "credential_reference": "fixture-secret-reference",
        "response_schema_id": "fixture.hyro.mock-response.v1",
        "read_access_enabled": True,
        "trading_access_enabled": False,
    }
    values.update(overrides)
    return HyroMcpConnectionConfig.from_mapping(values, account_scope=SCOPE, tools=TOOLS)


class FactorySpy:
    def __init__(self, server=None):
        self.server = server or MockHyroMcpServer.with_responses(responses())
        self.calls = []

    def __call__(self, config):
        self.calls.append(config.credential_reference)
        return DummyTokenMockTransport(self.server, DUMMY_TOKEN)


def test_missing_required_config_blocks_before_transport_construction():
    factory = FactorySpy()
    config = ready_config(server_url=None, auth_scheme=None, response_schema_id=None)
    result = HyroMcpConnectionBoundary(factory).read(config, now=NOW)
    assert result.validation.status is HyroMcpConnectionStatus.BLOCKED_MISSING
    assert result.validation.missing_fields == ("server_url", "auth_scheme", "response_schema_id")
    assert result.observation is None
    assert factory.calls == []


def test_unsafe_or_write_enabled_config_blocks_before_transport_construction():
    factory = FactorySpy()
    result = HyroMcpConnectionBoundary(factory).read(
        ready_config(server_url="http://fixture.invalid/mcp", trading_access_enabled=True),
        now=NOW,
    )
    assert result.validation.status is HyroMcpConnectionStatus.BLOCKED_UNSAFE
    assert set(result.validation.unsafe_fields) == {"server_url", "trading_access_enabled"}
    assert factory.calls == []


def test_ready_config_reads_separate_order_types_and_never_calls_advertised_write_tool():
    factory = FactorySpy()
    result = HyroMcpConnectionBoundary(factory).read(ready_config(), now=NOW)
    assert result.validation.status is HyroMcpConnectionStatus.READY
    assert result.observation.overall_quality is ReadDataQuality.COMPLETE
    assert result.observation.open_orders.confirmed_empty is True
    assert result.observation.conditional_orders.confirmed_empty is False
    assert len(result.observation.conditional_orders.value) == 1
    assert len(factory.calls) == 1
    assert "mock.hyro.submit_order" not in {name for name, _ in factory.server.calls}


def test_account_mismatch_rejects_before_remaining_reads():
    bad = responses()
    bad[(TOOLS.account_identity, None)] = envelope(account_ref="other-account")
    factory = FactorySpy(MockHyroMcpServer.with_responses(bad))
    result = HyroMcpConnectionBoundary(factory).read(ready_config(), now=NOW)
    assert result.observation.identity.failure.code is ReadErrorCode.INVALID_BINDING
    assert len(factory.server.calls) == 1


def test_missing_conditional_tool_is_unknown_not_confirmed_zero():
    server = MockHyroMcpServer.with_responses(responses())
    server.advertised_tools.remove(TOOLS.conditional_orders)
    result = HyroMcpConnectionBoundary(FactorySpy(server)).read(ready_config(), now=NOW)
    assert result.observation.conditional_orders.quality is ReadDataQuality.FAILED
    assert result.observation.conditional_orders.confirmed_empty is False
    assert result.observation.conditional_orders.failure.code is ReadErrorCode.UNSUPPORTED_CAPABILITY


def test_dummy_token_and_credential_reference_are_not_exposed():
    reference = "opaque-fixture-reference"
    factory = FactorySpy()
    config = ready_config(credential_reference=reference)
    result = HyroMcpConnectionBoundary(factory).read(config, now=NOW)
    combined = repr(config) + repr(result)
    assert reference not in combined
    assert DUMMY_TOKEN not in combined
