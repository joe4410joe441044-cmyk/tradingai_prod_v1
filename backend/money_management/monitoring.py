"""Observation-only monitoring identity and durable last-known MM read models.

Nothing in this module resolves runtime mode or grants execution authority.
"""
import json
import os
import stat
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock


class MonitoringAuthority(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"
    UNKNOWN = "UNKNOWN"


AUTHORITY_BY_SOURCE = {
    "PAPER_RUNTIME_EQUITY": MonitoringAuthority.PAPER,
    "REAL_LIVE_ACCOUNT_EQUITY": MonitoringAuthority.LIVE,
}
SNAPSHOT_FILENAME = "money_management_monitoring.json"
STALE_AFTER = timedelta(minutes=5)


def normalize_identity(value):
    value = value or {}
    source = value.get("accountingAuthoritySource")
    authority = AUTHORITY_BY_SOURCE.get(source, MonitoringAuthority.UNKNOWN)
    return {
        "authority": authority.value,
        "accountingAuthoritySource": source,
        "accountScope": value.get("accountScope"),
        "runtimeInstanceId": value.get("runtimeInstanceId"),
        "sessionId": value.get("sessionId"),
        "accountingRebaseId": value.get("accountingRebaseId"),
        "capturedAt": value.get("capturedAt"),
        "sourceRevision": value.get("sourceRevision"),
        "realizedPnlSemantics": pnl_semantics(authority.value),
    }


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def observation_identity(metrics, state=None):
    source = getattr(metrics, "accounting_authority_source", None)
    state_source = getattr(getattr(state, "accounting_authority_source", None), "value", None)
    same_authority = source is not None and state_source == source
    rebases = getattr(state, "accounting_rebases", ()) if same_authority else ()
    rebase = rebases[-1] if rebases else None
    return normalize_identity({
        "accountingAuthoritySource": source,
        "runtimeInstanceId": getattr(metrics, "runtime_instance_id", None),
        "sessionId": getattr(metrics, "session_id", None),
        "sourceRevision": getattr(metrics, "source_revision", None),
        "capturedAt": iso(metrics.captured_at) if metrics is not None else None,
        "accountScope": getattr(state, "account_scope", None) if same_authority else None,
        "accountingRebaseId": getattr(rebase, "rebase_id", None),
    })


def pnl_semantics(authority):
    return {"PAPER": "PAPER_ENGINE_REPORTED_REALIZED_PNL", "LIVE": "REALIZED_PNL_TODAY"}.get(authority, "UNSPECIFIED")


class MonitoringSnapshotStore:
    """Independent two-authority retention; timeline pruning cannot erase it."""
    def __init__(self, directory):
        self._directory = directory
        self._target = directory / SNAPSHOT_FILENAME
        self._lock = RLock()
        self._snapshots = {}
        if self._target.exists() or self._target.is_symlink():
            self._check_target()
            data = json.loads(self._target.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schemaVersion") != 1:
                raise ValueError("monitoring snapshot schema invalid")
            for authority, snapshot in data["snapshots"].items():
                if authority not in ("PAPER", "LIVE") or normalize_identity(snapshot)["authority"] != authority:
                    raise ValueError("monitoring snapshot authority invalid")
                captured = datetime.fromisoformat(snapshot["capturedAt"].replace("Z", "+00:00"))
                if captured.tzinfo is None:
                    raise ValueError("monitoring timestamp invalid")
                self._snapshots[authority] = snapshot

    def _check_target(self):
        if self._target.is_symlink() or not stat.S_ISREG(self._target.stat().st_mode) or self._target.stat().st_mode & 0o077:
            raise OSError("unsafe monitoring file")

    def record(self, metrics, values, identity, state, recorded_at):
        authority = identity["authority"]
        if authority not in ("PAPER", "LIVE") or identity["capturedAt"] is None:
            return
        def number(name):
            value = getattr(metrics, name, None)
            return str(value) if value is not None else None
        snapshot = {
            **identity, "source": "MM_RUNTIME_OBSERVATION", "recordedAt": iso(recorded_at),
            "metrics": dict(values), "riskState": state,
            "lifecycleContext": getattr(metrics, "source_state", None),
            "metricQuality": getattr(getattr(metrics, "data_quality", None), "value", None),
            "dailyPnl": number("daily_pnl"), "weeklyPnl": number("weekly_pnl"),
            "monthlyPnl": number("monthly_pnl"), "realizedPnlSemantics": pnl_semantics(authority),
        }
        with self._lock:
            old = self._snapshots.get(authority)
            if old and datetime.fromisoformat(old["capturedAt"].replace("Z", "+00:00")) > metrics.captured_at:
                return
            proposed = {**self._snapshots, authority: snapshot}
            raw = json.dumps({"schemaVersion": 1, "snapshots": proposed}, allow_nan=False, sort_keys=True)
            if self._target.exists() or self._target.is_symlink():
                self._check_target()
            fd, temporary = tempfile.mkstemp(prefix=".mm-monitoring-", dir=self._directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._target)
                directory_fd = os.open(self._directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                self._snapshots = proposed
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def get(self, authority):
        with self._lock:
            return deepcopy(self._snapshots.get(authority))


def monitoring_response(store, authority, now):
    snapshot = store.get(authority) if store else None
    response = {
        "viewAuthority": authority, "dataAuthority": authority if snapshot else None,
        "availability": "AVAILABLE" if snapshot else "UNAVAILABLE",
        "semantics": "LAST_KNOWN" if snapshot else "UNAVAILABLE",
        "freshness": "UNAVAILABLE", "source": snapshot["source"] if snapshot else None,
        "asOf": snapshot["capturedAt"] if snapshot else None,
        "staleAfterSeconds": int(STALE_AFTER.total_seconds()), "snapshot": snapshot,
        "fieldCategories": {"metrics": "OBSERVED_MM_METRIC", "metrics.exposureLimit": "CONFIGURATION",
                            "historicalMaximumDrawdown": "UNAVAILABLE", "projectionHistory": "UNAVAILABLE"},
    }
    if snapshot:
        captured = datetime.fromisoformat(snapshot["capturedAt"].replace("Z", "+00:00"))
        age = now - captured
        response["freshness"] = "STALE" if age < timedelta(0) or age > STALE_AFTER else "LAST_KNOWN"
    return response
