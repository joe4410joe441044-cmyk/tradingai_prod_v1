from datetime import datetime, timezone
import json

import pytest

from backend.execution.hyro_mcp_http_transport import (
    HyroMcpDiscoveryResult,
    HyroMcpHttpError,
    HyroMcpToolDescriptor,
)
from backend.prop_trading.hyro_trial_read_service import (
    ENABLED_ENV,
    TOKEN_ENV,
    TRIAL_ID_ENV,
    EnvironmentHyroCredentialResolver,
    HyroTrialReadConfig,
    HyroTrialReadError,
    HyroTrialReadService,
)


TRIAL = "trial-secret-value"
STAGE = "stage-secret-value"
TOKEN = "token-secret-value"


def tool(name, required):
    return HyroMcpToolDescriptor(
        name,
        "Read-only challenge data.",
        {"type": "object", "required": required},
        None,
    )


DISCOVERY = HyroMcpDiscoveryResult(
    "2025-11-25",
    "fixture",
    "1",
    (
        tool("get_challenge", ["challengePublicId"]),
        tool("get_stage_metrics", ["stagePublicId"]),
        tool("get_stage_trades", ["stagePublicId"]),
    ),
)


class FakeTransport:
    def __init__(self, *, mismatch=False, fail_trades=False):
        self.mismatch = mismatch
        self.fail_trades = fail_trades
        self.calls = []

    def initialize_and_list_tools(self):
        return DISCOVERY

    def call_tool_object(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name == "get_challenge":
            return {
                "publicId": "other" if self.mismatch else TRIAL,
                "status": "active",
                "currentStage": {"publicId": STAGE, "type": "evaluation"},
                "ruleSheet": [{"name": "redacted"}],
            }, "CONTENT_TEXT_JSON_OBJECT"
        if name == "get_stage_metrics":
            return {
                "equityMetrics": {
                    "initialBalance": "25000",
                    "currentEquity": "25125.5",
                    "currentDrawdown": "4",
                    "currentLoss": "0",
                },
            }, "CONTENT_TEXT_JSON_OBJECT"
        if self.fail_trades:
            raise HyroMcpHttpError("FIXTURE_TRADES_FAILED")
        return {
            "data": [
                {
                    "closedAt": "2026-11-15T01:00:00Z",
                    "netPnl": "125.5",
                    "accepted": True,
                },
            ],
            "page": 1,
            "pageSize": 100,
            "total": 1,
            "totalPages": 1,
        }, "CONTENT_TEXT_JSON_OBJECT"


def config(**changes):
    values = {
        "enabled": True,
        "token_reference": TOKEN_ENV,
        "trial_public_id": TRIAL,
    }
    values.update(changes)
    return HyroTrialReadConfig(**values)


def service(transport):
    return HyroTrialReadService(
        config=config(),
        transport_factory=lambda _config: transport,
        clock=lambda: datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc),
    )


def test_environment_config_and_resolver_are_allowlisted_and_redacted():
    values = {
        ENABLED_ENV: "true",
        TOKEN_ENV: TOKEN,
        TRIAL_ID_ENV: TRIAL,
    }
    subject = HyroTrialReadConfig.from_environment(values.get)
    resolver = EnvironmentHyroCredentialResolver(values.get)
    assert subject.ready is True
    assert resolver.resolve(TOKEN_ENV) == TOKEN
    with pytest.raises(RuntimeError):
        resolver.resolve("OTHER")
    rendered = repr(subject) + repr(resolver)
    assert TOKEN not in rendered
    assert TRIAL not in rendered


def test_refresh_uses_challenge_stage_chain_and_returns_only_safe_projection():
    transport = FakeTransport()
    result = service(transport).refresh()

    assert [name for name, _ in transport.calls] == [
        "get_challenge", "get_stage_metrics", "get_stage_trades",
    ]
    assert transport.calls[0][1] == {"challengePublicId": TRIAL}
    assert transport.calls[1][1] == {"stagePublicId": STAGE, "period": "all"}
    assert result["updatedAt"] == "2026-11-15T10:00:00Z"
    assert result["status"] == "ACTIVE"
    assert result["stage"] == "EVALUATION"
    assert result["dataQuality"] == "READY"
    assert result["metrics"]["currentEquity"] == 25125.5
    assert result["metrics"]["qualifyingTradingDays"] == 1
    assert result["metrics"]["dailyNetResults"] == [125.5]
    rendered = json.dumps(result)
    assert TOKEN not in rendered
    assert TRIAL not in rendered
    assert STAGE not in rendered
    assert "publicId" not in rendered


def test_trade_failure_returns_partial_without_zero_filling():
    result = service(FakeTransport(fail_trades=True)).refresh()
    assert result["dataQuality"] == "PARTIAL"
    assert result["metrics"]["tradeHistoryComplete"] is False
    assert result["metrics"]["qualifyingTradingDays"] is None
    assert result["metrics"]["dailyNetResults"] is None
    assert result["metrics"]["positions"] is None
    assert result["metrics"]["openOrders"] is None
    assert result["metrics"]["conditionalOrders"] is None


def test_disabled_or_incomplete_configuration_never_constructs_a_transport():
    constructed = []

    def factory(_config):
        constructed.append(_config)
        return FakeTransport()

    for candidate in (
        config(enabled=False),
        config(token_reference=None),
        config(trial_public_id=None),
        config(trial_public_id=" trial-padded "),
    ):
        subject = HyroTrialReadService(config=candidate, transport_factory=factory)
        with pytest.raises(HyroTrialReadError):
            subject.refresh()
    assert constructed == []


def test_scope_mismatch_configuration_and_concurrency_fail_closed():
    with pytest.raises(HyroTrialReadError) as mismatch:
        service(FakeTransport(mismatch=True)).refresh()
    assert mismatch.value.safe_code == "HYRO_TRIAL_CHALLENGE_ID_MISMATCH"

    disabled = HyroTrialReadService(config=config(enabled=False), transport_factory=lambda _: FakeTransport())
    with pytest.raises(HyroTrialReadError) as disabled_error:
        disabled.refresh()
    assert disabled_error.value.status_code == 404

    busy = service(FakeTransport())
    busy._lock.acquire()
    try:
        with pytest.raises(HyroTrialReadError) as busy_error:
            busy.refresh()
        assert busy_error.value.status_code == 409
    finally:
        busy._lock.release()
