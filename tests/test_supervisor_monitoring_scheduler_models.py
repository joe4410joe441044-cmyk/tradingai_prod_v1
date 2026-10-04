"""Phase 3A config, feature-flag, run and overlap model tests (synthetic only)."""
from datetime import datetime, timedelta, timezone
import inspect
import pytest
from pydantic import ValidationError

from backend.supervisor import monitoring_scheduler_models as models
from backend.supervisor.monitoring_scheduler_models import (
    MonitoringRun, SchedulerConfig, decide_overlap, resolve_feature_flag_status,
)

NOW = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)


def ts(minutes=0):
    return NOW + timedelta(minutes=minutes)


def run(**over):
    data = dict(
        run_id="run-1", trigger_type="SCHEDULED", requested_at=NOW, started_at=NOW,
        completed_at=NOW, status="SUCCESS", timeout_seconds=10.0, duration_ms=0,
        observation_count=1, evaluation_count=1, anomaly_count=0, state_event_count=0,
    )
    data.update(over)
    return MonitoringRun(**data)


# --- Config (1-10) ---------------------------------------------------------

def test_config_default_disabled():
    config = SchedulerConfig()
    assert config.enabled is False
    assert config.persistence_requested is False


def test_config_valid_enabled_requires_path():
    config = SchedulerConfig(enabled=True, state_journal_path="logs/runtime/sched.jsonl")
    assert config.enabled is True
    assert config.state_journal_path.endswith("sched.jsonl")


@pytest.mark.parametrize("value", [1.0, 14.99, 3600.01, 99999.0])
def test_config_invalid_interval(value):
    with pytest.raises(ValidationError):
        SchedulerConfig(interval_seconds=value)


@pytest.mark.parametrize("value", [0.0, -1.0, 61.0])
def test_config_invalid_run_timeout(value):
    with pytest.raises(ValidationError):
        SchedulerConfig(run_timeout_seconds=value)


def test_config_source_timeout_must_be_less_than_run_timeout():
    with pytest.raises(ValidationError):
        SchedulerConfig(run_timeout_seconds=5.0, source_timeout_seconds=5.0)


def test_config_excessive_query_budget():
    with pytest.raises(ValidationError):
        SchedulerConfig(query_budget=801)
    with pytest.raises(ValidationError):
        SchedulerConfig(max_pages=1, max_page_items=10, query_budget=800)


@pytest.mark.parametrize("field", ["recovery_max_records", "recovery_max_bytes"])
def test_config_invalid_recovery_bounds(field):
    with pytest.raises(ValidationError):
        SchedulerConfig(**{field: 0})


def test_config_path_requirement():
    with pytest.raises(ValidationError):
        SchedulerConfig(enabled=True)
    with pytest.raises(ValidationError):
        SchedulerConfig(persistence_requested=True)


def test_config_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        SchedulerConfig(unknown_field=1)


def test_config_deterministic_serialization():
    a = SchedulerConfig(interval_seconds=30.0)
    b = SchedulerConfig(interval_seconds=30.0)
    assert a.stable_json() == b.stable_json()
    assert a.canonical_digest() == b.canonical_digest()
    assert a.model_config["frozen"] is True


def test_config_no_environment_access():
    source = inspect.getsource(models)
    assert "os.environ" not in source
    assert "getenv" not in source
    assert "import os" not in source


# --- Feature flag (Step 11) ------------------------------------------------

def test_flag_absent_is_disabled():
    status = resolve_feature_flag_status(None)
    assert status.enabled is False and status.source == "DEFAULT_OFF"
    assert status.raw_value_present is False and status.valid is True
    assert status.reason_code == "FLAG_OFF"
    assert resolve_feature_flag_status("").source == "DEFAULT_OFF"


def test_flag_truthy_enabled():
    for raw in ("1", "true", "YES", "on", " On "):
        status = resolve_feature_flag_status(raw)
        assert status.enabled is True and status.source == "ENV" and status.valid is True


def test_flag_falsy_disabled():
    for raw in ("0", "false", "no", "off"):
        status = resolve_feature_flag_status(raw)
        assert status.enabled is False and status.source == "ENV"
        assert status.reason_code == "FLAG_OFF"


def test_flag_invalid_fails_closed():
    status = resolve_feature_flag_status("maybe")
    assert status.enabled is False and status.source == "INVALID"
    assert status.valid is False and status.reason_code == "FLAG_INVALID"


def test_flag_no_environment_read():
    source = inspect.getsource(models.resolve_feature_flag_status)
    assert "os.environ" not in source and "getenv" not in source


# --- Runs (38-47) ----------------------------------------------------------

