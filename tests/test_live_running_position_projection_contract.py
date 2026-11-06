"""RB-25: running LIVE account projection must retain position authority.

Offline only: no exchange calls, no runtime mutation, no orders. These tests
exercise the backend boundary that feeds ``startPositionAuthorityValue`` on the
Dashboard. The internal engine vocabulary ``NO_OPEN_POSITION`` is normalized to
the canonical consumer ``FLAT`` only at this projection boundary.
"""
from unittest.mock import Mock, patch

from backend.bot_manager.bot_manager import BotManager

NOW = 1790695880.0
SYMBOL = "XRPUSDTM"


class EmptyHistory:
    def __init__(self, *args, **kwargs):
        self.store = Mock(read_failed=False)

    def history(self, **kwargs):
        return {"records": []}


class LiveReadinessEngine:
    """Minimal engine readiness authority, matching ExecutionEngine's shape."""

    mode = "live"

    def __init__(self, *, state, real_position):
        self.symbol = SYMBOL
        self.latest_price = 2.0
        self.real_position = real_position
        self.real_position_state = state

    def build_live_readiness(self):
        return {
            "entryAuthority": "MANUAL",
            "ready": False,
            "realOrderAllowed": False,
            "checks": {
                "selectedModeLive": True,
                "dryRunDisabled": True,
                "allowLive": True,
                "tradeModeLive": True,
                "exchangeClientReady": True,
                "exchangeAuthReady": True,
                "balanceCheckOk": True,
                "positionCheckOk": True,
                "executionEnabled": False,
                "liveOrderEntryAllowed": False,
                "emergencyStopClear": True,
            },
            "blockReasons": ["LIVE_ORDER_ENTRY_DISARMED"],
            "selectedMode": "LIVE",
            "dryRun": False,
            "exchangeClientReady": True,
            "exchangeAuthReady": True,
            "balanceCheckOk": True,
            "positionCheckOk": True,
            "executionEnabled": False,
            "emergencyStop": False,
            "realBalance": 100.0,
            "realEquity": 100.0,
            "realAvailableBalance": 90.0,
            "realUnrealizedPnl": 0.0,
            "realMarginUsed": None,
            "realMarginAvailable": None,
            "realPosition": self.real_position,
            "realPositionState": self.real_position_state,
            "realAccountLastSync": NOW,
            "exchangeConnection": "CONNECTED",
            "apiKeyStatus": "VERIFIED",
            "permission": "READ_ONLY",
            "accountType": "KUCOIN_FUTURES",
            "exchangeAuthReason": "KUCOIN_CREDENTIALS_VERIFIED",
            "exchangeConnectionReason": "KUCOIN_CLIENT_READY",
            "accountReason": "KUCOIN_READ_ONLY_SYNC_OK",
            "balanceReason": "KUCOIN_BALANCE_SYNC_OK",
            "positionReason": "KUCOIN_POSITION_SYNC_OK",
        }


def raw_row(qty, symbol=SYMBOL):
    return {
        "id": f"{symbol}:{qty}",
        "symbol": symbol,
        "currentQty": qty,
        "avgEntryPrice": 2.0,
        "markPrice": 2.0,
        "markValue": abs(qty) * 10 * 2.0,
        "unrealisedPnl": 0.0,
        "realLeverage": 3,
        "posMargin": abs(qty) * 10 * 2.0 / 3,
        "liquidationPrice": 1.0,
        "openingTimestamp": int((NOW - 10) * 1000),
    }


def legacy_row(qty):
    return {
        "symbol": SYMBOL,
        "qty": abs(qty),
        "side": "BUY" if qty > 0 else "SELL",
        "entry_price": 2.0,
    }


def canonical_account(*, observation, positions, summary):
    return {
        "exchange": "kucoin",
        "accountType": "KUCOIN_FUTURES",
        "connected": True,
        "authenticated": True,
        "apiKeyPresent": True,
        "permission": "READ_ONLY",
        "balance": 100.0,
        "equity": 100.0,
        "availableBalance": 90.0,
        "walletBalance": 100.0,
        "unrealizedPnl": 0.0,
        "realizedPnlToday": 0.0,
        "totalPnlToday": 0.0,
        "marginUsed": None,
        "marginAvailable": None,
        "marginRatio": None,
        "dailyPnlSource": None,
        "dailyPnlObservedAt": None,
        "dailyPnlDayStart": None,
        "positions": positions,
        "positionSummary": summary,
        "positionObservation": observation,
        "lastSync": NOW,
        "lastAttempt": NOW,
        "stale": False,
        "loading": False,
        "authReason": "KUCOIN_CREDENTIALS_VERIFIED",
        "connectionReason": "KUCOIN_CLIENT_READY",
        "accountReason": "KUCOIN_READ_ONLY_SYNC_OK",
        "balanceReason": "KUCOIN_BALANCE_SYNC_OK",
        "positionReason": "KUCOIN_POSITION_SYNC_OK",
        "lastError": None,
        "accountSource": "KUCOIN_FUTURES_READ_ONLY",
        "balanceSource": "KUCOIN_FUTURES_READ_ONLY",
        "positionSource": "KUCOIN_FUTURES_READ_ONLY",
        "generation": 0,
    }


def build_runtime(*, state, real_position, observation, positions, summary):
    canonical = canonical_account(
        observation=observation,
        positions=positions,
        summary=summary,
    )
    bot = BotManager()
    bot.engine = LiveReadinessEngine(state=state, real_position=real_position)
    bot.symbol = SYMBOL
    bot._get_real_account_snapshot = lambda *args, **kwargs: canonical
    bot.real_account_snapshot = canonical

    with patch(
        "backend.runtime.trade_history_read.TradeHistoryService",
        EmptyHistory,
    ), patch(
        "backend.bot_manager.bot_manager.time.time",
        return_value=NOW,
    ):
        readiness = bot._build_live_readiness_snapshot("LIVE", False)
        runtime = bot._build_account_runtime(
            {},
            readiness,
            "LIVE",
            False,
            "SIMULATION",
            False,
        )
    return readiness, runtime


