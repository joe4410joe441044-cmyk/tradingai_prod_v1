"""Durable, deduplicated Money Management runtime timeline."""

import json
import os
import stat
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Mapping, Optional, Tuple
from uuid import uuid4

from .loss_runtime_metrics_models import LossRuntimeMetrics
from .models import MoneyManagementConfig
from .position_risk import calculate_risk_budget
from .monitoring import MonitoringSnapshotStore, observation_identity, normalize_identity


TIMELINE_FILENAME = "money_management_timeline.jsonl"
TIMELINE_TEMP_FILENAME = ".money_management_timeline.jsonl.tmp"
MAX_TIMELINE_EVENTS = 5000
MAX_HISTORY_LIMIT = 500
DEFAULT_HISTORY_LIMIT = 100
METRIC_FIELDS = (
    "equity",
    "availableCapital",
    "realizedPnl",
    "unrealizedPnl",
    "peakEquity",
    "openExposure",
    "exposureLimit",
    "exposureUtilization",
    "positionCount",
    "openPositionState",
    "riskLimitAmount",
    "currentRiskAmount",
    "reservedRiskAmount",
    "riskBudgetRemaining",
    "riskUtilization",
    "drawdownAmount",
    "drawdownPercent",
)


class MoneyManagementTimelineEventType(str, Enum):
    APPLICATION_STARTED = "APPLICATION_STARTED"
    CONFIGURATION_UPDATED = "CONFIGURATION_UPDATED"
    RUNTIME_METRICS_UPDATED = "RUNTIME_METRICS_UPDATED"
    LOSS_STATE_CHANGED = "LOSS_STATE_CHANGED"
    RECOVERY_STATE_CHANGED = "RECOVERY_STATE_CHANGED"
    EXPOSURE_STATE_CHANGED = "EXPOSURE_STATE_CHANGED"
    RISK_BUDGET_CHANGED = "RISK_BUDGET_CHANGED"
    POSITION_STATE_CHANGED = "POSITION_STATE_CHANGED"
    MONEY_MANAGEMENT_LOCKED = "MONEY_MANAGEMENT_LOCKED"
    MONEY_MANAGEMENT_UNLOCKED = "MONEY_MANAGEMENT_UNLOCKED"
    DIAGNOSTIC_RAISED = "DIAGNOSTIC_RAISED"
    DIAGNOSTIC_CLEARED = "DIAGNOSTIC_CLEARED"


