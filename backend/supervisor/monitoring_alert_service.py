"""Read-only / ingest service for the Supervisor alert outbox.

The service is observational metadata only.  It never delivers an external
notification, never mutates trading/MM/Governance state and never acts as a
second anomaly-state authority.  Reads never create the store; when the outbox
is not configured the read model is explicitly unavailable.
"""
from __future__ import annotations

from datetime import datetime

from .monitoring_alert_models import (
    AlertCandidate,
    AlertIngestResult,
    AlertPage,
    AlertRecord,
)
from .monitoring_alert_store import AlertStoreError, MonitoringAlertStore

ALERT_DISABLED = "ALERT_OUTBOX_DISABLED"
ALERT_NOT_CONFIGURED = "ALERT_OUTBOX_NOT_CONFIGURED"


class MonitoringAlertService:
    """Bounded alert outbox service.  Constructor performs no I/O."""

    def __init__(
        self,
        *,
        store: MonitoringAlertStore | None = None,
        enabled: bool = False,
        max_page: int = 20,
    ) -> None:
        if store is not None and not isinstance(store, MonitoringAlertStore):
            raise TypeError("store must be a MonitoringAlertStore or None")
        if not isinstance(max_page, int) or isinstance(max_page, bool) or not 1 <= max_page <= 100:
            raise ValueError("max_page out of range")
        self._store = store
        self._enabled = bool(enabled)
        self._max_page = max_page

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def configured(self) -> bool:
        return self._store is not None

    @property
    def available(self) -> bool:
        return self._store is not None

    @property
    def delivery_configured(self) -> bool:
        # No external transport exists in this task.
        return False

    def ingest(
        self, candidates, *, now: datetime | None = None
    ) -> tuple[AlertIngestResult, ...]:
        """Deduplicate/cooldown-aware ingestion.  No-op unless enabled+configured."""

        if not self._enabled:
            return (AlertIngestResult(decision="DISABLED", reason_code=ALERT_DISABLED),)
        if self._store is None:
            return (AlertIngestResult(decision="DISABLED", reason_code=ALERT_NOT_CONFIGURED),)
        results: list[AlertIngestResult] = []
        for candidate in candidates:
            try:
                results.append(self._store.ingest(candidate, now=now))
            except AlertStoreError as exc:
                results.append(AlertIngestResult(decision="INVALID", reason_code=exc.code))
        return tuple(results)

    def list(
        self, *, limit: int = 20, cursor: str | None = None, status: str | None = None
    ) -> AlertPage:
        if self._store is None:
            return AlertPage(alerts=(), partial_result=True)
        try:
            return self._store.list(limit=min(limit, self._max_page), cursor=cursor, status=status)
        except AlertStoreError:
            return AlertPage(alerts=(), partial_result=True)

    def get(self, alert_id: str) -> AlertRecord | None:
        if self._store is None:
            return None
        try:
            return self._store.get(alert_id)
        except AlertStoreError:
            return None

    def pending_count(self) -> int:
        """Bounded count of open (undelivered) alerts; 0 when unconfigured."""

        if self._store is None:
            return 0
        try:
            return min(self._store.count(status="OPEN"), 100000)
        except AlertStoreError:
            return 0


__all__ = [
    "ALERT_DISABLED",
    "ALERT_NOT_CONFIGURED",
    "MonitoringAlertService",
]