def test_running_live_flat_retains_observation_and_resolves_canonical_flat():
    observation = {"positions": [], "sourceUpdatedAt": NOW}
    readiness, runtime = build_runtime(
        state="NO_OPEN_POSITION",
        real_position=None,
        observation=observation,
        positions=[],
        summary="FLAT",
    )

    real = runtime["realAccount"]
    live = runtime["positionsByMode"]["LIVE"]

    assert real["positionObservation"] == observation
    assert real["positionSummary"] == "FLAT"
    assert real["positions"] == []
    assert live["status"] == "FLAT"
    assert live["freshness"] == "FRESH"
    assert live["sourceUpdatedAt"] == NOW
    assert runtime["currentPosition"] == live
    assert readiness["realPositionState"] == "FLAT"


def test_running_live_open_long_preserves_position_and_summary():
    observation = {"positions": [raw_row(1)], "sourceUpdatedAt": NOW}
    row = legacy_row(1)
    readiness, runtime = build_runtime(
        state="OPEN",
        real_position=row,
        observation=observation,
        positions=[row],
        summary="OPEN",
    )

    real = runtime["realAccount"]
    live = runtime["positionsByMode"]["LIVE"]

    assert real["positionObservation"] == observation
    assert real["positionSummary"] == "OPEN"
    assert len(real["positions"]) == 1
    assert live["status"] == "OPEN"
    assert live["side"] == "LONG"
    assert live["freshness"] == "FRESH"
    assert live["positions"][0]["symbol"] == SYMBOL
    assert live["positions"][0]["contractQuantity"] == 1
    assert readiness["realPositionState"] == "OPEN"


def test_running_live_open_short_preserves_position_and_summary():
    observation = {"positions": [raw_row(-2)], "sourceUpdatedAt": NOW}
    row = legacy_row(-2)
    readiness, runtime = build_runtime(
        state="OPEN",
        real_position=row,
        observation=observation,
        positions=[row],
        summary="OPEN",
    )

    real = runtime["realAccount"]
    live = runtime["positionsByMode"]["LIVE"]

    assert real["positionObservation"] == observation
    assert real["positionSummary"] == "OPEN"
    assert live["status"] == "OPEN"
    assert live["side"] == "SHORT"
    assert live["positions"][0]["contractQuantity"] == 2
    assert readiness["realPositionState"] == "OPEN"


def test_running_live_stale_observation_fails_closed():
    observation = {"positions": [], "sourceUpdatedAt": NOW - 91}
    _, runtime = build_runtime(
        state="NO_OPEN_POSITION",
        real_position=None,
        observation=observation,
        positions=[],
        summary="FLAT",
    )

    live = runtime["positionsByMode"]["LIVE"]
    assert live["status"] == "UNKNOWN"
    assert live["freshness"] == "STALE"


def test_running_live_unavailable_observation_fails_closed():
    observation = {"positions": None, "sourceUpdatedAt": None}
    _, runtime = build_runtime(
        state="NO_OPEN_POSITION",
        real_position=None,
        observation=observation,
        positions=[],
        summary="FLAT",
    )

    real = runtime["realAccount"]
    live = runtime["positionsByMode"]["LIVE"]
    assert real["positionObservation"] == observation
    assert real["positionSummary"] == "FLAT"
    assert live["status"] == "UNKNOWN"


def test_running_live_missing_observation_is_not_fabricated():
    canonical = canonical_account(
        observation=None,
        positions=[],
        summary="FLAT",
    )
    canonical.pop("positionObservation")
    bot = BotManager()
    bot.engine = LiveReadinessEngine(state="NO_OPEN_POSITION", real_position=None)
    bot.symbol = SYMBOL
    bot._get_real_account_snapshot = lambda *args, **kwargs: canonical
    bot.real_account_snapshot = canonical

    with patch(
        "backend.runtime.trade_history_read.TradeHistoryService",
        EmptyHistory,
    ), patch(
        "backend.bot_manager.bot_manager.time.time",
        return_value=NOW,
    ):
        readiness = bot._build_live_readiness_snapshot("LIVE", False)

    assert readiness["realAccount"]["positionObservation"] is None


def test_running_live_inconsistent_observation_and_engine_fails_closed():
    observation = {"positions": [], "sourceUpdatedAt": NOW}
    row = legacy_row(1)
    _, runtime = build_runtime(
        state="OPEN",
        real_position=row,
        observation=observation,
        positions=[row],
        summary="OPEN",
    )

    live = runtime["positionsByMode"]["LIVE"]
    assert live["status"] == "FLAT"
    assert runtime["realAccount"]["positionSummary"] == "OPEN"


def test_position_summary_normalization_is_boundary_only():
    assert BotManager._normalize_position_summary("NO_OPEN_POSITION", []) == "FLAT"
    assert BotManager._normalize_position_summary("NO_OPEN_POSITION", None) == "UNKNOWN"
    assert BotManager._normalize_position_summary(
        "NO_OPEN_POSITION", [{"qty": 1}],
    ) == "UNKNOWN"
    assert BotManager._normalize_position_summary("OPEN", [{"qty": 1}]) == "OPEN"
    assert BotManager._normalize_position_summary("FLAT", []) == "FLAT"
    assert BotManager._normalize_position_summary("SYNC_FAILED", []) == "SYNC_FAILED"
    assert BotManager._normalize_position_summary(None, []) == "FLAT"
