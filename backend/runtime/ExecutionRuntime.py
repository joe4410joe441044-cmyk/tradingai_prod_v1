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
from backend.runtime.runtime_symbol_context import symbol_context_matches
from backend.runtime.trading_trace import (
    new_trace_id,
    safe_record,
    strategy_decision_snapshot,
)
from backend.strategy.normalized_parameters import parameter_value

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
        self.handoff_live_block_reasons = []
        self.execution_governance_reached = False
        self.current_runtime_symbol_context = None

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
            "handoffLiveBlockReasons": self.handoff_live_block_reasons,
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

        if (self.current_runtime_symbol_context is not None
                and not symbol_context_matches(
                    adapter_output.get("runtimeSymbolContext"),
                    getattr(self.engine, "symbol", None),
                )):
            self.handoff_blocked_reason = "ORDER_INTENT_SYMBOL_MISMATCH"
            return

        if getattr(self.engine, "mode", None) == "live":

            live_readiness = (
                self.engine.build_live_readiness()
                if hasattr(self.engine, "build_live_readiness")
                else {
                    "realOrderAllowed": False,
                    "blockReasons": [
                        "LIVE_READINESS_UNAVAILABLE"
                    ],
                }
            )

            if not live_readiness.get(
                "realOrderAllowed",
                False,
            ):

                self.handoff_blocked_reason = (
                    "LIVE_NOT_READY"
                )
                self.handoff_live_block_reasons = list(
                    live_readiness.get("blockReasons")
                    or ["LIVE_NOT_READY"]
                )
                return

            self.handoff_live_block_reasons = []

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
                    "ExecutionEngine live handoff failed error=%s",
                    e,
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
            paper_orders_before = len(
                getattr(self.engine, "paper_orders", []) or []
            )
            submit_result = self.engine.submit_signal(
                adapter_output
            )
            paper_orders_after = len(
                getattr(self.engine, "paper_orders", []) or []
            )
            rejected = (
                isinstance(submit_result, dict)
                and submit_result.get("allowed") is False
            )
            self.handoff_executed = (
                not rejected
                and (
                    paper_orders_after > paper_orders_before
                    or isinstance(
                        getattr(self.engine, "actual_position", None),
                        dict,
                    )
                )
            )
            self.handoff_blocked_reason = (
                None
                if self.handoff_executed
                else submit_result.get("reason")
                if isinstance(submit_result, dict)
                else getattr(
                    self.engine,
                    "last_order_blocked_reason",
                    None,
                )
                or "ENGINE_DID_NOT_EXECUTE"
            )

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
        # Engine Risk Halt
        # ----------------------------------------------------

        engine_risk_state = {}

        if self.engine is not None and hasattr(
            self.engine,
            "get_risk_state",
        ):

            engine_risk_state = (
                self.engine.get_risk_state()
            )

        if engine_risk_state.get(
            "riskTradingDisabled",
            False,
        ):

            return {
                "executionAllowed": False,
                "reason": (
                    engine_risk_state.get(
                        "riskBlockReason",
                        "MAX_DRAWDOWN",
                    )
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

        minimum_confidence = 0.60
        if str(getattr(self.engine, "mode", "")).strip().lower() == "paper":
            minimum_confidence = float(parameter_value(
                strategy_state.get("parameterAuthority"),
                "minimumStrategyConfidence",
                minimum_confidence,
            ))

        if confidence < minimum_confidence:

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
        trace_id=None,
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

            "runtimeSymbolContext": self.current_runtime_symbol_context,

            "traceId": trace_id,
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

        engine_config = (
            getattr(self.engine, "config", {})
            if self.engine is not None
            else {}
        )

        trade_settings = {
            "symbol": (
                getattr(self.engine, "symbol", None)
                if self.engine is not None
                else None
            ),
            "risk_percent": engine_config.get("risk_percent"),
            "leverage": engine_config.get("leverage"),
            "timeframe": engine_config.get("timeframe"),
            "sl_percent": engine_config.get("sl_percent"),
            "tp_percent": engine_config.get("tp_percent"),
        }

        cooldown_result = (
            self.governance
            .evaluate_cooldown_control()
        )

        emergency_result = (
            self.governance
            .evaluate_emergency_halt()
        )

        live_readiness = (
            self.engine.build_live_readiness()
            if self.engine is not None
            and hasattr(self.engine, "build_live_readiness")
            else {}
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

            "riskState": (
                self.engine.get_risk_state()
                if self.engine is not None
                and hasattr(self.engine, "get_risk_state")
                else {}
            ),

            "tradeSettings": trade_settings,

            "trade_settings": trade_settings,

            "liveReadiness": live_readiness,

            "liveBlockReasons": (
                live_readiness.get("blockReasons", [])
            ),

            "realOrderAllowed": (
                live_readiness.get("realOrderAllowed", False)
            ),

            "exchangeClientReady": (
                live_readiness.get("exchangeClientReady", False)
            ),

            "exchangeAuthReady": (
                live_readiness.get("exchangeAuthReady", False)
            ),

            "balanceCheckOk": (
                live_readiness.get("balanceCheckOk", False)
            ),

            "positionCheckOk": (
                live_readiness.get("positionCheckOk", False)
            ),

            "executionEnabled": (
                live_readiness.get("executionEnabled", False)
            ),

            "emergencyStop": (
                live_readiness.get("emergencyStop", False)
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
        governance_resolver=None,
        money_management_decision=None,
        current_exposure=0.0,
        runtime_symbol_context=None,
    ):
        trace_id = strategy_state.get("traceId") or new_trace_id()
        strategy_state["traceId"] = trace_id
        mode = (
            "LIVE"
            if getattr(self.engine, "mode", None) == "live"
            else "PAPER"
        )
        context = (
            runtime_symbol_context
            or strategy_state.get("runtimeSymbolContext")
            or {}
        )
        symbol = (
            strategy_state.get("symbol")
            or context.get("symbol")
            or getattr(self.engine, "symbol", None)
        )
        runtime_id = (
            strategy_state.get("runtimeId")
            or context.get("runtimeId")
        )
        decision_id = strategy_state.get("decisionId")
        direction = str(
            strategy_state.get("direction") or "HOLD"
        ).upper()
        strategy_status = (
            "HOLD"
            if direction == "HOLD"
            or not strategy_state.get("executionAllowed", False)
            else direction
        )

        def record(stage, status, reason=None, metadata=None):
            safe_record(
                trace_id=trace_id,
                mode=mode,
                stage=stage,
                status=status,
                symbol=symbol,
                runtime_id=runtime_id,
                decision_id=decision_id,
                reason_code=reason,
                metadata=metadata,
            )

        def clear_preflight():
            if self.engine is not None and hasattr(
                self.engine,
                "clear_execution_entry_preflight",
            ):
                self.engine.clear_execution_entry_preflight(trace_id)

        def context_fields(
            *,
            money_reached=False,
            money_decision=None,
            governance_reached=False,
            governance_output=None,
        ):
            governance_allowed = (
                governance_output.get("allowed")
                if isinstance(governance_output, dict)
                else None
            )
            governance_reason = (
                governance_output.get("reason")
                if isinstance(governance_output, dict)
                else None
            )
            return {
                "tradingAiMode": "OFF",
                "tradingAiStatus": "NOT_INSTALLED",
                "aiRuntimeReached": False,
                "aiDecision": None,
                "moneyManagementReached": bool(money_reached),
                "moneyManagementDecision": money_decision,
                "governanceRuntimeReached": bool(governance_reached),
                "governanceOutput": governance_output,
                "governanceDecision": (
                    "ALLOW" if governance_allowed is True
                    else "BLOCK" if governance_allowed is False
                    else None
                ),
                "governanceAllowed": governance_allowed,
                "governanceBlockedReason": (
                    governance_reason
                    if governance_allowed is False
                    else None
                ),
            }

        record(
            "STRATEGY",
            strategy_status,
            strategy_state.get("suppressionReason"),
            {
                "decision": direction,
                "confidence": strategy_state.get("confidence"),
                "executionAllowed": strategy_state.get("executionAllowed"),
                "decisionInput": strategy_decision_snapshot(strategy_state),
            },
        )
        record(
            "AI",
            "DISABLED",
            "TRADING_AI_OFF",
            {
                "mode": "OFF",
                "implementationStatus": "NOT_INSTALLED",
                "required": False,
                "fallback": None,
            },
        )

        self.signal_adapter_reached = False
        self.last_adapter_output = None
        self.handoff_attempted = False
        self.handoff_executed = False
        self.handoff_blocked_reason = None
        self.handoff_signal = None
        self.handoff_live_block_reasons = []
        self.execution_governance_reached = False
        self.current_runtime_symbol_context = runtime_symbol_context

        if strategy_status == "HOLD":
            reason = (
                strategy_state.get("suppressionReason")
                or "STRATEGY_HOLD"
            )
            record(
                "MONEY_MANAGEMENT",
                "NOT_REQUIRED",
                "STRATEGY_HOLD",
            )
            record(
                "RESULT",
                "SUPPRESSED",
                reason,
                {"decision": "HOLD"},
            )
            return {
                "valid": True,
                "traceId": trace_id,
                **context_fields(),
                "runtime": {
                    "executionAllowed": False,
                    "reason": reason,
                },
                **self.build_direction_contract_trace(None),
            }

        engine_symbol = getattr(self.engine, "symbol", None)
        strategy_context = strategy_state.get("runtimeSymbolContext")
        if runtime_symbol_context is not None and (
            not symbol_context_matches(
                runtime_symbol_context,
                engine_symbol,
            )
            or strategy_context != runtime_symbol_context
        ):
            self.handoff_blocked_reason = (
                "RUNTIME_SYMBOL_CONTEXT_MISMATCH"
            )
            record(
                "RESULT",
                "FAILED",
                self.handoff_blocked_reason,
            )
            return {
                "valid": False,
                "traceId": trace_id,
                **context_fields(),
                **self.build_direction_contract_trace(None),
                "runtime": {
                    "executionAllowed": False,
                    "reason": self.handoff_blocked_reason,
                },
            }

        canonical_direction = self.normalize_direction(direction)

        try:
            validation_result = self.validate_strategy_state(
                strategy_state
            )
            if not validation_result["valid"]:
                reason = validation_result["reason"]
                record(
                    "MONEY_MANAGEMENT",
                    "NOT_REQUIRED",
                    "STRATEGY_INVALID",
                )
                record("RESULT", "BLOCKED", reason)
                return {
                    "valid": False,
                    "traceId": trace_id,
                    **context_fields(),
                    **self.build_direction_contract_trace(
                        canonical_direction
                    ),
                    "runtime": {
                        "executionAllowed": False,
                        "reason": reason,
                    },
                }

            if money_management_decision is None:
                if self.engine is None or not hasattr(
                    self.engine,
                    "preflight_execution_entry",
                ):
                    money_management_decision = {
                        "allowed": False,
                        "decision": "UNKNOWN",
                        "reason": "MONEY_MANAGEMENT_UNKNOWN",
                    }
                else:
                    money_management_decision = (
                        self.engine.preflight_execution_entry(
                            (
                                "BUY"
                                if canonical_direction == "LONG"
                                else "SELL"
                            ),
                            trace_id,
                        )
                    )
            money_management_decision = dict(
                money_management_decision or {}
            )
            money_allowed = (
                money_management_decision.get("allowed") is True
            )
            money_reason = money_management_decision.get("reason")
            record(
                "MONEY_MANAGEMENT",
                "ALLOW" if money_allowed else "BLOCKED",
                money_reason,
                money_management_decision,
            )

            if not money_allowed:
                clear_preflight()
                reason = (
                    money_reason
                    or "MONEY_MANAGEMENT_BLOCKED"
                )
                record(
                    "RESULT",
                    "BLOCKED",
                    reason,
                    {"decision": direction},
                )
                return {
                    "valid": True,
                    "traceId": trace_id,
                    **context_fields(
                        money_reached=True,
                        money_decision=money_management_decision,
                    ),
                    **self.build_direction_contract_trace(
                        canonical_direction
                    ),
                    "runtime": {
                        "executionAllowed": False,
                        "reason": reason,
                    },
                }

            if governance_resolver is not None:
                governance_decision = governance_resolver(
                    strategy_state
                )
            if not isinstance(governance_decision, dict):
                governance_decision = {
                    "allowed": False,
                    "reason": "GOVERNANCE_UNAVAILABLE",
                    "direction": None,
                }
            else:
                governance_decision = dict(governance_decision)

            if runtime_symbol_context is not None:
                governance_decision.update({
                    "symbol": symbol,
                    "runtimeId": runtime_id,
                    "runtimeSymbolContext": runtime_symbol_context,
                })

            governance_allowed = (
                governance_decision.get("allowed") is True
            )
            governance_reason = governance_decision.get("reason")
            record(
                "GOVERNANCE",
                "ALLOW" if governance_allowed else "BLOCKED",
                governance_reason,
            )
            decision_fields = context_fields(
                money_reached=True,
                money_decision=money_management_decision,
                governance_reached=True,
                governance_output=governance_decision,
            )

            if not governance_allowed:
                clear_preflight()
                reason = governance_reason or "GOVERNANCE_REJECTED"
                record(
                    "RESULT",
                    "BLOCKED",
                    reason,
                    {"decision": direction},
                )
                return {
                    "valid": False,
                    "traceId": trace_id,
                    **decision_fields,
                    **self.build_direction_contract_trace(
                        canonical_direction
                    ),
                    "runtime": {
                        "executionAllowed": False,
                        "reason": reason,
                    },
                }

            if governance_state.get("emergency_stop", False):
                self.governance.activate_emergency_halt()
            else:
                self.governance.release_emergency_halt()

            self.mark_execution_governance_reached()
            governance_wrapper = (
                self.governance.process_execution_governance(
                    strategy_state,
                    current_exposure,
                )
            )
            governance_result = governance_wrapper["governance"]
            permission_result = self.evaluate_execution_permission(
                strategy_state,
                governance_result,
                governance_decision,
                canonical_direction,
            )

            if not permission_result["executionAllowed"]:
                clear_preflight()
                reason = permission_result["reason"]
                record("GOVERNANCE", "BLOCKED", reason)
                record(
                    "RESULT",
                    "BLOCKED",
                    reason,
                    {"decision": direction},
                )
                suppression_event = self.build_suppression_event(
                    reason
                )
                runtime_state = self.build_execution_runtime_state(
                    permission_result
                )
                return {
                    "valid": True,
                    "traceId": trace_id,
                    **decision_fields,
                    **self.build_direction_contract_trace(
                        canonical_direction
                    ),
                    "runtime": {
                        "executionAllowed": False,
                        "reason": reason,
                        "suppression": suppression_event,
                        "telemetry": runtime_state,
                    },
                }

            execution_event = self.dispatch_execution(
                canonical_direction,
                trace_id=trace_id,
            )
            if not self.handoff_executed:
                clear_preflight()

            execution_status = (
                "PAPER_FILLED"
                if mode == "PAPER" and self.handoff_executed
                else "ORDER_SUBMITTED"
                if mode == "LIVE" and self.handoff_executed
                else "FAILED"
            )
            order_id = None
            if (
                mode == "PAPER"
                and self.engine is not None
                and getattr(self.engine, "paper_orders", None)
            ):
                order_id = self.engine.paper_orders[-1].get(
                    "orderId"
                )
            record(
                "EXECUTION",
                execution_status,
                self.handoff_blocked_reason,
                {"orderId": order_id},
            )
            if (
                self.handoff_executed
                and isinstance(
                    getattr(self.engine, "actual_position", None),
                    dict,
                )
            ):
                position = self.engine.actual_position
                position_id = (
                    position.get("position_id")
                    or position.get("order_id")
                )
                record(
                    "POSITION",
                    "OPEN",
                    metadata={
                        "positionId": position_id,
                        "orderId": order_id,
                        "side": position.get("side"),
                        "entry": position.get("entry_price"),
                        "quantity": position.get("coin_qty"),
                    },
                )
                record(
                    "RESULT",
                    "EXECUTED",
                    metadata={
                        "decision": direction,
                        "orderId": order_id,
                        "positionId": position_id,
                    },
                )
            elif not self.handoff_executed:
                record(
                    "RESULT",
                    "BLOCKED",
                    self.handoff_blocked_reason
                    or "EXECUTION_HANDOFF_BLOCKED",
                    {"decision": direction},
                )

            runtime_state = self.build_execution_runtime_state(
                permission_result
            )
            return {
                "valid": True,
                "traceId": trace_id,
                **decision_fields,
                **self.build_direction_contract_trace(
                    canonical_direction
                ),
                "runtime": {
                    "executionAllowed": self.handoff_executed,
                    "reason": (
                        None
                        if self.handoff_executed
                        else self.handoff_blocked_reason
                        or "EXECUTION_HANDOFF_BLOCKED"
                    ),
                    "execution": execution_event,
                    "telemetry": runtime_state,
                },
            }

        except Exception as error:
            clear_preflight()
            self.runtime_healthy = False
            reason = str(error)
            record("RESULT", "FAILED", reason)
            suppression_event = self.build_suppression_event(
                reason,
                layer="RUNTIME_EXCEPTION",
            )
            return {
                "valid": False,
                "traceId": trace_id,
                **context_fields(),
                **self.build_direction_contract_trace(
                    canonical_direction
                ),
                "runtime": {
                    "executionAllowed": False,
                    "reason": reason,
                    "suppression": suppression_event,
                },
            }
