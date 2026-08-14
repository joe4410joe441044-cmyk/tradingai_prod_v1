# -*- coding: utf-8 -*-
"""Backend DTO validation for the Market Recorder proxy.

The proxy receives the upstream ``{ok, data, error}`` envelope and must never
forward raw payloads to the UI.  Every response is validated against the
fixed contract and sanitized into a clean dict; any invalid payload fails
closed with a ``RecorderProxyDTOError`` carrying a safe error code only.
"""


class RecorderProxyDTOError(Exception):
    """Raised when an upstream payload does not match the contract.

    Only the safe error code may ever be surfaced to callers.
    """

    def __init__(self, code="market_recorder_upstream_invalid_response"):
        super().__init__(code)
        self.code = code


def _fail(code="market_recorder_upstream_invalid_response"):
    raise RecorderProxyDTOError(code)


def _require_dict(value, name):
    if not isinstance(value, dict):
        _fail()
    return value


def _optional_str(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) == 0:
        _fail()
    return value


def _required_str(value):
    if not isinstance(value, str) or len(value) == 0:
        _fail()
    return value


def _optional_int(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        _fail()
    if value < 0:
        _fail()
    return value


def _optional_number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail()
    if value < 0:
        _fail()
    return value


def _optional_bool(value):
    if value is None:
        return None
    if not isinstance(value, bool):
        _fail()
    return value


def _string_list(value):
    if not isinstance(value, list):
        _fail()
    result = []
    for entry in value:
        if not isinstance(entry, str):
            _fail()
        result.append(entry)
    return result


def validate_envelope(payload):
    """Validate the common ``{ok, data, error}`` envelope."""
    _require_dict(payload, "envelope")
    if payload.get("ok") is not True:
        _fail("market_recorder_upstream_rejected")
    if "data" not in payload:
        _fail()
    return payload["data"]


def validate_control_envelope(payload):
    """Validate the Recorder Control success envelope without changing reads."""
    data = validate_envelope(payload)
    if "error" not in payload or payload["error"] is not None:
        _fail()
    return data


def validate_health_dto(data):
    _require_dict(data, "health")
    return {
        "status": _required_str(data.get("status")),
        "contract_version": _optional_str(data.get("contract_version")),
        "uptime_seconds": _optional_int(data.get("uptime_seconds")),
    }


def validate_status_dto(data):
    _require_dict(data, "status")
    return {
        "status": _required_str(data.get("status")),
        "connection_state": _optional_str(data.get("connection_state")),
        "pid": _optional_int(data.get("pid")),
        "uptime_seconds": _optional_number(data.get("uptime_seconds")),
        "subscribed_streams": _string_list(data.get("subscribed_streams")),
        "messages_received": _optional_int(data.get("messages_received")),
        "bytes_received": _optional_number(data.get("bytes_received")),
        "reconnect_count": _optional_int(data.get("reconnect_count")),
        "sequence_anomaly_count": _optional_int(data.get("sequence_anomaly_count")),
        "active_files": _string_list(data.get("active_files")),
        "last_message_at": _optional_str(data.get("last_message_at")),
        "last_error": _optional_str(data.get("last_error")),
        "process_started_at": _optional_str(data.get("process_started_at")),
        "observed_at": _optional_str(data.get("observed_at")),
    }


def validate_storage_dto(data):
    _require_dict(data, "storage")
    return {
        "filesystem": _optional_str(data.get("filesystem")),
        "total_bytes": _optional_number(data.get("total_bytes")),
        "used_bytes": _optional_number(data.get("used_bytes")),
        "free_bytes": _optional_number(data.get("free_bytes")),
        "usage_percent": _optional_number(data.get("usage_percent")),
        "archive_bytes": _optional_number(data.get("archive_bytes")),
        "active_bytes": _optional_number(data.get("active_bytes")),
        "manifest_bytes": _optional_number(data.get("manifest_bytes")),
        "quarantine_count": _optional_int(data.get("quarantine_count")),
        "runtime_bytes": _optional_number(data.get("runtime_bytes")),
        "observed_at": _optional_str(data.get("observed_at")),
    }


def validate_archive_entry_dto(entry):
    _require_dict(entry, "archive_entry")
    return {
        "id": _required_str(entry.get("id")),
        "stream": _optional_str(entry.get("stream")),
        "symbol": _optional_str(entry.get("symbol")),
        "period": _optional_str(entry.get("period")),
        "start_time": _optional_str(entry.get("start_time")),
        "end_time": _optional_str(entry.get("end_time")),
        "record_count": _optional_int(entry.get("record_count")),
        "compressed_bytes": _optional_number(entry.get("compressed_bytes")),
        "uncompressed_bytes": _optional_number(entry.get("uncompressed_bytes")),
        "verification_status": _optional_str(entry.get("verification_status")),
        "manifest_status": _optional_str(entry.get("manifest_status")),
        "downloadable": _optional_bool(entry.get("downloadable")),
        "deletion_eligible": _optional_bool(entry.get("deletion_eligible")),
    }


def validate_archives_dto(data):
    _require_dict(data, "archives")
    entries = data.get("entries")
    if not isinstance(entries, list):
        _fail()
    return {
        "entries": [validate_archive_entry_dto(entry) for entry in entries],
        "page": _optional_int(data.get("page")),
        "page_size": _optional_int(data.get("page_size")),
        "total_count": _optional_int(data.get("total_count")),
        "total_pages": _optional_int(data.get("total_pages")),
    }


def validate_control_dto(data):
    _require_dict(data, "control")
    # Support the original status-style response and the Recorder state-machine
    # response.  An empty/unrelated object is not a Control result.
    legacy = "status" in data
    state_machine = all(key in data for key in ("operation_id", "operation", "result"))
    if not legacy and not state_machine:
        _fail()

    plan = data.get("plan")
    if plan is not None and not isinstance(plan, (str, dict)):
        _fail()
    if isinstance(plan, str) and not plan:
        _fail()
    if isinstance(plan, dict):
        for key, value in plan.items():
            if not isinstance(key, str) or not key:
                _fail()
            if value is not None and not isinstance(value, (str, int, float, bool, dict, list)):
                _fail()

    result = {
        "status": _optional_str(data.get("status")),
        "operation_id": _optional_str(data.get("operation_id")),
        "operation": _optional_str(data.get("operation")),
        "result": _optional_str(data.get("result")),
        "previous_state": _optional_str(data.get("previous_state")),
        "current_state": _optional_str(data.get("current_state")),
        "requested_at": _optional_str(data.get("requested_at")),
        "completed_at": _optional_str(data.get("completed_at")),
        "plan": plan,
        "event_count": _optional_int(data.get("event_count")),
        "message": _optional_str(data.get("message")),
    }
    return result


VALIDATORS = {
    "health": validate_health_dto,
    "status": validate_status_dto,
    "storage": validate_storage_dto,
    "archives": validate_archives_dto,
    "start": validate_control_dto,
    "stop": validate_control_dto,
}