def test_run_scheduled_success():
    item = run()
    assert item.status == "SUCCESS" and item.trigger_type == "SCHEDULED"


def test_run_manual_success():
    assert run(trigger_type="MANUAL").trigger_type == "MANUAL"


def test_run_partial():
    item = run(status="PARTIAL", partial_result=True)
    assert item.partial_result is True


def test_run_timeout_requires_error():
    item = run(status="TIMED_OUT", error_code="RUN_TIMEOUT")
    assert item.status == "TIMED_OUT"
    with pytest.raises(ValidationError):
        run(status="TIMED_OUT")


def test_run_cancelled():
    assert run(status="CANCELLED", error_code="RUN_CANCELLED").status == "CANCELLED"
    with pytest.raises(ValidationError):
        run(status="CANCELLED")


def test_run_failed():
    assert run(status="FAILED", error_code="RUN_FAILED").status == "FAILED"
    with pytest.raises(ValidationError):
        run(status="FAILED")


def test_run_skipped_overlap():
    item = run(status="SKIPPED_OVERLAP", started_at=None, completed_at=NOW, duration_ms=None)
    assert item.status == "SKIPPED_OVERLAP" and item.started_at is None


def test_run_invalid_timestamp_order():
    with pytest.raises(ValidationError):
        run(started_at=ts(5), completed_at=ts(1))


def test_run_count_validation():
    with pytest.raises(ValidationError):
        run(observation_count=1, evaluation_count=2)
    with pytest.raises(ValidationError):
        run(observation_count=2, evaluation_count=2, anomaly_count=3)


def test_run_duration_consistency():
    with pytest.raises(ValidationError):
        run(started_at=NOW, completed_at=ts(1), duration_ms=999)


def test_run_rejects_secret_and_raw_evidence():
    with pytest.raises(ValidationError):
        run(warnings=("API_KEY_LEAK",))
    with pytest.raises(ValidationError):
        run(status="FAILED", error_code="X", error_summary="Traceback (most recent call last)")


def test_run_deterministic_serialization():
    assert run().stable_json() == run().stable_json()


# --- Overlap (62-69) -------------------------------------------------------

def test_overlap_scheduled_during_scheduled():
    result = decide_overlap(
        scheduler_state="RUNNING", trigger_type="SCHEDULED", request_id="req-s",
        active_run_id="run-1",
    )
    assert result.decision == "REJECT_OVERLAP" and result.reason_code == "ACTIVE_RUN_IN_PROGRESS"


def test_overlap_manual_during_scheduled():
    result = decide_overlap(
        scheduler_state="RUNNING", trigger_type="MANUAL", request_id="req-m",
        active_run_id="run-1",
    )
    assert result.decision == "REJECT_OVERLAP"


def test_overlap_manual_during_manual():
    result = decide_overlap(
        scheduler_state="RUNNING", trigger_type="MANUAL", request_id="req-2",
        active_run_id="run-1",
    )
    assert result.decision == "REJECT_OVERLAP"


def test_overlap_replay_existing_request():
    result = decide_overlap(
        scheduler_state="RUNNING", trigger_type="MANUAL", request_id="run-1",
        active_run_id="run-1",
    )
    assert result.decision == "REPLAY_EXISTING" and result.reason_code == "IDEMPOTENT_REPLAY"


def test_overlap_disabled_decision():
    assert decide_overlap(
        scheduler_state="DISABLED", trigger_type="MANUAL", request_id="r"
    ).decision == "DISABLED"
    assert decide_overlap(
        scheduler_state="STOPPED", trigger_type="MANUAL", request_id="r"
    ).reason_code == "SCHEDULER_STOPPED"


def test_overlap_invalid_replay_reference():
    result = decide_overlap(
        scheduler_state="RUNNING", trigger_type="MANUAL", request_id="r",
        active_run_id="run-1", replay_of_run_id="run-other",
    )
    assert result.decision == "INVALID" and result.reason_code == "INVALID_REPLAY_REFERENCE"


def test_overlap_accept_when_idle():
    result = decide_overlap(
        scheduler_state="IDLE", trigger_type="SCHEDULED", request_id="req-1"
    )
    assert result.decision == "ACCEPT" and result.reason_code == "ACCEPTED"


def test_overlap_stable_reason_codes_and_no_lock():
    source = inspect.getsource(models.decide_overlap)
    assert "fcntl" not in source and "import os" not in source
    assert "Cross-process" in models.decide_overlap.__doc__
    assert {decide_overlap(
        scheduler_state="IDLE", trigger_type="MANUAL", request_id="r"
    ).reason_code} == {"ACCEPTED"}
