# ============================================================
# FILE:
# backend/runtime/ExecutionRuntime.py
# ============================================================

# ============================================================
# ExecutionRuntime.py
# ============================================================
#
# PURPOSE
# ------------------------------------------------------------
# Final governed execution runtime.
#
# This layer:
#
# - receives strategy state
# - validates governance authority
# - evaluates final execution permission
# - dispatches execution
# - logs suppression events
# - builds execution telemetry
#
# IMPORTANT:
# ------------------------------------------------------------
# This runtime DOES NOT predict the market.
#
# This runtime exists to:
#
#     suppress dangerous execution
#
# ============================================================

from backend.runtime.governance_runtime import (
    governance_state,
)

from datetime import datetime

from backend.execution.ExecutionGovernance import (
    ExecutionGovernance,
)

from backend.runtime.adapters.execution_signal_adapter import (
ExecutionSignalAdapter
)

class ExecutionRuntime:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self):

        self.governance = (
            ExecutionGovernance()
        )

        self.last_execution = None

        self.last_suppression_reason = None

        self.runtime_healthy = True

        self.suppression_events = []

        # ExecutionEngine Binding
        self.engine = None

    # ========================================================
    # ENGINE BINDING
    # ========================================================

    def set_engine(self, engine):

        self.engine = engine

    # ========================================================
    # STRATEGY VALIDATION
    # ========================================================

    def validate_strategy_state(
        self,
        strategy_state,
    ):

        required_fields = [

            "executionAllowed",
            "direction",
            "edge",
            "confidence",
            "risk",
        ]

        for field in required_fields:

            if field not in strategy_state:

                return {
                    "valid": False,
                    "reason": (
                        f"MISSING_{field}"
                    ),
                }

        return {
            "valid": True,
            "reason": None,
        }

    # ========================================================
    # FINAL EXECUTION PERMISSION
    # ========================================================

    def evaluate_execution_permission(
        self,
        strategy_state,
        governance_result,
        governance_decision=None,

    ):

        # ----------------------------------------------------
        # Governance Rejection
        # ----------------------------------------------------

        if not governance_result.get(
            "executionAllowed",
            False,
        ):

            return {
                "executionAllowed": False,
                "reason": (
                    governance_result.get(
                        "reason",
                        "GOVERNANCE_REJECTED",
                    )
                ),
            }

        # ----------------------------------------------------
        # Invalid Direction
        # ----------------------------------------------------

        if governance_decision is not None:

            direction = governance_decision.get(
                "direction",
                "NEUTRAL",
            )

        else:

            direction = strategy_state.get(
                "direction",
                "NEUTRAL",
            )
        print(
            "PERMISSION DIRECTION:",
            direction,
        )

        if direction not in [

            "LONG",
            "SHORT",

        ]:

            return {
                "executionAllowed": False,
                "reason": (
                    "INVALID_DIRECTION"
                ),
            }

        # ----------------------------------------------------
        # Governance Runtime Switch
        # ----------------------------------------------------

        if not governance_state.get(
            "execution_enabled",
            False,
        ):

            return {
                "executionAllowed": False,
                "reason": (
                    "EXECUTION_DISABLED"
                ),
            }

        # ----------------------------------------------------
        # Low Confidence
        # ----------------------------------------------------

        confidence = float(
            strategy_state.get(
                "confidence",
                0.0,
            )
        )

        if confidence < 0.60:

            return {
                "executionAllowed": False,
                "reason": (
                    "LOW_CONFIDENCE"
                ),
            }

        # ----------------------------------------------------
        # Runtime Healthy
        # ----------------------------------------------------

        if not self.runtime_healthy:

            return {
                "executionAllowed": False,
                "reason": (
                    "RUNTIME_UNHEALTHY"
                ),
            }

        # ----------------------------------------------------
        # FINAL APPROVAL
        # ----------------------------------------------------

        return {
            "executionAllowed": True,
            "reason": None,
        }

    # ========================================================
    # EXECUTION DISPATCH
    # ========================================================

    def dispatch_execution(
        self,
        governance_decision,
    ):

        direction = governance_decision.get(
            "direction"
        )

        execution_event = {

            "executed": True,

            "mode": (
                "SIMULATED_EXECUTION"
            ),

            "direction": direction,

            "timestamp": (
                datetime.utcnow().isoformat()
            ),
        }

        # ----------------------------------------------------
        # Register Execution
        # ----------------------------------------------------

        self.last_execution = (
            execution_event
        )

        self.governance.register_execution()

        # ----------------------------------------------------
        # Execution Engine Dispatch
        # ----------------------------------------------------

        if self.engine:

            signal = (
                ExecutionSignalAdapter.adapt(
                    execution_event
                )
            )

            if signal:

                self.engine.submit_signal(
                    signal
                )
                
                
        return execution_event


    # ========================================================
    # SUPPRESSION EVENT
    # ========================================================

    def build_suppression_event(
        self,
        reason,
        layer="EXECUTION_RUNTIME",
    ):

        suppression_event = {

            "suppressed": True,

            "reason": reason,

            "layer": layer,

            "timestamp": (
                datetime.utcnow().isoformat()
            ),
        }

        self.suppression_events.append(
            suppression_event
        )

        # ----------------------------------------------------
        # Prevent Infinite Growth
        # ----------------------------------------------------

        if len(self.suppression_events) > 1000:

            self.suppression_events = (
                self.suppression_events[-1000:]
            )

        self.last_suppression_reason = (
            reason
        )

        return suppression_event

    # ========================================================
    # EXECUTION TELEMETRY
    # ========================================================

    def build_execution_runtime_state(
        self,
        governance_result,
    ):

        cooldown_result = (
            self.governance
            .evaluate_cooldown_control()
        )

        emergency_result = (
            self.governance
            .evaluate_emergency_halt()
        )

        runtime_state = {

            "runtimeHealthy": (
                self.runtime_healthy
            ),

            "executionAllowed": (
                governance_result.get(
                    "executionAllowed",
                    False,
                )
            ),

            "suppressionReason": (
                governance_result.get(
                    "reason"
                )
            ),

            "lastExecution": (
                self.last_execution
            ),

            "cooldownActive": (
                cooldown_result[
                    "cooldownActive"
                ]
            ),

            "emergencyHalt": (
                emergency_result[
                    "emergencyHalt"
                ]
            ),

            "timestamp": (
                datetime.utcnow().isoformat()
            ),
        }

        return runtime_state

    # ========================================================
    # MAIN RUNTIME PIPELINE
    # ========================================================

    def process_execution_runtime(
        self,
        strategy_state,
        governance_decision=None,
        current_exposure=0.0,
    ):
        print(
            "EXECUTION GOVERNANCE:",
            governance_decision,
        )

        try:

            # ------------------------------------------------
            # Strategy Validation
            # ------------------------------------------------

            validation_result = (
                self.validate_strategy_state(
                    strategy_state
                )
            )

            if not validation_result["valid"]:

                suppression_event = (
                    self.build_suppression_event(
                        validation_result[
                            "reason"
                        ],
                        layer="STRATEGY_VALIDATION",
                    )
                )
            if governance_decision is not None:

                if not governance_decision.get(
                    "allowed",
                    False,
                ):
                    return {
                        "valid": False,
                        "runtime": {
                            "executionAllowed": False,
                            "reason": (
                                governance_decision.get(
                                    "reason",
                                    "GOVERNANCE_REJECTED",
                                )
                            ),
                        },
                    }

                # allowed=True
                # returnしない
                # 後続の permission → dispatch へ進む
            # ------------------------------------------------
            # Governance State Sync
            # ------------------------------------------------

            if governance_state.get(
                "emergency_stop",
                False,
            ):
                self.governance.activate_emergency_halt()
            else:
                self.governance.release_emergency_halt()

            # ------------------------------------------------
            # Governance
            # ------------------------------------------------

            governance_wrapper = (
                self.governance
                .process_execution_governance(
                    strategy_state,
                    current_exposure,
                )
            )

            governance_result = (
                governance_wrapper[
                    "governance"
                ]
            )

            # ------------------------------------------------
            # Final Permission
            # ------------------------------------------------

            permission_result = (
                self.evaluate_execution_permission(
                    strategy_state,
                    governance_result,
                    governance_decision,
                )
            )

            # ------------------------------------------------
            # Execution Rejected
            # ------------------------------------------------

            if not permission_result[
                "executionAllowed"
            ]:

                suppression_event = (
                    self.build_suppression_event(
                        permission_result[
                            "reason"
                        ]
                    )
                )

                runtime_state = (
                    self.build_execution_runtime_state(
                        permission_result
                    )
                )

                return {

                    "valid": True,

                    "runtime": {

                        "executionAllowed": False,

                        "reason": (
                            permission_result[
                                "reason"
                            ]
                        ),

                        "suppression": (
                            suppression_event
                        ),

                        "telemetry": (
                            runtime_state
                        ),
                    },
                }

            # ------------------------------------------------
            # Dispatch Execution
            # ------------------------------------------------

            print(
                "DISPATCH DIRECTION:",
                governance_decision.get(
                    "direction"
                ),
            )

            execution_event = (
                self.dispatch_execution(
                    governance_decision

                )
            )

            # ------------------------------------------------
            # Runtime Telemetry
            # ------------------------------------------------

            runtime_state = (
                self.build_execution_runtime_state(
                    permission_result
                )
            )

            return {

                "valid": True,

                "runtime": {

                    "executionAllowed": True,

                    "execution": (
                        execution_event
                    ),

                    "telemetry": (
                        runtime_state
                    ),
                },
            }

        except Exception as e:

            self.runtime_healthy = False

            suppression_event = (
                self.build_suppression_event(
                    str(e),
                    layer="RUNTIME_EXCEPTION",
                )
            )

            return {

                "valid": False,

                "runtime": {

                    "executionAllowed": False,

                    "reason": str(e),

                    "suppression": (
                        suppression_event
                    ),
                },
            }