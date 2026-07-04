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

from backend.utils.log_buffer import runtime_debug

from datetime import datetime

from backend.execution.ExecutionGovernance import (
    ExecutionGovernance,
)

from backend.runtime.adapters.execution_signal_adapter import (
    ExecutionSignalAdapter,
)

import backend.config as config


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

        # Latest direction-contract trace
        self.signal_adapter_reached = False
        self.last_adapter_output = None

        # Latest ExecutionEngine handoff trace
        self.handoff_attempted = False
        self.handoff_executed = False
        self.handoff_blocked_reason = None
        self.handoff_signal = None
        self.execution_governance_reached = False

    # ========================================================
    # ENGINE BINDING
    # ========================================================

    def set_engine(self, engine):

        self.engine = engine

    # ========================================================
    # DIRECTION CONTRACT
    # ========================================================

    @staticmethod
    def normalize_direction(direction):

        return {
            "BUY": "LONG",
            "SELL": "SHORT",
            "LONG": "LONG",
            "SHORT": "SHORT",
        }.get(direction)

    def build_direction_contract_trace(
        self,
        canonical_direction,
    ):

        return {
            "executionRuntimeReached": True,
            "executionGovernanceReached": self.execution_governance_reached,
            "signalAdapterReached": self.signal_adapter_reached,
            "normalizedDirection": canonical_direction,
            "adapterOutput": self.last_adapter_output,
            "handoffAttempted": self.handoff_attempted,
            "handoffExecuted": self.handoff_executed,
            "handoffBlockedReason": self.handoff_blocked_reason,
            "handoffSignal": self.handoff_signal,
        }

    def mark_execution_governance_reached(self):
        """Record monitoring telemetry without changing the decision path."""

        self.execution_governance_reached = True

    # ========================================================
    # EXECUTION ENGINE HANDOFF
    # ========================================================

    def handoff_adapter_output(
        self,
        adapter_output,
    ):

        self.handoff_attempted = True
        self.handoff_signal = adapter_output

        if self.engine is None:

            self.handoff_blocked_reason = (
                "ENGINE_UNAVAILABLE"
            )
            return

        if adapter_output is None:

            self.handoff_blocked_reason = (
                "ADAPTER_OUTPUT_UNAVAILABLE"
            )
            return

        if getattr(self.engine, "mode", None) == "live":

            self.handoff_blocked_reason = (
                "ENGINE_MODE_LIVE"
            )
            return

        engine_config = getattr(
            self.engine,
            "config",
            {},
        )

        config_dry_run = (
            engine_config.get("dry_run")
            if isinstance(engine_config, dict)
            else None
        )

        engine_dry_run = getattr(
            self.engine,
            "dry_run",
            config_dry_run,
        )

        if engine_dry_run is not True:

            self.handoff_blocked_reason = (
                "ENGINE_DRY_RUN_NOT_TRUE"
            )
            return

        if getattr(self.engine, "exchange", None) is not None:

            self.handoff_blocked_reason = (
                "ENGINE_EXCHANGE_ATTACHED"
            )
            return

        if config.ALLOW_LIVE is not False:

            self.handoff_blocked_reason = (
                "CONFIG_ALLOW_LIVE_NOT_FALSE"
            )
            return

        if config.TRADE_MODE != "paper":

            self.handoff_blocked_reason = (
                "CONFIG_TRADE_MODE_NOT_PAPER"
            )
            return

        try:

            self.engine.submit_signal(
                adapter_output
            )

            self.handoff_executed = True
            self.handoff_blocked_reason = None

        except Exception as e:

            self.handoff_blocked_reason = (
                "ENGINE_SUBMIT_EXCEPTION"
            )

            runtime_debug(
                "ExecutionEngine handoff failed error=%s",
                e,
            )

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
        canonical_direction=None,

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

        runtime_debug(
            "Execution permission direction=%s",
            canonical_direction,
        )

        if canonical_direction not in [

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
        canonical_direction,
    ):

        execution_event = {

            "executed": True,

            "mode": (
                "SIMULATED_EXECUTION"
            ),

            "direction": canonical_direction,

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
        # Execution Engine Handoff
        # ----------------------------------------------------

        self.signal_adapter_reached = True

        signal = (
            ExecutionSignalAdapter.adapt(
                execution_event
            )
        )

        self.last_adapter_output = signal

        self.handoff_adapter_output(
            self.last_adapter_output
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
        self.signal_adapter_reached = False
        self.last_adapter_output = None
        self.handoff_attempted = False
        self.handoff_executed = False
        self.handoff_blocked_reason = None
        self.handoff_signal = None
        self.execution_governance_reached = False

        if governance_decision is not None:

            source_direction = governance_decision.get(
                "direction"
            )

        else:

            source_direction = strategy_state.get(
                "direction"
            )

        canonical_direction = self.normalize_direction(
            source_direction
        )

        runtime_debug(
            "Execution governance=%s source_direction=%s "
            "canonical_direction=%s",
            governance_decision,
            source_direction,
            canonical_direction,
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
                        **self.build_direction_contract_trace(
                            canonical_direction
                        ),
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

            self.mark_execution_governance_reached()

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
                    canonical_direction,
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

                    **self.build_direction_contract_trace(
                        canonical_direction
                    ),

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

            runtime_debug(
                "Execution dispatch direction=%s",
                canonical_direction,
            )

            execution_event = (
                self.dispatch_execution(
                    canonical_direction

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

                **self.build_direction_contract_trace(
                    canonical_direction
                ),

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

                **self.build_direction_contract_trace(
                    canonical_direction
                ),

                "runtime": {

                    "executionAllowed": False,

                    "reason": str(e),

                    "suppression": (
                        suppression_event
                    ),
                },
            }
