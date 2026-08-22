"""Paper-only BotManager runtime boundary for AMS-2B."""

from dataclasses import dataclass
from datetime import datetime, timezone
from copy import deepcopy
import threading

from .safe_switch import SnapshotNotReady

@dataclass
class PreparedFeed:
    feed: object
    runtime_id: str
    previous_feed: object
    previous_runtime_id: str
    symbol: str
    exchange_symbol: str
    snapshot: object = None
    snapshot_timed_out: bool = False


class BotManagerSwitchRuntime:
    """Adapts existing BotManager/KuCoin primitives without adding an authority."""

    def __init__(self, bot_manager, *, position_provider, mm_provider,
                 emergency_provider, snapshot_timeout_seconds=10, clock=None,
                 recorder_integration=None):
        self.manager = bot_manager
        self.position_provider = position_provider
        self.mm_provider = mm_provider
        self.emergency_provider = emergency_provider
        self.snapshot_timeout_seconds = snapshot_timeout_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.recorder_integration = recorder_integration

    def now(self):
        return self.clock()

    def publish_switch_result(self, result):
        observation = deepcopy(
            self.manager.auto_market_selection_observation
        ) if isinstance(self.manager.auto_market_selection_observation, dict) else {}
        observation["switchResult"] = result.to_dict()
        self.manager.set_auto_market_selection_observation(observation)
        if self.recorder_integration is not None:
            # Recording is observational and its result must not change the
            # already-finalized switch transaction or active-symbol authority.
            self.recorder_integration.record_symbol_switch(
                result,
                active_symbol=self.manager.activeSymbol,
                runtime_id=self.manager.active_runtime_id,
            )

    def revalidate_switch(self, proposal):
        try:
            position = self.position_provider()
        except Exception:
            position = None
        try:
            pending = self.manager.get_authoritative_pending_order_state()
            pending = pending.get("pending") if pending.get("known") is True else None
        except Exception:
            pending = None
        try:
            mm = self.mm_provider()
        except Exception:
            mm = None
        try:
            emergency_safe = self.emergency_provider() is True
        except Exception:
            emergency_safe = False
        return {
            "activeSymbol": self.manager.activeSymbol,
            "positionState": position,
            "pendingOrder": pending,
            "mmAvailable": mm is not None,
            "mmFresh": getattr(mm, "authority_fresh", False) is True,
            "emergencySafe": emergency_safe,
        }

    def pause_new_entries(self, transaction_id):
        return self.manager._pause_new_entries_for_safe_switch(transaction_id)

    def resume_new_entries(self, transaction_id):
        return self.manager._resume_new_entries_for_safe_switch(transaction_id)

    def prepare_new_feed(self, symbol, exchange_symbol, transaction_id):
        from backend.market.exchange_factory import ExchangeFactory

        ready = threading.Event()
        runtime_id = transaction_id
        handle = PreparedFeed(
            None, runtime_id, self.manager.ws, self.manager.active_runtime_id,
            symbol, exchange_symbol,
        )

        def staging_callback(callback_symbol, data, callback_runtime_id):
            if callback_runtime_id != runtime_id or callback_symbol != symbol:
                return
            if data.get("symbol") != symbol or data.get("exchange_symbol") != exchange_symbol:
                return
            handle.snapshot = data
            ready.set()
            if (self.manager.active_runtime_id == runtime_id
                    and self.manager.activeSymbol == symbol
                    and callable(self.manager._market_update_callback)):
                self.manager._market_update_callback(callback_symbol, data, callback_runtime_id)

        feed = ExchangeFactory.create_market_ws(
            exchange=self.manager.exchange_name, symbol=symbol,
            on_update=staging_callback, runtime_id=runtime_id,
        )
        handle.feed = feed
        feed.start()
        handle.snapshot_timed_out = not ready.wait(
            self.snapshot_timeout_seconds
        )
        return handle

    def read_new_snapshot(self, handle):
        data = handle.snapshot
        if data is None and handle.snapshot_timed_out:
            return SnapshotNotReady()
        if not isinstance(data, dict):
            return None
        debug = data.get("orderbook_sync_debug") or {}
        timestamp = data.get("market_timestamp")
        if type(timestamp) not in {int, float}:
            return None
        return {
            "symbol": data.get("symbol"),
            "exchangeSymbol": data.get("exchange_symbol"),
            "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc),
            "sequence": data.get("sequence"),
            "sequenceValid": (
                debug.get("isOrderbookSynced") is True
                and debug.get("lastSequenceEnd") == data.get("sequence")
            ),
            "bids": data.get("bids"),
            "asks": data.get("asks"),
        }

    def commit_active_symbol(self, expected, proposed, handle, transaction_id):
        # AMS-2B is deliberately unavailable outside dry-run Paper runtime.
        config = self.manager.config
        if (str(config.get("mode", "paper")).lower() != "paper"
                or config.get("dry_run", True) is not True):
            return False
        return self.manager._commit_active_symbol_for_safe_switch(
            expected, proposed, handle.feed, handle.runtime_id,
            handle.exchange_symbol, transaction_id,
        )

    def commit_limited_live_active_symbol(
        self, expected, proposed, handle, transaction_id, permission,
    ):
        """AMS-7C-only Live commit; grants no execution/order authority."""
        from .live_safe_switch import LiveSymbolSwitchPermission

        config = self.manager.config
        if (not isinstance(permission, LiveSymbolSwitchPermission)
                or permission.enabled is not True
                or not permission.validation_transaction_id
                or not transaction_id
                or permission.expected_active_symbol != expected
                or permission.proposed_symbol != proposed
                or str(config.get("mode", "")).strip().lower() != "live"
                or config.get("dry_run") is not False
                or config.get("realOrderAllowed", False) is not False
                or config.get("autoTradeEnabled", False) is not False
                or config.get("executionRealOrderEnabled", False) is not False):
            return False
        return self.manager._commit_active_symbol_for_safe_switch(
            expected, proposed, handle.feed, handle.runtime_id,
            handle.exchange_symbol, transaction_id,
        )

    def sync_downstream(self, symbol, handle):
        engine = self.manager.engine
        if engine is None:
            return False
        engine.symbol = symbol
        if engine.symbol != symbol:
            return False
        return self.manager._synchronize_market_intelligence_for_safe_switch(
            symbol, handle.runtime_id, handle.snapshot,
        ) is True

    @staticmethod
    def cleanup_old_feed(handle):
        if handle.previous_feed is not None:
            handle.previous_feed.stop()
        return True

    @staticmethod
    def cleanup_new_feed(handle):
        if handle.feed is not None:
            handle.feed.stop()
        return True


class InitialBotManagerCommitRuntime(BotManagerSwitchRuntime):
    """Initial commit sync before the normal Bot Start creates an engine."""

    def sync_downstream(self, symbol, handle):
        snapshot = handle.snapshot
        return bool(
            self.manager.engine is None
            and self.manager.activeSymbol == symbol
            and self.manager.active_runtime_id == handle.runtime_id
            and isinstance(snapshot, dict)
            and snapshot.get("symbol") == symbol
        )


    @staticmethod
    def cleanup_old_feed(handle):
        del handle
        return True
