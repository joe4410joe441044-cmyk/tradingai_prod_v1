# ============================================================
# FILE:
# backend/execution/ExecutionGovernance.py
# ============================================================

# ============================================================
# ExecutionGovernance.py
# ============================================================
#
# PURPOSE
# ------------------------------------------------------------
# Final execution authority layer.
#
# This layer decides:
#
#     "Should execution REALLY happen?"
#
# Even if strategy allows execution,
# governance may still suppress execution.
#
# ============================================================

from datetime import datetime, timedelta


class ExecutionGovernance:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self):

        # ----------------------------------------------------
        # Execution Limits
        # ----------------------------------------------------

        self.MAX_CONSECUTIVE_EXECUTIONS = 3

        self.COOLDOWN_SECONDS = 5

        self.MAX_EXPOSURE = 1.0

        self.MAX_EXECUTIONS_PER_MINUTE = 10

        # ----------------------------------------------------
        # Runtime State
        # ----------------------------------------------------

        self.execution_count = 0

        self.last_execution_time = None

        self.consecutive_executions = 0

        self.execution_timestamps = []

        self.emergency_halt = False

        self.execution_locked = False

    # ========================================================
    # EXECUTION THROTTLE
    # ========================================================

    def evaluate_execution_throttle(self):

        current_time = datetime.utcnow()

        # ----------------------------------------------------
        # Cleanup old timestamps
        # ----------------------------------------------------

        self.execution_timestamps = [

            timestamp
            for timestamp in self.execution_timestamps

            if (
                current_time - timestamp
            ).seconds < 60
        ]

        # ----------------------------------------------------
        # Throttle Detection
        # ----------------------------------------------------

        if (
            len(self.execution_timestamps)
            >= self.MAX_EXECUTIONS_PER_MINUTE
        ):

            return {
                "throttleActive": True,
                "reason": "EXECUTION_THROTTLE",
            }

        return {
            "throttleActive": False,
            "reason": None,
        }

    # ========================================================
    # COOLDOWN CONTROL
    # ========================================================

    def evaluate_cooldown_control(self):

        if self.last_execution_time is None:

            return {
                "cooldownActive": False,
                "remainingSeconds": 0,
            }

        current_time = datetime.utcnow()

        elapsed = (
            current_time - self.last_execution_time
        ).total_seconds()

        if elapsed < self.COOLDOWN_SECONDS:

            remaining = (
                self.COOLDOWN_SECONDS - elapsed
            )

            return {
                "cooldownActive": True,
                "remainingSeconds": round(
                    remaining,
                    2,
                ),
            }

        return {
            "cooldownActive": False,
            "remainingSeconds": 0,
        }

    # ========================================================
    # EXPOSURE SUPPRESSION
    # ========================================================

    def evaluate_exposure_suppression(
        self,
        current_exposure,
    ):

        exposure_risk = (
            current_exposure >= self.MAX_EXPOSURE
        )

        return {
            "exposureSuppressed": exposure_risk,
            "currentExposure": current_exposure,
        }

    # ========================================================
    # EXECUTION PACING
    # ========================================================

    def evaluate_execution_pacing(self):

        pacing_risk = (
            self.consecutive_executions
            >= self.MAX_CONSECUTIVE_EXECUTIONS
        )

        return {
            "pacingSuppressed": pacing_risk,
            "consecutiveExecutions": (
                self.consecutive_executions
            ),
        }

    # ========================================================
    # EMERGENCY HALT
    # ========================================================

    def evaluate_emergency_halt(self):

        return {
            "emergencyHalt": self.emergency_halt,
        }

    # ========================================================
    # EXECUTION LOCK
    # ========================================================

    def evaluate_execution_lock(self):

        return {
            "executionLocked": (
                self.execution_locked
            ),
        }

    # ========================================================
    # FINAL GOVERNANCE
    # ========================================================

    def evaluate_execution_governance(
        self,
        strategy_state,
        current_exposure=0.0,
    ):

        # ----------------------------------------------------
        # Strategy Validation
        # ----------------------------------------------------

        if not strategy_state.get(
            "executionAllowed",
            False,
        ):

            return {
                "executionAllowed": False,
                "reason": (
                    strategy_state.get(
                        "suppressionReason",
                        "STRATEGY_SUPPRESSED",
                    )
                ),
            }

        # ----------------------------------------------------
        # Emergency Halt
        # ----------------------------------------------------

        emergency_result = (
            self.evaluate_emergency_halt()
        )

        if emergency_result["emergencyHalt"]:

            return {
                "executionAllowed": False,
                "reason": "EMERGENCY_HALT",
            }

        # ----------------------------------------------------
        # Execution Lock
        # ----------------------------------------------------

        lock_result = (
            self.evaluate_execution_lock()
        )

        if lock_result["executionLocked"]:

            return {
                "executionAllowed": False,
                "reason": "EXECUTION_LOCKED",
            }

        # ----------------------------------------------------
        # Throttle
        # ----------------------------------------------------

        throttle_result = (
            self.evaluate_execution_throttle()
        )

        if throttle_result["throttleActive"]:

            return {
                "executionAllowed": False,
                "reason": (
                    throttle_result["reason"]
                ),
            }

        # ----------------------------------------------------
        # Cooldown
        # ----------------------------------------------------

        cooldown_result = (
            self.evaluate_cooldown_control()
        )

        if cooldown_result["cooldownActive"]:

            return {
                "executionAllowed": False,
                "reason": "COOLDOWN_ACTIVE",
            }

        # ----------------------------------------------------
        # Exposure
        # ----------------------------------------------------

        exposure_result = (
            self.evaluate_exposure_suppression(
                current_exposure
            )
        )

        if exposure_result[
            "exposureSuppressed"
        ]:

            return {
                "executionAllowed": False,
                "reason": "EXPOSURE_LIMIT",
            }

        # ----------------------------------------------------
        # Pacing
        # ----------------------------------------------------

        pacing_result = (
            self.evaluate_execution_pacing()
        )

        if pacing_result["pacingSuppressed"]:

            return {
                "executionAllowed": False,
                "reason": "EXECUTION_PACING",
            }

        # ----------------------------------------------------
        # EXECUTION APPROVED
        # ----------------------------------------------------

        return {
            "executionAllowed": True,
            "reason": None,
        }

    # ========================================================
    # REGISTER EXECUTION
    # ========================================================

    def register_execution(self):

        current_time = datetime.utcnow()

        self.execution_count += 1

        self.consecutive_executions += 1

        self.last_execution_time = current_time

        self.execution_timestamps.append(
            current_time
        )

    # ========================================================
    # RESET CONSECUTIVE
    # ========================================================

    def reset_consecutive_executions(self):

        self.consecutive_executions = 0

    # ========================================================
    # EMERGENCY CONTROL
    # ========================================================

    def activate_emergency_halt(self):

        self.emergency_halt = True

    def release_emergency_halt(self):

        self.emergency_halt = False

    # ========================================================
    # EXECUTION LOCK CONTROL
    # ========================================================

    def lock_execution(self):

        self.execution_locked = True

    def unlock_execution(self):

        self.execution_locked = False

    # ========================================================
    # FINAL PIPELINE ENTRY
    # ========================================================

    def process_execution_governance(
        self,
        strategy_state,
        current_exposure=0.0,
    ):

        governance_result = (
            self.evaluate_execution_governance(
                strategy_state,
                current_exposure,
            )
        )

        return {
            "valid": True,
            "governance": {

                "executionAllowed": (
                    governance_result[
                        "executionAllowed"
                    ]
                ),

                "reason": (
                    governance_result["reason"]
                ),

                "timestamp": (
                    datetime.utcnow().isoformat()
                ),
            },
        }