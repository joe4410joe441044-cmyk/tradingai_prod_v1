# backend/runtime/governance_runtime.py

from datetime import datetime, timezone
import time
import uuid

# ============================================================
# GOVERNANCE RUNTIME STATE
# ============================================================

governance_state = {

    "execution_enabled": False,

    "mode": "PAPER",

    "risk_profile": "SAFE",

    "emergency_stop": False,

    "authority": "BACKEND",

    "router_state": "OBSERVING",

    "session_state": "ACTIVE",

    "no_trade_zone": False,

    "survivability": "STABLE",

    "emergency_state": "READY",

    "last_emergency_result": None,

    "emergency_timeline": [],

}


EMERGENCY_READY = "READY"
EMERGENCY_PROCESSING = "PROCESSING"
EMERGENCY_LOCKED = "LOCKED"
EMERGENCY_ACTION_REQUIRED = "ACTION_REQUIRED"

EMERGENCY_RESULT_NONE = "NONE"
EMERGENCY_RESULT_SUCCESS = "SUCCESS"
EMERGENCY_RESULT_PARTIAL = "PARTIAL"
EMERGENCY_RESULT_FAILED = "FAILED"

EMERGENCY_TIMELINE_LIMIT = 120


def utc_now_iso():
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def create_emergency_operation_id():
    timestamp = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )
    suffix = uuid.uuid4().hex[:6]

    return f"emg_{timestamp}_{suffix}"


def classify_emergency_result(result):
    if not isinstance(result, dict):
        return EMERGENCY_RESULT_FAILED

    if (
        result.get("partial") is True
        or result.get("position_remaining") is True
        or result.get("state_unknown") is True
    ):
        return EMERGENCY_RESULT_PARTIAL

    if (
        result.get("success") is True
        and result.get("completed") is True
        and result.get("partial") is not True
        and result.get("position_remaining") is not True
        and result.get("state_unknown") is not True
    ):
        return EMERGENCY_RESULT_SUCCESS

    return EMERGENCY_RESULT_FAILED


def emergency_state_for_result(result_classification):
    if result_classification == EMERGENCY_RESULT_SUCCESS:
        return EMERGENCY_LOCKED

    if result_classification in {
        EMERGENCY_RESULT_PARTIAL,
        EMERGENCY_RESULT_FAILED,
    }:
        return EMERGENCY_ACTION_REQUIRED

    return EMERGENCY_PROCESSING


def _reason_from_result(value):
    if not isinstance(value, dict):
        return None

    return (
        value.get("error_code")
        or value.get("error")
        or value.get("reason")
    )


def summarize_cancel_result(value):
    if value is None:
        return None

    if not isinstance(value, dict):
        return {
            "status": "UNKNOWN",
            "success": False,
            "completed": False,
            "reason": "MALFORMED_CANCEL_RESULT",
            "orders_cancelled": None,
            "position_remaining": None,
        }

    success = value.get("success") is True

    return {
        "status": "COMPLETED" if success else "FAILED",
        "success": success,
        "completed": success,
        "reason": _reason_from_result(value),
        "orders_cancelled": value.get("cancelled"),
        "position_remaining": value.get("position_remaining"),
    }


def summarize_flatten_result(value, position_remaining=None, state_unknown=None):
    if value is None:
        return None

    if not isinstance(value, dict):
        return {
            "status": "UNKNOWN",
            "success": False,
            "completed": False,
            "reason": "MALFORMED_FLATTEN_RESULT",
            "position_closed": False,
            "position_remaining": position_remaining,
            "state_unknown": state_unknown,
        }

    success = value.get("success") is True
    closed = (
        value.get("closed") is True
        or value.get("skipped") is True
        or value.get("flattened") == 1
    )

    return {
        "status": "COMPLETED" if success else "FAILED",
        "success": success,
        "completed": success,
        "reason": _reason_from_result(value),
        "position_closed": bool(success and closed),
        "position_remaining": position_remaining,
        "state_unknown": state_unknown,
    }


def emergency_message(result, result_classification):
    if not isinstance(result, dict):
        return "Emergency result was not available."

    error_code = result.get("error_code")

    if result_classification == EMERGENCY_RESULT_SUCCESS:
        return "Emergency completed."

    if result_classification == EMERGENCY_RESULT_PARTIAL:
        if error_code:
            return f"Emergency requires operator action: {error_code}"
        return "Emergency requires operator action."

    if error_code:
        return f"Emergency failed: {error_code}"

    return "Emergency failed."


def _emergency_timeline_events():
    events = governance_state.get("emergency_timeline")

    if not isinstance(events, list):
        events = []
        governance_state["emergency_timeline"] = events

    return events


