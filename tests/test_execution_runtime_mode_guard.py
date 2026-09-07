from unittest.mock import patch

import pytest

import backend.config as backend_config
from backend.runtime.ExecutionRuntime import ExecutionRuntime


class GuardEngine:
    def __init__(
        self,
        *,
        mode,
        configured_mode,
        dry_run,
        live_readiness=None,
    ):
        self.mode = mode
        self.config = {"dry_run": dry_run}
        if configured_mode is not None:
            self.config["mode"] = configured_mode
        self.exchange = None
        self.symbol = "BTCUSDT"
        self.paper_orders = []
        self.actual_position = None
        self.live_readiness = live_readiness or {
            "realOrderAllowed": False,
            "blockReasons": ["LIVE_NOT_READY"],
        }
        self.live_readiness_calls = 0
        self.submit_calls = 0
        self.real_exchange_submit_calls = 0

    def build_live_readiness(self):
        self.live_readiness_calls += 1
        if backend_config.ALLOW_LIVE is not True:
            return {
                "realOrderAllowed": False,
                "blockReasons": ["LIVE_NOT_ENABLED"],
            }
        return self.live_readiness

    def submit_signal(self, signal):
        self.submit_calls += 1
        if self.mode == "live":
            self.real_exchange_submit_calls += 1
            raise AssertionError("blocked LIVE handoff was submitted")
        self.paper_orders.append({"orderId": "paper-guard-1"})
        self.actual_position = {"side": signal["side"]}


def handoff(engine, *, allow_live, trade_mode):
    runtime = ExecutionRuntime()
    runtime.set_engine(engine)
    with patch(
        "backend.config.ALLOW_LIVE",
        allow_live,
    ), patch(
        "backend.config.TRADE_MODE",
        trade_mode,
    ):
        runtime.handoff_adapter_output({"id": 1, "side": "BUY"})
    return runtime


@pytest.mark.parametrize(
    ("allow_live", "trade_mode"),
    [(False, "paper"), (True, "live")],
)
def test_authoritative_paper_handoff_is_independent_of_global_live_config(
    allow_live,
    trade_mode,
):
    engine = GuardEngine(
        mode="paper",
        configured_mode="paper",
        dry_run=True,
    )

    runtime = handoff(
        engine,
        allow_live=allow_live,
        trade_mode=trade_mode,
    )

    assert runtime.handoff_executed is True
    assert runtime.handoff_blocked_reason is None
    assert engine.submit_calls == 1
    assert engine.live_readiness_calls == 0
    assert engine.real_exchange_submit_calls == 0


@pytest.mark.parametrize(
    ("allow_live", "reason"),
    [
        (False, "LIVE_NOT_ENABLED"),
        (True, "REAL_ORDER_DISABLED"),
    ],
)
def test_live_handoff_remains_blocked_when_live_readiness_denies(
    allow_live,
    reason,
):
    engine = GuardEngine(
        mode="live",
        configured_mode="live",
        dry_run=False,
        live_readiness={
            "realOrderAllowed": False,
            "blockReasons": [reason],
        },
    )

    runtime = handoff(
        engine,
        allow_live=allow_live,
        trade_mode="live",
    )

    assert runtime.handoff_executed is False
    assert runtime.handoff_blocked_reason == "LIVE_NOT_READY"
    assert runtime.handoff_live_block_reasons == [reason]
    assert engine.live_readiness_calls == 1
    assert engine.submit_calls == 0
    assert engine.real_exchange_submit_calls == 0


@pytest.mark.parametrize(
    ("mode", "configured_mode", "dry_run"),
    [
        ("unknown", "paper", True),
        ("paper", None, True),
        ("paper", "live", True),
        ("live", "live", True),
    ],
)
def test_unknown_missing_or_conflicting_execution_mode_fails_closed(
    mode,
    configured_mode,
    dry_run,
):
    engine = GuardEngine(
        mode=mode,
        configured_mode=configured_mode,
        dry_run=dry_run,
    )

    runtime = handoff(
        engine,
        allow_live=True,
        trade_mode="live",
    )

    assert runtime.handoff_executed is False
    assert (
        runtime.handoff_blocked_reason
        == "EXECUTION_MODE_UNKNOWN_OR_CONFLICTING"
    )
    assert engine.live_readiness_calls == 0
    assert engine.submit_calls == 0
    assert engine.real_exchange_submit_calls == 0