def _utc(value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _serialized(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_serialized(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _serialized(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class MoneyManagementTimelineEvent:
    event_id: str
    timestamp: datetime
    sequence: int
    event_type: MoneyManagementTimelineEventType
    source: str
    state: str
    previous_state: Optional[str]
    reason_codes: Tuple[str, ...]
    metrics: Mapping[str, Optional[str]]
    configuration_version: int
    diagnostics: Tuple[str, ...]
    correlation_id: Optional[str]
    changes: Mapping[str, object]
    observation: Optional[Mapping[str, object]] = None

    def __post_init__(self):
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError("event_id required")
        object.__setattr__(self, "timestamp", _utc(self.timestamp))
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("sequence must be positive")
        object.__setattr__(
            self, "event_type", MoneyManagementTimelineEventType(self.event_type)
        )
        for name in ("source", "state"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} required")
        if self.previous_state is not None and not isinstance(
            self.previous_state, str
        ):
            raise TypeError("previous_state invalid")
        object.__setattr__(
            self, "reason_codes", tuple(str(item) for item in self.reason_codes)
        )
        object.__setattr__(
            self, "diagnostics", tuple(str(item) for item in self.diagnostics)
        )
        if set(self.metrics) != set(METRIC_FIELDS):
            raise ValueError("metrics shape invalid")
        if type(self.configuration_version) is not int:
            raise TypeError("configuration_version invalid")
        if self.correlation_id is not None and not isinstance(
            self.correlation_id, str
        ):
            raise TypeError("correlation_id invalid")
        if not isinstance(self.changes, Mapping):
            raise TypeError("changes invalid")

    def to_dict(self):
        return {
            "eventId": self.event_id,
            "timestamp": _serialized(self.timestamp),
            "sequence": self.sequence,
            "eventType": self.event_type.value,
            "source": self.source,
            "state": self.state,
            "previousState": self.previous_state,
            "reasonCodes": list(self.reason_codes),
            "metrics": _serialized(self.metrics),
            "configurationVersion": self.configuration_version,
            "diagnostics": list(self.diagnostics),
            "correlationId": self.correlation_id,
            "changes": _serialized(self.changes),
            **normalize_identity(self.observation),
        }


@dataclass(frozen=True)
class MoneyManagementHistoryResult:
    events: Tuple[MoneyManagementTimelineEvent, ...]
    has_more: bool
    next_cursor: Optional[str]

    def to_dict(self):
        return {
            "events": [event.to_dict() for event in self.events],
            "count": len(self.events),
            "hasMore": self.has_more,
            "nextCursor": self.next_cursor,
        }


def _safe_directory(path):
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("absolute timeline directory required")
    if not path.exists() or not path.is_dir() or path.is_symlink():
        raise OSError("unsafe timeline directory")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise OSError("unsafe timeline parent")
    return path


def _event_from_dict(value):
    expected = {
        "eventId", "timestamp", "sequence", "eventType", "source", "state",
        "previousState", "reasonCodes", "metrics", "configurationVersion",
        "diagnostics", "correlationId", "changes",
    }
    identity_keys = set(normalize_identity(None))
    if not isinstance(value, dict) or not expected <= set(value) or set(value) - expected - identity_keys:
        raise ValueError("event shape invalid")
    metrics = value["metrics"]
    if not isinstance(metrics, dict):
        raise ValueError("event metrics invalid")
    # Timeline records written before the analytics contract extension do not
    # contain these fields. Preserve their meaning as unavailable.
    metrics = {
        key: metrics.get(key)
        for key in METRIC_FIELDS
    }
    timestamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
    return MoneyManagementTimelineEvent(
        value["eventId"], timestamp, value["sequence"], value["eventType"],
        value["source"], value["state"], value["previousState"],
        tuple(value["reasonCodes"]), metrics,
        value["configurationVersion"], tuple(value["diagnostics"]),
        value["correlationId"], value["changes"], normalize_identity(value),
    )


class MoneyManagementTimelineStore:
    def __init__(self, directory, maximum_events=MAX_TIMELINE_EVENTS):
        self._directory = _safe_directory(directory)
        if type(maximum_events) is not int or maximum_events < 1:
            raise ValueError("maximum_events invalid")
        self._maximum_events = maximum_events
        self._target = directory / TIMELINE_FILENAME
        self._temp = directory / TIMELINE_TEMP_FILENAME
        self._lock = RLock()
        self._events = []
        self._corrupt_lines = 0
        self._load()
        self.monitoring = MonitoringSnapshotStore(directory)

    @property
    def corrupt_lines(self):
        return self._corrupt_lines

    def _load(self):
        if self._target.is_symlink():
            raise OSError("unsafe timeline file")
        if not self._target.exists():
            return
        if (
            self._target.is_symlink()
            or not stat.S_ISREG(self._target.stat().st_mode)
            or self._target.stat().st_mode & 0o077
        ):
            raise OSError("unsafe timeline file")
        with self._target.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(
                        line,
                        parse_constant=lambda token: (_ for _ in ()).throw(
                            ValueError(token)
                        ),
                    )
                    self._events.append(_event_from_dict(value))
                except (ValueError, TypeError, KeyError):
                    self._corrupt_lines += 1
        self._events.sort(key=lambda event: event.sequence)
        self._events = self._events[-self._maximum_events:]

    def _signature(self, event):
        value = event.to_dict()
        for key in ("eventId", "timestamp", "sequence", "correlationId"):
            value.pop(key)
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def append(
        self,
        *,
        event_type,
        timestamp,
        source,
        state,
        previous_state=None,
        reason_codes=(),
        metrics=None,
        configuration_version=0,
        diagnostics=(),
        correlation_id=None,
        changes=None,
        observation=None,
    ):
        with self._lock:
            sequence = self._events[-1].sequence + 1 if self._events else 1
            event = MoneyManagementTimelineEvent(
                f"mm-{sequence}-{uuid4().hex}",
                timestamp,
                sequence,
                event_type,
                source,
                state,
                previous_state,
                tuple(reason_codes),
                metrics or {key: None for key in METRIC_FIELDS},
                configuration_version,
                tuple(diagnostics),
                correlation_id,
                changes or {},
                normalize_identity(observation),
            )
            if (
                self._events
                and self._signature(self._events[-1]) == self._signature(event)
            ):
                return None
            raw = (
                json.dumps(
                    event.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            if self._target.exists() and (
                self._target.is_symlink()
                or not stat.S_ISREG(self._target.stat().st_mode)
                or self._target.stat().st_mode & 0o077
            ):
                raise OSError("unsafe timeline file")
            fd = os.open(
                self._target,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                offset = 0
                while offset < len(raw):
                    written = os.write(fd, raw[offset:])
                    if written <= 0:
                        raise OSError("timeline short write")
                    offset += written
                os.fsync(fd)
            finally:
                os.close(fd)
            self._events.append(event)
            if len(self._events) > self._maximum_events:
                self._events = self._events[-self._maximum_events:]
                self._rewrite()
            return event

    def _rewrite(self):
        if self._temp.exists():
            raise OSError("timeline temp exists")
        fd = os.open(
            self._temp,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            for event in self._events:
                raw = (
                    json.dumps(
                        event.to_dict(), sort_keys=True,
                        separators=(",", ":"), allow_nan=False,
                    ) + "\n"
                ).encode("utf-8")
                offset = 0
                while offset < len(raw):
                    written = os.write(fd, raw[offset:])
                    if written <= 0:
                        raise OSError("timeline retention short write")
                    offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(self._temp, self._target)
        directory_fd = os.open(
            self._directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def query(self, *, limit=DEFAULT_HISTORY_LIMIT, before=None,
              after=None, event_type=None, state=None, authority="ALL"):
        if type(limit) is not int or limit < 1 or limit > MAX_HISTORY_LIMIT:
            raise ValueError("history limit invalid")
        if authority not in ("ALL", "PAPER", "LIVE", "UNKNOWN"):
            raise ValueError("authority filter invalid")
        def cursor_key(cursor):
            if not isinstance(cursor, str):
                raise ValueError("cursor invalid")
            parts = cursor.split(":", 1)
            if not parts[0].isascii() or not parts[0].isdigit() or int(parts[0]) < 1:
                raise ValueError("cursor invalid")
            if len(parts) == 2 and not parts[1]:
                raise ValueError("cursor invalid")
            return int(parts[0]), parts[1] if len(parts) == 2 else None
        with self._lock:
            selected = list(self._events)
        if authority != "ALL":
            selected = [e for e in selected if normalize_identity(e.observation)["authority"] == authority]
        for cursor, is_before in ((before, True), (after, False)):
            if cursor is not None:
                sequence, event_id = cursor_key(cursor)
                def matches(e):
                    left = (e.sequence, e.event_id) if event_id is not None else e.sequence
                    right = (sequence, event_id) if event_id is not None else sequence
                    return left < right if is_before else left > right
                selected = [e for e in selected if matches(e)]
        if event_type is not None:
            normalized = MoneyManagementTimelineEventType(event_type)
            selected = [event for event in selected if event.event_type is normalized]
        if state is not None:
            if not isinstance(state, str) or not state:
                raise ValueError("state filter invalid")
            selected = [event for event in selected if event.state == state]
        selected.sort(key=lambda event: (event.sequence, event.event_id), reverse=True)
        page = selected[:limit]
        # Numeric cursors remain accepted; composite cursors disambiguate old
        # duplicate sequences without rewriting any historical record.
        next_cursor = None
        if len(selected) > limit and page:
            last = page[-1]
            next_cursor = f"{last.sequence}:{last.event_id}"
        return MoneyManagementHistoryResult(tuple(page), len(selected) > limit, next_cursor)


def timeline_metrics(metrics, config):
    if not isinstance(metrics, LossRuntimeMetrics):
        return {key: None for key in METRIC_FIELDS}
    exposure_limit = (
        metrics.equity * config.total_exposure_pct / Decimal("100")
        if isinstance(config, MoneyManagementConfig)
        and metrics.equity is not None else None
    )
    exposure_utilization = (
        metrics.open_exposure / exposure_limit * Decimal("100")
        if metrics.open_exposure is not None
        and exposure_limit is not None and exposure_limit > 0 else None
    )
    current = (
        Decimal("0")
        if metrics.position_count == 0
        else metrics.current_risk_amount
    )
    reserved = (
        Decimal("0")
        if metrics.pending_order_count == 0
        else metrics.reserved_risk_amount
    )
    risk = calculate_risk_budget(
        metrics.available_balance,
        config.risk_per_trade_pct
        if isinstance(config, MoneyManagementConfig) else None,
        current,
        reserved,
    )
    values = {
        "equity": metrics.equity,
        "availableCapital": metrics.available_balance,
        "realizedPnl": metrics.realized_pnl,
        "unrealizedPnl": metrics.unrealized_pnl,
        "peakEquity": metrics.peak_equity,
        "openExposure": metrics.open_exposure,
        "exposureLimit": (
            config.total_exposure_pct
            if isinstance(config, MoneyManagementConfig) else None
        ),
        "exposureUtilization": exposure_utilization,
        "positionCount": metrics.position_count,
        "openPositionState": (
            "FLAT" if metrics.position_count == 0
            else metrics.position_side
            if metrics.position_count is not None
            and metrics.position_count > 0
            and metrics.position_side in ("LONG", "SHORT", "OPEN")
            else "OPEN"
            if metrics.position_count is not None
            and metrics.position_count > 0
            else "UNKNOWN"
        ),
        "riskLimitAmount": risk.risk_limit_amount,
        "currentRiskAmount": risk.current_risk_amount,
        "reservedRiskAmount": risk.reserved_risk_amount,
        "riskBudgetRemaining": risk.risk_budget_remaining,
        "riskUtilization": risk.risk_utilization,
        "drawdownAmount": (
            metrics.peak_equity - metrics.equity
            if metrics.peak_equity is not None and metrics.equity is not None
            else None
        ),
        "drawdownPercent": metrics.drawdown,
    }
    return {key: _serialized(values[key]) for key in METRIC_FIELDS}


class MoneyManagementTimelineRecorder:
    def __init__(self, store, timestamp_source=None):
        if not isinstance(store, MoneyManagementTimelineStore):
            raise TypeError("timeline store required")
        self.store = store
        self._now = timestamp_source or (lambda: datetime.now(timezone.utc))
        self._last_observation = normalize_identity(None)
        self._last_metrics = None
        self._last_state = None
        self._last_diagnostics = ()
        latest = store.query(limit=1).events
        if latest:
            self._last_observation = normalize_identity(latest[0].observation)
            self._last_metrics = dict(latest[0].metrics)
            self._last_state = latest[0].state
            self._last_diagnostics = latest[0].diagnostics

    def record_started(self, state="RUNNING"):
        return self.store.append(
            event_type=MoneyManagementTimelineEventType.APPLICATION_STARTED,
            timestamp=self._now(), source="APPLICATION", state=state,
        )

    def record_runtime(self, metrics, config, state, diagnostics=(),
                       correlation_id=None, configuration_version=0,
                       reason_codes=(), reason_groups=None, observation_state=None):
        snapshot = timeline_metrics(metrics, config)
        identity = observation_identity(metrics, observation_state)
        self.store.monitoring.record(metrics, snapshot, identity, state, self._now())
        previous_metrics = self._last_metrics
        previous_state = self._last_state
        events = []
        common = {
            "timestamp": self._now(),
            "observation": identity,
            "source": "LOSS_RUNTIME",
            "state": state,
            "previous_state": previous_state,
            "metrics": snapshot,
            "configuration_version": configuration_version,
            "diagnostics": tuple(diagnostics),
            "reason_codes": tuple(reason_codes),
            "correlation_id": correlation_id,
        }
        if previous_metrics != snapshot or identity != self._last_observation:
            events.append(self.store.append(
                event_type=MoneyManagementTimelineEventType.RUNTIME_METRICS_UPDATED,
                changes={
                    "previousMetrics": previous_metrics or {},
                    "reasonGroups": reason_groups or {},
                },
                **common,
            ))
        if previous_state is not None and previous_state != state:
            events.append(self.store.append(
                event_type=MoneyManagementTimelineEventType.LOSS_STATE_CHANGED,
                changes={"from": previous_state, "to": state},
                **common,
            ))
            if state == "LOCKED":
                events.append(self.store.append(
                    event_type=MoneyManagementTimelineEventType.MONEY_MANAGEMENT_LOCKED,
                    **common,
                ))
            elif previous_state == "LOCKED":
                events.append(self.store.append(
                    event_type=MoneyManagementTimelineEventType.MONEY_MANAGEMENT_UNLOCKED,
                    **common,
                ))
        comparisons = (
            ("exposureUtilization", MoneyManagementTimelineEventType.EXPOSURE_STATE_CHANGED),
            ("riskUtilization", MoneyManagementTimelineEventType.RISK_BUDGET_CHANGED),
            ("openPositionState", MoneyManagementTimelineEventType.POSITION_STATE_CHANGED),
        )
        if previous_metrics is not None:
            for field, event_type in comparisons:
                if previous_metrics.get(field) != snapshot.get(field):
                    events.append(self.store.append(
                        event_type=event_type,
                        changes={
                            "field": field,
                            "from": previous_metrics.get(field),
                            "to": snapshot.get(field),
                        },
                        **common,
                    ))
        raised = tuple(item for item in diagnostics if item not in self._last_diagnostics)
        cleared = tuple(item for item in self._last_diagnostics if item not in diagnostics)
        if raised:
            events.append(self.store.append(
                event_type=MoneyManagementTimelineEventType.DIAGNOSTIC_RAISED,
                changes={"raised": raised}, **common,
            ))
        if cleared:
            events.append(self.store.append(
                event_type=MoneyManagementTimelineEventType.DIAGNOSTIC_CLEARED,
                changes={"cleared": cleared}, **common,
            ))
        self._last_observation = identity
        self._last_metrics = snapshot
        self._last_state = state
        self._last_diagnostics = tuple(diagnostics)
        return tuple(event for event in events if event is not None)

    def record_configuration(self, *, before, after, version,
                             base_before=None, base_after=None,
                             correlation_id=None):
        changes = {}
        for prefix, old_value, new_value in (
            ("loss", before, after),
            ("base", base_before, base_after),
        ):
            if old_value is None or new_value is None:
                continue
            for field in fields(old_value):
                old = getattr(old_value, field.name)
                new = getattr(new_value, field.name)
                if old != new:
                    changes[f"{prefix}.{field.name}"] = {
                        "before": _serialized(old),
                        "after": _serialized(new),
                    }
        return self.store.append(
            event_type=MoneyManagementTimelineEventType.CONFIGURATION_UPDATED,
            timestamp=self._now(), source="CONFIGURATION_API",
            state=self._last_state or "UNKNOWN",
            previous_state=self._last_state,
            metrics=self._last_metrics or {key: None for key in METRIC_FIELDS},
            observation=self._last_observation,
            configuration_version=version,
            correlation_id=correlation_id,
            changes=changes,
        )

    def record_recovery(self, *, previous_state, current_state,
                        version, correlation_id=None):
        return self.store.append(
            event_type=MoneyManagementTimelineEventType.RECOVERY_STATE_CHANGED,
            timestamp=self._now(), source="RECOVERY_API",
            state=current_state,
            previous_state=previous_state,
            metrics=self._last_metrics or {key: None for key in METRIC_FIELDS},
            observation=self._last_observation,
            configuration_version=version,
            correlation_id=correlation_id,
            changes={"from": previous_state, "to": current_state},
        )
