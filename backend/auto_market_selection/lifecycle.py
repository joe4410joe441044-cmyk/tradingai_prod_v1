"""Production lifecycle boundary for Paper AUTO market selection."""

from copy import deepcopy
from enum import Enum
from hashlib import sha256
import threading
from typing import Mapping


class AutoSelectionLifecycleState(str, Enum):
    STOPPED = "STOPPED"
    READY = "READY"
    RUNNING_CYCLE = "RUNNING_CYCLE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class PaperAutoSelectionLifecycle:
    """Manage an injected AMS-4B single-cycle runtime without scheduling it."""

    def __init__(self, bot_manager, e2e_runtime, *, readiness_provider):
        if not callable(getattr(e2e_runtime, "run", None)):
            raise TypeError("PaperAutoSelectionE2E required")
        if not callable(readiness_provider):
            raise TypeError("AUTO lifecycle readiness provider required")
        self.manager = bot_manager
        self.e2e_runtime = e2e_runtime
        self.readiness_provider = readiness_provider
        self._state = AutoSelectionLifecycleState.STOPPED
        self._enabled = False
        self._cycle_lock = threading.Lock()
        self._current_cycle_id = None
        self._last_result = None
        self._reason_codes = ()

    def start(self):
        if self._state is AutoSelectionLifecycleState.RUNNING_CYCLE:
            return self.get_status()
        reason = self._safety_reason()
        if reason is None:
            readiness = self.readiness_provider()
            reason = self._readiness_reason(readiness)
        if reason:
            self._enabled = False
            self._state = AutoSelectionLifecycleState.BLOCKED
            self._reason_codes = (reason,)
            return self.get_status()
        self._enabled = True
        self._state = AutoSelectionLifecycleState.READY
        self._reason_codes = ()
        return self.get_status()

    def stop(self):
        # Never interrupt a SafeSwitch transaction. A running call observes
        # this flag only after its existing E2E transaction has finalized.
        self._enabled = False
        if self._state is not AutoSelectionLifecycleState.RUNNING_CYCLE:
            self._state = AutoSelectionLifecycleState.STOPPED
            self._current_cycle_id = None
        return self.get_status()

    def run_one_cycle(self, *, started_at=None):
        if self._state is AutoSelectionLifecycleState.RUNNING_CYCLE:
            self._reason_codes = ("AUTO_SELECTION_ALREADY_IN_PROGRESS",)
            return {"accepted": False, "reasonCodes": list(self._reason_codes),
                    "runtime": self.get_status(), "result": None}
        if not self._enabled or self._state is not AutoSelectionLifecycleState.READY:
            self._reason_codes = ("AUTO_RUNTIME_NOT_READY",)
            return {"accepted": False, "reasonCodes": list(self._reason_codes),
                    "runtime": self.get_status(), "result": None}
        if not self._cycle_lock.acquire(blocking=False):
            self._reason_codes = ("AUTO_SELECTION_ALREADY_IN_PROGRESS",)
            return {"accepted": False, "reasonCodes": list(self._reason_codes),
                    "runtime": self.get_status(), "result": None}
        try:
            self._state = AutoSelectionLifecycleState.RUNNING_CYCLE
            trigger_source = started_at
            if trigger_source is None:
                clock = getattr(self.e2e_runtime, "clock", None)
                trigger_source = clock() if callable(clock) else "CURRENT"
            self._current_cycle_id = "ams-4c-" + sha256(
                str(trigger_source).encode("utf-8")
            ).hexdigest()[:20]
            result = self.e2e_runtime.run(started_at=started_at)
            self._last_result = result
            self._current_cycle_id = None
            failed = getattr(getattr(result, "status", None), "value", None) == "FAILED"
            self._reason_codes = tuple(getattr(result, "reason_codes", ()))
            if not self._enabled:
                self._state = AutoSelectionLifecycleState.STOPPED
            elif failed:
                self._state = AutoSelectionLifecycleState.FAILED
                self._enabled = False
            else:
                self._state = AutoSelectionLifecycleState.READY
            return {"accepted": True, "reasonCodes": list(self._reason_codes),
                    "runtime": self.get_status(), "result": result.to_dict()}
        except Exception:
            self._last_result = None
            self._current_cycle_id = None
            self._reason_codes = ("AUTO_RUNTIME_CYCLE_FAILED",)
            self._state = AutoSelectionLifecycleState.FAILED
            self._enabled = False
            return {"accepted": True, "reasonCodes": list(self._reason_codes),
                    "runtime": self.get_status(), "result": None}
        finally:
            self._cycle_lock.release()

    def get_status(self):
        last = self._last_result.to_dict() if self._last_result is not None else {}
        observation = getattr(self.manager, "auto_market_selection_observation", None)
        observation = observation if isinstance(observation, Mapping) else {}
        cycle = observation.get("autoSelectionCycle")
        cycle = cycle if isinstance(cycle, Mapping) else {}
        switch = observation.get("switchResult")
        switch = switch if isinstance(switch, Mapping) else {}
        scanner = observation.get("scannerResult")
        scanner = scanner if isinstance(scanner, Mapping) else {}
        ranking = observation.get("rankingResult")
        ranking = ranking if isinstance(ranking, Mapping) else {}
        proposal = observation.get("selectionProposal")
        proposal = proposal if isinstance(proposal, Mapping) else {}
        active = getattr(self.manager, "activeSymbol", None)
        enabled = self._enabled or self._state is AutoSelectionLifecycleState.RUNNING_CYCLE
        committed = switch.get("committedSymbol")
        locked = bool(switch.get("success") is True and committed and active == committed)
        initial_committed = (
            "previousSymbol" in switch
            and switch.get("previousSymbol") is None
            and switch.get("committedSymbol") is not None
        )
        selection_mode = (
            "INITIAL_SELECTION" if enabled and (active is None or initial_committed)
            else "SYMBOL_SWITCH" if enabled
            else "MANUAL"
        )
        cycle_state = (
            "EVALUATING" if self._state is AutoSelectionLifecycleState.RUNNING_CYCLE
            else "WAITING_SELECTION" if enabled and active is None
            else last.get("status")
        )
        top = ranking.get("topCandidate")
        top = top if isinstance(top, Mapping) else {}
        last_updated = (switch.get("completedAt") or cycle.get("evaluatedAt")
                        or last.get("completedAt"))
        return {
            "attached": True,
            "running": enabled,
            "runtimeState": self._state.value,
            "cycleState": cycle_state,
            "selectionMode": selection_mode,
            "selectionCycleId": cycle.get("autoSelectionCycleId"),
            "universeCount": scanner.get("universeCount"),
            "evaluatedCount": scanner.get("evaluatedCount"),
            "eligibleCount": scanner.get("eligibleCount"),
            "rejectedCount": scanner.get("rejectedCount"),
            "topScore": top.get("rankingScore"),
            "previousSymbol": switch.get("previousSymbol", proposal.get("currentActiveSymbol")),
            "requestedSymbol": proposal.get("proposedSymbol"),
            "proposedSymbol": proposal.get("proposedSymbol"),
            "committedSymbol": committed,
            "safeSwitchState": switch.get("state") or "IDLE",
            "lockOnState": "LOCKED" if locked else "UNLOCKED",
            "lockedSymbol": committed if locked else None,
            "lockedAt": switch.get("committedAt") if locked else None,
            "lastReason": self._reason_codes[0] if self._reason_codes else None,
            "lastUpdatedAt": last_updated,
            "amsMode": "AUTO_PAPER" if self._enabled or self._state is AutoSelectionLifecycleState.RUNNING_CYCLE else "MANUAL",
            "amsRuntimeState": self._state.value,
            "currentCycleId": self._current_cycle_id,
            "lastCycleId": last.get("e2eCycleId"),
            "lastCycleStatus": last.get("status"),
            "lastEvaluatedAt": last.get("completedAt"),
            "activeSymbol": active,
            "topCandidate": cycle.get("topCandidateSymbol"),
            "switchState": switch.get("state") or "IDLE",
            "reasonCodes": list(self._reason_codes),
            "enabled": self._enabled,
            "readOnly": True,
        }

    def _safety_reason(self):
        config = getattr(self.manager, "config", None)
        if not isinstance(config, Mapping):
            return "AUTO_RUNTIME_MODE_UNAVAILABLE"
        mode = str(config.get("mode", config.get("tradeMode", "paper"))).lower()
        if mode != "paper":
            return "AUTO_RUNTIME_LIVE_BLOCKED"
        if config.get("dryRun", config.get("dry_run", True)) is not True:
            return "AUTO_RUNTIME_DRY_RUN_REQUIRED"
        if config.get("realOrderAllowed", config.get("real_order_allowed", False)) is not False:
            return "AUTO_RUNTIME_REAL_ORDER_FORBIDDEN"
        return None

    @staticmethod
    def _readiness_reason(value):
        if not isinstance(value, Mapping):
            return "AUTO_RUNTIME_DEPENDENCIES_UNAVAILABLE"
        required = (
            ("dependenciesAvailable", "AUTO_RUNTIME_DEPENDENCIES_UNAVAILABLE"),
            ("mmAvailable", "AUTO_RUNTIME_MM_UNAVAILABLE"),
            ("emergencySafe", "AUTO_RUNTIME_EMERGENCY_UNSAFE"),
        )
        optional = (
            ("positionFlat", "AUTO_RUNTIME_POSITION_NOT_FLAT"),
            ("pendingKnown", "AUTO_RUNTIME_PENDING_UNKNOWN"),
            ("pendingClear", "AUTO_RUNTIME_PENDING_EXISTS"),
            ("pendingSafe", "AUTO_RUNTIME_PENDING_UNSAFE"),
        )
        for key, reason in required:
            if value.get(key) is not True:
                return reason
        for key, reason in optional:
            if key in value and value.get(key) is not True:
                return reason
        return None
