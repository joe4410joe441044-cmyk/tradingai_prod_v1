"""Advisor read-only Supervisor-alert explanation tests.

No write, no acknowledgement, no configuration change and no trading authority.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

from backend.ai_advisor import knowledge_history_consumer as consumer_module
from backend.ai_advisor.knowledge_history_consumer import (
    ADVISOR_SUPERVISOR_ALERT_EXPLANATION_ENABLED_ENV,
    AdvisorKnowledgeHistoryConsumer,
    extract_supervisor_alert_id,
)
from backend.supervisor.monitoring_alert_models import AlertCandidate
from backend.supervisor.monitoring_alert_service import MonitoringAlertService
from backend.supervisor.monitoring_alert_store import MonitoringAlertStore

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def make_service(tmp_path, **overrides):
    store = MonitoringAlertStore(tmp_path / "alerts.sqlite3")
    store.initialize()
    service = MonitoringAlertService(store=store, enabled=True)
    candidate = AlertCandidate(
        anomaly_fingerprint="F" + "a" * 20, severity="WARNING",
        category="STATISTICAL_DRIFT", metric="entry_candidate_rate",
        provenance=("SUPERVISOR_MONITORING_JOURNAL",), freshness="FRESH",
        availability="AVAILABLE", occurred_at=NOW,
    )
    result = service.ingest([candidate], now=NOW)[0]
    if overrides.get("acknowledge"):
        service._store.acknowledge(result.alert_id, now=NOW)
    return service, result.alert_id


def test_flag_off_is_backward_compatible(tmp_path):
    service, alert_id = make_service(tmp_path)
    consumer = AdvisorKnowledgeHistoryConsumer(environ={}, alert_lookup=lambda x: None)
    assert consumer.metadata_for_message(f"explain alert {alert_id}") is None
    assert consumer.supervisor_alert_explanation_for_message(f"explain alert {alert_id}") is None


def test_enabled_returns_bounded_alert_context(tmp_path):
    service, alert_id = make_service(tmp_path)
    consumer = AdvisorKnowledgeHistoryConsumer(
        environ={ADVISOR_SUPERVISOR_ALERT_EXPLANATION_ENABLED_ENV: "1"},
        alert_lookup=lambda x: service.get(x),
    )
    metadata = consumer.metadata_for_message(f"Please explain supervisor alert {alert_id}")
    alert = metadata["supervisorAlert"]
    assert alert["found"] is True
    assert alert["read_only"] is True
    assert alert["severity"] == "WARNING"
    assert alert["metric"] == "entry_candidate_rate"
    assert alert["freshness"] == "FRESH"
    assert alert["availability"] == "AVAILABLE"
    assert alert["provenance"] == ["SUPERVISOR_MONITORING_JOURNAL"]
    # Observed evidence / baseline / drift / interpretation remain distinct.
    for key in ("observed_evidence", "baseline", "drift_result", "supervisor_interpretation"):
        assert key in alert


def test_unknown_alert_is_handled(tmp_path):
    service, _alert_id = make_service(tmp_path)
    consumer = AdvisorKnowledgeHistoryConsumer(
        environ={ADVISOR_SUPERVISOR_ALERT_EXPLANATION_ENABLED_ENV: "1"},
        alert_lookup=lambda x: service.get(x),
    )
    metadata = consumer.metadata_for_message("explain alert A" + "0" * 31)
    alert = metadata["supervisorAlert"]
    assert alert["found"] is False
    assert alert["reason"] == "ALERT_NOT_FOUND"
    assert alert["uncertainty"] == "HIGH"


def test_partial_result_is_reported_honestly(tmp_path):
    store = MonitoringAlertStore(tmp_path / "alerts.sqlite3")
    store.initialize()
    service = MonitoringAlertService(store=store, enabled=True)
    candidate = AlertCandidate(
        anomaly_fingerprint="F" + "b" * 20, severity="WARNING",
        category="MISSING_DATA", metric="evidence_missing_rate",
        partial_result=True, freshness="STALE", availability="PARTIAL", occurred_at=NOW,
    )
    alert_id = service.ingest([candidate], now=NOW)[0].alert_id
    consumer = AdvisorKnowledgeHistoryConsumer(
        environ={ADVISOR_SUPERVISOR_ALERT_EXPLANATION_ENABLED_ENV: "1"},
        alert_lookup=lambda x: service.get(x),
    )
    alert = consumer.metadata_for_message(alert_id)["supervisorAlert"]
    assert alert["partial_result"] is True
    assert alert["uncertainty"] == "MEDIUM"
    assert alert["freshness"] == "STALE"
    assert alert["availability"] == "PARTIAL"


def test_lookup_failure_is_bounded(tmp_path):
    def explode(_alert_id):
        raise RuntimeError("raw lookup failure")

    consumer = AdvisorKnowledgeHistoryConsumer(
        environ={ADVISOR_SUPERVISOR_ALERT_EXPLANATION_ENABLED_ENV: "1"},
        alert_lookup=explode,
    )
    alert = consumer.metadata_for_message("A" + "0" * 31)["supervisorAlert"]
    assert alert["found"] is False
    assert alert["reason"] == "ALERT_LOOKUP_FAILED"
    assert "raw lookup failure" not in str(alert)


def test_extract_alert_id():
    assert extract_supervisor_alert_id("A" + "a" * 31) == "A" + "a" * 31
    assert extract_supervisor_alert_id("no id here") is None
    assert extract_supervisor_alert_id(None) is None


def test_advisor_explanation_is_read_only():
    source = inspect.getsource(consumer_module)
    assert ".acknowledge(" not in source
    assert ".resolve(" not in source
    assert ".remove(" not in source
    assert ".write(" not in source
