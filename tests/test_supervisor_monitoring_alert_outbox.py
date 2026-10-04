"""Supervisor alert outbox tests: deterministic identity, dedup, cooldown,
recovery, corruption isolation, bounded pagination and no delivery.

Temporary paths only.  No external notification, no Production outbox and no
trading mutation.
"""
from __future__ import annotations

import inspect
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.supervisor import monitoring_alert_store as store_module
from backend.supervisor.monitoring_alert_models import AlertCandidate
from backend.supervisor.monitoring_alert_service import MonitoringAlertService
from backend.supervisor.monitoring_alert_store import (
    MonitoringAlertStore,
    deterministic_alert_id,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def candidate(**overrides):
    payload = dict(
        anomaly_fingerprint="F" + "a" * 20,
        severity="WARNING",
        category="STATISTICAL_DRIFT",
        metric="entry_candidate_rate",
        occurred_at=NOW,
    )
    payload.update(overrides)
    return AlertCandidate(**payload)


def make_store(tmp_path):
    store = MonitoringAlertStore(tmp_path / "alerts.sqlite3")
    store.initialize()
    return store


def test_deterministic_id():
    first = deterministic_alert_id(candidate())
    second = deterministic_alert_id(candidate())
    assert first == second
    assert first.startswith("A")
    assert len(first) == 32
    assert deterministic_alert_id(candidate(severity="CRITICAL")) == first


def test_create_and_deduplicate(tmp_path):
    store = make_store(tmp_path)
    created = store.ingest(candidate(), now=NOW)
    assert created.decision == "CREATED"
    assert store.count() == 1
    repeated = store.ingest(candidate(), now=NOW)
    assert repeated.decision == "SUPPRESSED_COOLDOWN"
    assert store.count() == 1


def test_cooldown_suppresses_then_advances(tmp_path):
    store = make_store(tmp_path)
    store.ingest(candidate(severity="WARNING"), now=NOW)
    suppressed = store.ingest(candidate(severity="WARNING"), now=NOW + timedelta(minutes=5))
    assert suppressed.decision == "SUPPRESSED_COOLDOWN"
    after = store.ingest(candidate(severity="WARNING"), now=NOW + timedelta(hours=2))
    assert after.decision == "UPDATED"
    record = store.get(after.alert_id)
    assert record.occurrence_count == 2


def test_escalation_bypasses_cooldown(tmp_path):
    store = make_store(tmp_path)
    store.ingest(candidate(severity="WARNING"), now=NOW)
    escalated = store.ingest(candidate(severity="CRITICAL"), now=NOW + timedelta(minutes=1))
    assert escalated.decision == "UPDATED"
    assert store.get(escalated.alert_id).highest_severity == "CRITICAL"


def test_acknowledgement_suppresses_repeat(tmp_path):
    store = make_store(tmp_path)
    created = store.ingest(candidate(), now=NOW)
    assert store.acknowledge(created.alert_id, now=NOW) is True
    suppressed = store.ingest(candidate(), now=NOW + timedelta(hours=2))
    assert suppressed.decision == "SUPPRESSED_ACKNOWLEDGED"
    assert store.get(created.alert_id).status == "ACKNOWLEDGED"


def test_delivery_status_never_delivered(tmp_path):
    store = make_store(tmp_path)
    store.ingest(candidate(), now=NOW)
    record = store.list(limit=5).alerts[0]
    assert record.delivery_status in ("PENDING", "NOT_CONFIGURED")
    service = MonitoringAlertService(store=store, enabled=True)
    assert service.delivery_configured is False


def test_disabled_service_does_not_write(tmp_path):
    store = make_store(tmp_path)
    service = MonitoringAlertService(store=store, enabled=False)
    result = service.ingest([candidate()], now=NOW)[0]
    assert result.decision == "DISABLED"
    assert store.count() == 0


def test_restart_recovery(tmp_path):
    first = make_store(tmp_path)
    first.ingest(candidate(), now=NOW)
    second = MonitoringAlertStore(tmp_path / "alerts.sqlite3")
    second.initialize()
    assert second.count() == 1
    recovered = second.recover()
    assert len(recovered.alerts) == 1


def test_corruption_isolation(tmp_path):
    store = make_store(tmp_path)
    store.ingest(candidate(), now=NOW)
    with sqlite3.connect(store.path) as db:
        db.execute(
            "INSERT INTO alert_records(alert_id, anomaly_fingerprint, episode_number, status, "
            "current_severity, first_seen_at, last_seen_at, payload) VALUES(?,?,?,?,?,?,?,?)",
            ("Abad", "Fbad", 1, "OPEN", "WARNING",
             NOW.isoformat(), (NOW + timedelta(seconds=1)).isoformat(), "{broken"),
        )
    page = store.list(limit=10)
    assert page.corruption_count >= 1
    assert page.partial_result is True
    assert len(page.alerts) >= 1


def test_bounded_pagination(tmp_path):
    store = make_store(tmp_path)
    for index in range(5):
        store.ingest(
            candidate(anomaly_fingerprint="F" + f"{index:020d}", occurred_at=NOW),
            now=NOW + timedelta(seconds=index),
        )
    first = store.list(limit=2)
    assert len(first.alerts) == 2
    assert first.next_cursor is not None
    second = store.list(limit=2, cursor=first.next_cursor)
    assert len(second.alerts) == 2
    ids = {a.alert_id for a in first.alerts} & {a.alert_id for a in second.alerts}
    assert ids == set()


def test_secret_like_candidate_rejected():
    with pytest.raises(ValidationError):
        candidate(category="API_KEY_LEAK")


def test_invalid_limit_rejected(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(Exception):
        store.list(limit=0)


def test_no_external_delivery_source():
    source = inspect.getsource(store_module)
    for token in ("requests", "smtplib", "slack", "webhook", "urllib", "http.client"):
        assert token not in source


def test_no_production_path():
    source = inspect.getsource(store_module)
    assert "logs/runtime" not in source
