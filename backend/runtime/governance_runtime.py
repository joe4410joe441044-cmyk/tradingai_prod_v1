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

    "current_emergency_operation_id": None,

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

    not_required = (
        value.get("status") == "NOT_REQUIRED"
        or value.get("not_required") is True
    )
    success = value.get("success") is True

    return {
        "status": (
            "NOT_REQUIRED"
            if not_required and success
            else "COMPLETED"
            if success
            else "FAILED"
        ),
        "success": success,
        "completed": success or not_required,
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

    not_required = (
        value.get("status") == "NOT_REQUIRED"
        or value.get("not_required") is True
    )
    success = value.get("success") is True
    closed = (
        value.get("closed") is True
        or value.get("skipped") is True
        or value.get("position_closed") is True
        or not_required
        or value.get("flattened") == 1
    )

    return {
        "status": (
            "NOT_REQUIRED"
            if not_required and success
            else "COMPLETED"
            if success
            else "FAILED"
        ),
        "success": success,
        "completed": success or not_required,
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
    governance_state["current_emergency_operation_id"] = operation_id
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
    governance_state["current_emergency_operation_id"] = operation_id
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
        "returnWarnings": governance_state.get(
            "emergency_return_warnings",
            [],
        ),
    }


def emergency_pending_order_block_reason(pending_order):
    if isinstance(pending_order, dict):
        if (
            pending_order.get("safe") is True
            and pending_order.get("pending_order") is False
        ):
            return None

        return (
            pending_order.get("reason")
            or "PENDING_ORDER_UNKNOWN"
        )

    if type(pending_order) is not bool:
        return "PENDING_ORDER_UNKNOWN"

    if pending_order is not False:
        return "PENDING_ORDER_REMAINING"

    return None


def emergency_unlock_block_reason(pending_order):
    state = governance_state.get(
        "emergency_state",
        EMERGENCY_READY,
    )
    emergency_locked = bool(
        governance_state.get("emergency_stop", False)
    )

    if state == EMERGENCY_PROCESSING:
        return "PROCESSING"

    if state == EMERGENCY_ACTION_REQUIRED:
        return "ACTION_REQUIRED"

    if state != EMERGENCY_LOCKED or not emergency_locked:
        return "NOT_LOCKED"

    if governance_state.get("execution_enabled", False) is not False:
        return "EXECUTION_ENABLED"

    last_result = governance_state.get("last_emergency_result")

    if last_result is None:
        return "LAST_RESULT_MISSING"

    if not isinstance(last_result, dict):
        return "LAST_RESULT_INVALID"

    current_operation_id = governance_state.get(
        "current_emergency_operation_id"
    )

    if not current_operation_id:
        return "CURRENT_OPERATION_ID_MISSING"

    if "operationId" not in last_result:
        return "RESULT_OPERATION_ID_MISSING"

    result_operation_id = last_result.get("operationId")

    if not result_operation_id:
        return "RESULT_OPERATION_ID_MISSING"

    if result_operation_id != current_operation_id:
        return "OPERATION_ID_MISMATCH"

    if "result" not in last_result:
        return "RESULT_MISSING"

    if last_result.get("result") != EMERGENCY_RESULT_SUCCESS:
        return "RESULT_NOT_SUCCESS"

    if "success" not in last_result:
        return "SUCCESS_MISSING"

    if last_result.get("success") is not True:
        return "SUCCESS_NOT_TRUE"

    if "completed" not in last_result:
        return "COMPLETED_MISSING"

    if last_result.get("completed") is not True:
        return "COMPLETED_NOT_TRUE"

    if "stateUnknown" not in last_result:
        return "STATE_UNKNOWN_MISSING"

    if last_result.get("stateUnknown") is not False:
        return "STATE_UNKNOWN"

    if "positionRemaining" not in last_result:
        return "POSITION_REMAINING_MISSING"

    if last_result.get("positionRemaining") is not False:
        return "POSITION_REMAINING"

    pending_order_reason = emergency_pending_order_block_reason(
        pending_order
    )

    if pending_order_reason is not None:
        return pending_order_reason

    return None


def unlock_emergency_lock(pending_order=None, warnings=None):
    state = governance_state.get(
        "emergency_state",
        EMERGENCY_READY,
    )
    reason = (
        "PROCESSING"
        if state == EMERGENCY_PROCESSING
        else None
    )

    if reason is not None:
        return {
            "success": False,
            "unlocked": False,
            "reason": reason,
            "emergency": build_emergency_status(),
        }

    return_warnings = list(dict.fromkeys(warnings or []))
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
    try:
        governance_state["execution_enabled"] = False
        governance_state["emergency_stop"] = False
        governance_state["emergency_state"] = EMERGENCY_READY
        governance_state["current_emergency_operation_id"] = None
        governance_state["emergency_return_warnings"] = return_warnings
    except Exception:
        return {
            "success": False,
            "unlocked": False,
            "reason": "UNLOCK_STATE_UPDATE_FAILED",
            "emergency": build_emergency_status(),
        }

    try:
        record_emergency_timeline_event(
            event="EMERGENCY_UNLOCKED",
            state=EMERGENCY_READY,
            operation_id=operation_id,
            message="緊急状態を解除しました",
            details={
                "operationId": operation_id,
                "previousState": EMERGENCY_LOCKED,
                "warnings": return_warnings,
            },
            severity="WARNING" if return_warnings else "INFO",
            event_key=event_key,
        )
    except Exception:
        return_warnings.append("UNLOCK_LOG_WRITE_FAILED")
        governance_state["emergency_return_warnings"] = return_warnings

    return {
        "success": True,
        "unlocked": True,
        "emergency_stop": False,
        "emergency_state": EMERGENCY_READY,
        "execution_enabled": governance_state.get(
            "execution_enabled",
            False,
        ),
        "emergencyLocked": False,
        "emergencyState": EMERGENCY_READY,
        "loopEnabled": False,
        "loopState": "STOPPED",
        "autoTradeEnabled": False,
        "executionEnabled": False,
        "warnings": return_warnings,
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