def _emergency_timeline_label(event):
    labels = {
        "EMERGENCY_STARTED": "EMERGENCY STARTED",
        "EMERGENCY_COMPLETED": "EMERGENCY STOPPED SAFELY",
        "EMERGENCY_ACTION_REQUIRED": "ACTION REQUIRED",
        "EMERGENCY_UNLOCKED": "EMERGENCY UNLOCKED",
    }

    return labels.get(event, event)


def record_emergency_timeline_event(
    *,
    event,
    state,
    result=None,
    operation_id=None,
    path=None,
    message=None,
    details=None,
    severity="INFO",
    event_key=None,
):
    events = _emergency_timeline_events()

    if event_key and any(
        item.get("eventKey") == event_key
        for item in events
        if isinstance(item, dict)
    ):
        return None

    now = datetime.now(timezone.utc)
    timestamp = (
        now
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    label = _emergency_timeline_label(event)
    timeline_event = {
        "timestamp": timestamp,
        "timestampEpoch": time.time(),
        "source": "Emergency",
        "type": "EMERGENCY",
        "event": event,
        "eventKey": event_key,
        "stageId": "emergency",
        "state": state,
        "label": label,
        "reason": message or label,
        "message": message or label,
        "level": severity,
        "severity": severity,
        "details": details if isinstance(details, dict) else {},
    }

    if operation_id is not None:
        timeline_event["operationId"] = operation_id

    if result is not None:
        timeline_event["result"] = result

    if path is not None:
        timeline_event["path"] = path

    events.append(timeline_event)

    if len(events) > EMERGENCY_TIMELINE_LIMIT:
        governance_state["emergency_timeline"] = (
            events[-EMERGENCY_TIMELINE_LIMIT:]
        )

    return timeline_event


def begin_emergency_operation():
    started_at = utc_now_iso()
    operation_id = create_emergency_operation_id()

    last_result = {
        "operationId": operation_id,
        "state": EMERGENCY_PROCESSING,
        "result": EMERGENCY_RESULT_NONE,
        "startedAt": started_at,
        "completedAt": None,
        "path": None,
        "success": False,
        "completed": False,
        "partial": False,
        "retryable": True,
        "positionRemaining": None,
        "stateUnknown": False,
        "cancelResult": None,
        "flattenResult": None,
        "message": "Emergency processing.",
    }

    governance_state["emergency_stop"] = True
    governance_state["execution_enabled"] = False
    governance_state["emergency_state"] = EMERGENCY_PROCESSING
    governance_state["last_emergency_result"] = last_result
    record_emergency_timeline_event(
        event="EMERGENCY_STARTED",
        state=EMERGENCY_PROCESSING,
        result=EMERGENCY_RESULT_NONE,
        operation_id=operation_id,
        message="緊急停止処理を開始しました",
        severity="WARN",
        event_key=f"{operation_id}:EMERGENCY_STARTED",
    )

    return {
        "operation_id": operation_id,
        "started_at": started_at,
    }


def complete_emergency_operation(result, operation=None):
    operation = operation or {}
    current_result = governance_state.get("last_emergency_result")

    operation_id = (
        operation.get("operation_id")
        or (
            current_result.get("operationId")
            if isinstance(current_result, dict)
            else None
        )
        or create_emergency_operation_id()
    )
    started_at = (
        operation.get("started_at")
        or (
            current_result.get("startedAt")
            if isinstance(current_result, dict)
            else None
        )
        or utc_now_iso()
    )

    result = result if isinstance(result, dict) else {}
    result_classification = classify_emergency_result(result)
    state = emergency_state_for_result(result_classification)
    position_remaining = result.get("position_remaining")
    state_unknown = result.get("state_unknown")

    last_result = {
        "operationId": operation_id,
        "state": state,
        "result": result_classification,
        "startedAt": started_at,
        "completedAt": utc_now_iso(),
        "path": result.get("execution_path") or result.get("path"),
        "success": result.get("success") is True,
        "completed": result.get("completed") is True,
        "partial": result.get("partial") is True,
        "retryable": result.get("retryable") is True,
        "positionRemaining": position_remaining,
        "stateUnknown": state_unknown is True,
        "cancelResult": summarize_cancel_result(
            result.get("cancel")
        ),
        "flattenResult": summarize_flatten_result(
            result.get("flatten"),
            position_remaining=position_remaining,
            state_unknown=state_unknown,
        ),
        "message": emergency_message(
            result,
            result_classification,
        ),
    }

    governance_state["emergency_state"] = state
    governance_state["last_emergency_result"] = last_result
    completion_event = (
        "EMERGENCY_COMPLETED"
        if state == EMERGENCY_LOCKED
        else "EMERGENCY_ACTION_REQUIRED"
    )
    completion_message = (
        "緊急停止が正常に完了しました"
        if state == EMERGENCY_LOCKED
        else "緊急停止結果の手動確認が必要です"
    )
    record_emergency_timeline_event(
        event=completion_event,
        state=state,
        result=result_classification,
        operation_id=operation_id,
        path=last_result.get("path"),
        message=completion_message,
        details={
            "operationId": operation_id,
            "path": last_result.get("path"),
            "result": result_classification,
            "cancelResult": last_result.get("cancelResult"),
            "flattenResult": last_result.get("flattenResult"),
            "positionRemaining": last_result.get("positionRemaining"),
            "stateUnknown": last_result.get("stateUnknown"),
            "completedAt": last_result.get("completedAt"),
            "message": last_result.get("message"),
        },
        severity=(
            "WARN"
            if state == EMERGENCY_LOCKED
            else "ERROR"
        ),
        event_key=f"{operation_id}:EMERGENCY_COMPLETION",
    )

    return last_result


def build_emergency_status():
    emergency_locked = bool(
        governance_state.get("emergency_stop", False)
    )
    state = governance_state.get(
        "emergency_state",
        EMERGENCY_READY,
    )
    if emergency_locked and state == EMERGENCY_READY:
        state = EMERGENCY_ACTION_REQUIRED

    return {
        "active": emergency_locked or state != EMERGENCY_READY,
        "locked": emergency_locked,
        "state": state,
        "lastResult": governance_state.get("last_emergency_result"),
    }


def _last_emergency_value(*keys):
    last_result = governance_state.get("last_emergency_result")

    if not isinstance(last_result, dict):
        return None

    for key in keys:
        if key in last_result:
            return last_result.get(key)

    return None


def emergency_unlock_block_reason():
    state = governance_state.get(
        "emergency_state",
        EMERGENCY_READY,
    )
    emergency_locked = bool(
        governance_state.get("emergency_stop", False)
    )
    position_remaining = _last_emergency_value(
        "positionRemaining",
        "position_remaining",
    )
    state_unknown = _last_emergency_value(
        "stateUnknown",
        "state_unknown",
    )

    if state == EMERGENCY_PROCESSING:
        return "PROCESSING"

    if position_remaining is True:
        return "POSITION_REMAINING"

    if state_unknown is True:
        return "STATE_UNKNOWN"

    if state == EMERGENCY_ACTION_REQUIRED:
        return "ACTION_REQUIRED"

    if state != EMERGENCY_LOCKED or not emergency_locked:
        return "NOT_LOCKED"

    if governance_state.get("execution_enabled", False) is not False:
        return "EXECUTION_ENABLED"

    return None


def unlock_emergency_lock():
    reason = emergency_unlock_block_reason()

    if reason is not None:
        return {
            "success": False,
            "unlocked": False,
            "reason": reason,
            "emergency": build_emergency_status(),
        }

    governance_state["emergency_stop"] = False
    governance_state["emergency_state"] = EMERGENCY_READY
    last_result = governance_state.get("last_emergency_result")
    operation_id = (
        last_result.get("operationId")
        if isinstance(last_result, dict)
        else None
    )
    event_key = (
        f"{operation_id}:EMERGENCY_UNLOCKED"
        if operation_id
        else f"unknown:{utc_now_iso()}:EMERGENCY_UNLOCKED"
    )
    record_emergency_timeline_event(
        event="EMERGENCY_UNLOCKED",
        state=EMERGENCY_READY,
        operation_id=operation_id,
        message="緊急状態を解除しました",
        details={
            "operationId": operation_id,
            "previousState": EMERGENCY_LOCKED,
        },
        severity="INFO",
        event_key=event_key,
    )

    return {
        "success": True,
        "unlocked": True,
        "emergency_stop": False,
        "emergency_state": EMERGENCY_READY,
        "execution_enabled": governance_state.get(
            "execution_enabled",
            False,
        ),
        "emergency": build_emergency_status(),
    }
# ============================================================
# GOVERNANCE RUNTIME
# ============================================================

class GovernanceRuntime:

    def process_governance(
        self,
        strategy_state,
        ai_signal,
    ):

        if ai_signal is None:

            return {
                "allowed": False,
                "reason": "AI_SIGNAL_NONE",
                "direction": None,
            }

        if ai_signal == "HOLD":

            return {
                "allowed": False,
                "reason": "AI_HOLD",
                "direction": None,
            }

        return {
            "allowed": True,
            "reason": None,
            "direction": ai_signal,
        }
