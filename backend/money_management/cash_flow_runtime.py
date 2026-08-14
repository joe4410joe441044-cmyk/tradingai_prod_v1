"""MM-owned, GET-only external cash-flow synchronization runtime."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from threading import Event, Lock, Thread
import time

from .cash_flow_adjustment import reconcile_equity_change
from .external_cash_flow import (
    advance_checkpoint, baseline_from_persisted_loss_state, classify_deposit,
    classify_withdrawal, eligible_events, load_cash_flow_checkpoint,
    net_external_cash_flow, save_cash_flow_checkpoint,
    validate_futures_ledger_page, validate_paginated_items,
)
from .loss_persistence_adapter import LoadStatus, load_loss_state
from .loss_persistence_models import (
    CashFlowType, FreshnessStatus, PersistedCashFlowState,
    PersistedDrawdownState,
)

DAY_MS = 86_400_000
DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_FRESHNESS_SECONDS = 600
MAX_PAGES = 10_000


class CashFlowSyncState(str, Enum):
    STOPPED = "STOPPED"
    IDLE = "IDLE"
    SYNCING = "SYNCING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CashFlowSyncResult:
    accepted: bool
    state: CashFlowSyncState
    events_applied: int = 0
    checkpoint_revision: int = 0
    reason: str | None = None


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


class CashFlowAuthorityReader:
    """Collect all required KuCoin histories before exposing any events."""

    def __init__(self, client, *, page_size=50, max_pages=MAX_PAGES):
        self._client = client
        self._page_size = page_size
        self._max_pages = max_pages

    def _wallet(self, method, validator, start_ms, end_ms):
        result, page = [], 1
        while page <= self._max_pages:
            payload = method(start_at=start_ms, end_at=end_ms,
                             current_page=page, page_size=self._page_size)
            items = validate_paginated_items(payload, expected_page=page)
            for item in items:
                validator(item)
            result.extend(items)
            total = payload["totalPage"]
            if total == 0 or page >= total:
                return tuple(result)
            page += 1
        raise ValueError("pagination limit exceeded")

    def _ledger_window(self, start_ms, end_ms):
        result, offset, seen = [], None, set()
        for _ in range(self._max_pages):
            payload = self._client.get_futures_transaction_history(
                start_at=start_ms, end_at=end_ms, offset=offset,
                max_count=self._page_size,
            )
            items, next_offset = validate_futures_ledger_page(payload)
            result.extend(items)
            if next_offset is None:
                return tuple(result)
            if next_offset in seen or next_offset == offset:
                raise ValueError("malformed Futures ledger cursor")
            seen.add(next_offset)
            offset = next_offset
        raise ValueError("pagination limit exceeded")

    def read(self, *, start_at, end_at):
        start, end = _utc(start_at), _utc(end_at)
        start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        if end_ms < start_ms:
            raise ValueError("invalid cash-flow range")
        # Wallet histories are corroborating evidence. A failure still fails the
        # authoritative sync, but only Futures transfers become canonical MM flows.
        self._wallet(self._client.get_deposit_history, classify_deposit,
                     start_ms, end_ms)
        self._wallet(self._client.get_withdrawal_history, classify_withdrawal,
                     start_ms, end_ms)
        ledger = []
        window_start = start_ms
        while window_start <= end_ms:
            window_end = min(end_ms, window_start + DAY_MS)
            ledger.extend(self._ledger_window(window_start, window_end))
            window_start = window_end + 1
        return tuple(ledger)


def _decimal_equity(value):
    if isinstance(value, dict):
        if value.get("sourceAuthority") not in (None, "REAL_LIVE_ACCOUNT"):
            raise ValueError("current equity authority invalid")
        value = value.get("equity")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("current REAL_LIVE_ACCOUNT equity unavailable") from None
    if not result.is_finite() or result < 0:
        raise ValueError("current REAL_LIVE_ACCOUNT equity unavailable")
    return result


def build_cash_flow_loss_state(state, events, *, current_equity, captured_at):
    """Apply external flow separation using existing MM persisted semantics."""
    at = _utc(captured_at)
    equity = _decimal_equity(current_equity)
    net = net_external_cash_flow(events)
    previous_adjusted = state.drawdown_state.current_equity
    previous_actual = previous_adjusted + state.cash_flow_state.net_cash_flow_amount
    adjusted = reconcile_equity_change(
        previous_equity=previous_actual, current_equity=equity,
        net_external_cash_flow=net, previous_adjusted_equity=previous_adjusted,
        previous_adjusted_high_water_mark=state.drawdown_state.high_water_mark,
    )

    def period(item):
        pnl = item.net_realized_pnl + adjusted.trading_pnl
        loss = max(Decimal("0"), -pnl)
        return replace(item, net_realized_pnl=pnl, net_loss=loss,
                       loss_percent=loss / item.starting_equity * Decimal("100"),
                       cash_flow_amount=item.cash_flow_amount + net,
                       last_updated_at=min(at, item.period_end))

    cash = PersistedCashFlowState(
        False, (),
        state.cash_flow_state.net_cash_flow_amount + net,
        max(event.occurred_at for event in events) if events
        else state.cash_flow_state.last_cash_flow_at,
    )
    drawdown = PersistedDrawdownState(
        adjusted.adjusted_high_water_mark, adjusted.adjusted_equity,
        adjusted.drawdown_amount, adjusted.drawdown_percent, at,
    )
    return replace(state, daily_state=period(state.daily_state),
                   weekly_state=period(state.weekly_state),
                   monthly_state=period(state.monthly_state),
                   drawdown_state=drawdown, cash_flow_state=cash,
                   captured_at=at, freshness=FreshnessStatus.VALID)


class CashFlowSyncRuntime:
    """The single Money Management invocation owner and non-overlapping poller."""

    def __init__(self, *, persistence_directory, reader, equity_source,
                 transaction_coordinator, enabled=True,
                 poll_interval_seconds=DEFAULT_POLL_INTERVAL_SECONDS,
                 freshness_seconds=DEFAULT_FRESHNESS_SECONDS, clock=None):
        if poll_interval_seconds <= 0 or freshness_seconds <= 0:
            raise ValueError("positive cash-flow timing required")
        self._base = persistence_directory
        self._reader, self._equity = reader, equity_source
        self._transaction = transaction_coordinator
        self._enabled = bool(enabled)
        self._interval, self._freshness = poll_interval_seconds, freshness_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sync_lock, self._status_lock = Lock(), Lock()
        self._stop = Event()
        self._thread = None
        self._state = CashFlowSyncState.STOPPED
        self._last_attempt = self._last_success = self._last_error = None
        self._checkpoint_revision = 0

    def initialize(self):
        # Composition has already loaded baseline and recovered transactions.
        checkpoint = load_cash_flow_checkpoint(self._base)
        with self._status_lock:
            self._checkpoint_revision = checkpoint.revision
            self._last_success = checkpoint.last_successful_sync_at
            self._state = CashFlowSyncState.IDLE if self._enabled else CashFlowSyncState.STOPPED
        return self.read_model()

    def start(self, *, immediate=True):
        self.initialize()
        if not self._enabled or (self._thread and self._thread.is_alive()):
            return False
        self._stop.clear()
        self._thread = Thread(target=self._run, args=(immediate,),
                              name="mm-cash-flow-sync", daemon=True)
        self._thread.start()
        return True

    def _run(self, immediate):
        if immediate and not self._stop.is_set():
            self.sync_once()
        while not self._stop.wait(self._interval):
            self.sync_once()

    def stop(self, timeout=5):
        self._stop.set()
        thread = self._thread
        if thread:
            thread.join(timeout)
        with self._status_lock:
            self._state = CashFlowSyncState.STOPPED
        return not bool(thread and thread.is_alive())

    def sync_once(self):
        if not self._enabled:
            return CashFlowSyncResult(False, CashFlowSyncState.STOPPED,
                                      checkpoint_revision=self._checkpoint_revision,
                                      reason="DISABLED")
        if not self._sync_lock.acquire(blocking=False):
            return CashFlowSyncResult(False, CashFlowSyncState.SYNCING,
                                      checkpoint_revision=self._checkpoint_revision,
                                      reason="SYNC_ALREADY_RUNNING")
        now = _utc(self._clock())
        with self._status_lock:
            self._state, self._last_attempt, self._last_error = CashFlowSyncState.SYNCING, now, None
        try:
            loaded = load_loss_state(self._base)
            if loaded.status is not LoadStatus.VALID:
                raise RuntimeError("authoritative MM state unavailable")
            checkpoint = load_cash_flow_checkpoint(self._base)
            baseline = baseline_from_persisted_loss_state(loaded.state)
            ledger = self._reader.read(start_at=baseline, end_at=now)
            events = eligible_events(ledger, baseline_at=baseline,
                                     processed_event_ids=checkpoint.processed_event_ids)
            new_checkpoint = advance_checkpoint(checkpoint, events, synced_at=now)
            if events:
                new_state = build_cash_flow_loss_state(
                    loaded.state, events, current_equity=self._equity(), captured_at=now)
                self._transaction.commit(
                    expected_revision=checkpoint.revision, new_state=new_state,
                    new_checkpoint=new_checkpoint,
                    event_ids=tuple(event.event_id for event in events), now=now,
                )
            else:
                # No loss-state rewrite and no revision churn; only freshness moves.
                save_cash_flow_checkpoint(new_checkpoint, self._base)
            with self._status_lock:
                self._state, self._last_success = CashFlowSyncState.COMPLETED, now
                self._checkpoint_revision = new_checkpoint.revision
            return CashFlowSyncResult(True, CashFlowSyncState.COMPLETED, len(events),
                                      new_checkpoint.revision)
        except Exception as exc:
            with self._status_lock:
                self._state, self._last_error = CashFlowSyncState.FAILED, type(exc).__name__
            return CashFlowSyncResult(True, CashFlowSyncState.FAILED,
                                      checkpoint_revision=self._checkpoint_revision,
                                      reason=type(exc).__name__)
        finally:
            self._sync_lock.release()

    def read_model(self):
        with self._status_lock:
            now, last = _utc(self._clock()), self._last_success
            fresh = bool(self._enabled and last and
                         (now - last).total_seconds() <= self._freshness)
            authority = "DISABLED" if not self._enabled else "READY" if fresh else "FAILED" if self._state is CashFlowSyncState.FAILED else "STALE"
            return {
                "cashFlowAuthority": authority, "cashFlowFresh": fresh,
                "lastSuccessfulSyncAt": last.isoformat().replace("+00:00", "Z") if last else None,
                "lastAttemptAt": self._last_attempt.isoformat().replace("+00:00", "Z") if self._last_attempt else None,
                "syncState": self._state.value, "lastErrorReason": self._last_error,
                "checkpointRevision": self._checkpoint_revision,
            }
