# -*- coding: utf-8 -*-

from backend.runtime.governance_runtime import (
    GovernanceRuntime,
)
from fastapi import (
    FastAPI,
    WebSocket,
)

from fastapi.middleware.cors import (
    CORSMiddleware,
)

import backend.runtime.runtime_registry as registry

from backend.runtime.runtime_debug_snapshot import (
    build_runtime_debug_result,
    extract_value,
    safe_debug,
)



# ============================================================
# LOG
# ============================================================

from backend.utils.log_buffer import (
    add_log,
    logger,
    runtime_debug,
)

# ============================================================
# GOVERNANCE ROUTER
# ============================================================

from backend.api.governance import (
    router as governance_router
)

# ============================================================
# WEBSOCKET MANAGER
# ============================================================

from backend.websocket import ws_manager

# ============================================================
# EXECUTION COGNITION RUNTIME
# ============================================================

from backend.strategy.MicrostructureEdgeStrategy import (
    MicrostructureEdgeStrategy
)

from backend.runtime.ExecutionRuntime import (
    ExecutionRuntime
)

from backend.ai.ai_pipeline import (
    AIPipeline
)

from backend.ai.runtime_adapter import (
    RuntimeAdapter
)

# ============================================================
# FASTAPI
# ============================================================

app = FastAPI()


def _new_momentum_trace(microstructure_state):

    missing = object()
    source_value = extract_value(
        microstructure_state,
        "momentumPersistence",
        missing,
    )
    source_present = source_value is not missing

    if not source_present:
        source_value = None

    source_computation = extract_value(
        microstructure_state,
        "momentumPersistenceDebug",
    )

    price_history_generation = extract_value(
        microstructure_state,
        "priceHistoryGenerationDebug",
    )

    return {
        "sourceGenerator": (
            "MicrostructureStateBuilder."
            "compute_momentum_persistence"
        ),
        "sourceField": (
            "microstructure_state.momentumPersistence"
        ),
        "sourcePresent": source_present,
        "sourceValue": safe_debug(source_value),
        "sourceComputation": safe_debug(
            source_computation
        ),
        "priceHistoryGeneration": safe_debug(
            price_history_generation
        ),
        "strategyInputValue": safe_debug(source_value),
        "strategyFallbackUsed": not source_present,
        "strategyFallbackValue": 0.0,
        "strategyOutputPresent": None,
        "strategyOutputValue": None,
        "runtimeAdapterFallbackUsed": None,
        "runtimeStateValue": None,
        "tradeBrainFallbackUsed": None,
        "tradeBrainValue": None,
        "llmEngineFallbackUsed": None,
        "llmEngineValue": None,
        "valueChanged": None,
        "zeroFirstObservedAt": (
            "microstructure_state.momentumPersistence"
            if source_present and source_value == 0
            else None
        ),
    }


def _update_momentum_trace_consistency(momentum_trace):

    stages = (
        (
            "microstructure_state.momentumPersistence",
            momentum_trace.get("sourceValue"),
        ),
        (
            "runtime_state.momentum_score",
            momentum_trace.get("runtimeStateValue"),
        ),
        (
            "TradeBrain.llmInput.runtime_state.momentum_score",
            momentum_trace.get("tradeBrainValue"),
        ),
        (
            "LLMEngine.llmRuleInput.momentum_score",
            momentum_trace.get("llmEngineValue"),
        ),
    )
    observed_values = [
        value
        for _, value in stages
        if value is not None
    ]

    momentum_trace["zeroFirstObservedAt"] = next(
        (
            stage
            for stage, value in stages
            if value == 0
        ),
        None,
    )

    if len(observed_values) < 2:
        momentum_trace["valueChanged"] = None
        return

    first_value = observed_values[0]
    momentum_trace["valueChanged"] = any(
        value != first_value
        for value in observed_values[1:]
    )


def _new_momentum_pipeline_trace(microstructure_state):

    momentum = safe_debug(extract_value(
        microstructure_state,
        "momentumPersistence",
    ))
    ai_momentum = safe_debug(extract_value(
        microstructure_state,
        "aiMomentumPersistence",
    ))
    ai_momentum_trace = extract_value(
        microstructure_state,
        "aiMomentumTrace",
    )
    comparison_metrics = extract_value(
        ai_momentum_trace,
        "comparisonMetrics",
    )
    candidate_metrics = extract_value(
        ai_momentum_trace,
        "candidateMetrics",
    )

    trace = {
        "microstructureMomentumPersistence": momentum,
        "microstructureAiMomentumPersistence": ai_momentum,
        "runtimeAdapterInputMomentum": momentum,
        "runtimeAdapterInputAiMomentum": ai_momentum,
        "runtimeStateMomentumScore": None,
        "tradeBrainInputMomentumScore": None,
        "llmInputMomentumScore": None,
        "llmRuleInputMomentumScore": None,
        "aiMomentumTraceValue": safe_debug(extract_value(
            ai_momentum_trace,
            "value",
        )),
        "aiMomentumFlatExcludedMomentum": safe_debug(
            extract_value(
                comparison_metrics,
                "flatExcludedMomentum",
            )
        ),
        "aiMomentumProposedMomentumScore": safe_debug(
            extract_value(
                candidate_metrics,
                "proposedMomentumScore",
            )
        ),
        "allValuesEqual": None,
        "mismatchDetected": None,
        "mismatchReason": None,
    }
    _update_momentum_pipeline_trace_consistency(trace)
    return trace


def _update_momentum_pipeline_trace_consistency(trace):

    value_fields = (
        "microstructureMomentumPersistence",
        "microstructureAiMomentumPersistence",
        "runtimeAdapterInputMomentum",
        "runtimeAdapterInputAiMomentum",
        "runtimeStateMomentumScore",
        "tradeBrainInputMomentumScore",
        "llmInputMomentumScore",
        "llmRuleInputMomentumScore",
        "aiMomentumTraceValue",
        "aiMomentumFlatExcludedMomentum",
        "aiMomentumProposedMomentumScore",
    )
    values = [trace.get(field) for field in value_fields]
    all_present = all(value is not None for value in values)
    all_values_equal = (
        all_present
        and all(value == values[0] for value in values[1:])
    )

    trace["allValuesEqual"] = all_values_equal
    trace["mismatchDetected"] = not all_values_equal

    runtime_state_momentum = trace.get(
        "runtimeStateMomentumScore"
    )
    llm_input_momentum = trace.get("llmInputMomentumScore")
    microstructure_momentum = trace.get(
        "microstructureMomentumPersistence"
    )
    microstructure_ai_momentum = trace.get(
        "microstructureAiMomentumPersistence"
    )
    ai_trace_value = trace.get("aiMomentumTraceValue")
    proposed_momentum = trace.get(
        "aiMomentumProposedMomentumScore"
    )

    if runtime_state_momentum is None:
        reason = "MISSING_RUNTIME_STATE_MOMENTUM"
    elif ai_trace_value is None:
        reason = "MISSING_AI_MOMENTUM_TRACE"
    elif all_values_equal:
        reason = "NO_MISMATCH"
    elif (
        llm_input_momentum == microstructure_momentum
        and microstructure_ai_momentum != llm_input_momentum
    ):
        reason = "LLM_USES_MICROSTRUCTURE_MOMENTUM"
    elif ai_trace_value != llm_input_momentum:
        reason = "AI_TRACE_VALUE_DIFFERS_FROM_LLM_INPUT"
    elif proposed_momentum != llm_input_momentum:
        reason = "PROPOSED_SCORE_DIFFERS_FROM_LLM_INPUT"
    else:
        reason = "UNKNOWN_MISMATCH"

    trace["mismatchReason"] = reason


def _record_strategy_debug(debug_result, strategy_result):

    strategy_state = extract_value(
        strategy_result,
        "strategy",
    )

    debug_result.update({
        "strategyRuntimeReached": True,
        "strategyOutput": safe_debug(strategy_result),
        "strategySignal": safe_debug(
            extract_value(strategy_state, "signal")
        ),
        "strategyDirection": safe_debug(
            extract_value(strategy_state, "direction")
        ),
        "strategyConfidence": safe_debug(
            extract_value(strategy_state, "confidence")
        ),
        "liquidityInstabilityDebug": safe_debug(
            extract_value(
                strategy_state,
                "liquidityInstabilityDebug",
                debug_result.get(
                    "liquidityInstabilityDebug"
                ),
            )
        ),
        "liquidityDeteriorationDebug": safe_debug(
            extract_value(
                strategy_state,
                "liquidityDeteriorationDebug",
                debug_result.get(
                    "liquidityDeteriorationDebug"
                ),
            )
        ),
    })

    momentum_trace = debug_result.get("momentumTrace")

    if isinstance(momentum_trace, dict):
        missing = object()
        strategy_momentum = missing

        for key in (
            "momentum_score",
            "momentumScore",
            "momentumPersistence",
            "momentum",
        ):
            strategy_momentum = extract_value(
                strategy_state,
                key,
                missing,
            )

            if strategy_momentum is not missing:
                break

        momentum_trace["strategyOutputPresent"] = (
            strategy_momentum is not missing
        )
        momentum_trace["strategyOutputValue"] = safe_debug(
            None
            if strategy_momentum is missing
            else strategy_momentum
        )


def _attach_runtime_debug(runtime_result, debug_result):

    if isinstance(runtime_result, dict):
        runtime_result.update(debug_result)
        runtime_result["runtimeDebug"] = {
            "momentumTrace": safe_debug(
                debug_result.get("momentumTrace")
            ),
            "momentumPipelineTrace": safe_debug(
                debug_result.get("momentumPipelineTrace")
            ),
            "priceHistoryTrace": safe_debug(
                debug_result.get("priceHistoryTrace")
            ),
            "aiMomentumTrace": safe_debug(
                debug_result.get("aiMomentumTrace")
            ),
            "liquidityInstabilityDebug": safe_debug(
                debug_result.get(
                    "liquidityInstabilityDebug"
                )
            ),
            "liquidityDeteriorationDebug": safe_debug(
                debug_result.get(
                    "liquidityDeteriorationDebug"
                )
            ),
            "aiRuntimeReached": safe_debug(
                debug_result.get("aiRuntimeReached")
            ),
            "aiInput": safe_debug(
                debug_result.get("aiInput")
            ),
            "aiOutput": safe_debug(
                debug_result.get("aiOutput")
            ),
            "aiDecision": safe_debug(
                debug_result.get("aiDecision")
            ),
            "aiReason": safe_debug(
                debug_result.get("consensusReason")
            ),
            "aiHoldReason": safe_debug(
                debug_result.get("aiHoldReason")
            ),
            "llmDebug": {
                "input": safe_debug(
                    debug_result.get("llmInput")
                ),
                "output": safe_debug(
                    debug_result.get("llmOutput")
                ),
                "decision": safe_debug(
                    debug_result.get("llmDecision")
                ),
                "confidence": safe_debug(
                    debug_result.get("llmConfidence")
                ),
                "reason": safe_debug(
                    debug_result.get("llmRuleReason")
                ),
                "decisionSource": safe_debug(
                    debug_result.get("llmDecisionSource")
                ),
                "longCandidate": safe_debug(
                    debug_result.get("aiLongCandidate")
                ),
                "shortCandidate": safe_debug(
                    debug_result.get("aiShortCandidate")
                ),
                "rawSignal": safe_debug(
                    debug_result.get("aiRawSignal")
                ),
            },
            "tradeBrainDebug": {
                "aiRuntimeReached": safe_debug(
                    debug_result.get("aiRuntimeReached")
                ),
                "aiInput": safe_debug(
                    debug_result.get("aiInput")
                ),
                "aiOutput": safe_debug(
                    debug_result.get("aiOutput")
                ),
                "aiDecision": safe_debug(
                    debug_result.get("aiDecision")
                ),
                "aiHoldReason": safe_debug(
                    debug_result.get("aiHoldReason")
                ),
                "llmDecision": safe_debug(
                    debug_result.get("llmDecision")
                ),
                "llmDecisionSource": safe_debug(
                    debug_result.get("llmDecisionSource")
                ),
                "consensusReason": safe_debug(
                    debug_result.get("consensusReason")
                ),
            },
        }

    return runtime_result


def _build_llm_debug(
    latest_ai_event,
    ai_raw_signal,
    ai_decision_debug=None,
):

    def llm_debug_value(key, default=None):

        for source in (
            ai_decision_debug,
            latest_ai_event,
            ai_raw_signal,
        ):
            value = extract_value(source, key)

            if value is not None:
                return value

        return default

    llm_output = extract_value(
        ai_decision_debug,
        "llmOutput",
        extract_value(ai_raw_signal, "llm"),
    )

    llm_decision = extract_value(
        ai_decision_debug,
        "llmDecision",
        llm_output,
    )

    lstm_decision = extract_value(
        ai_raw_signal,
        "lstm",
    )

    llm_input = extract_value(
        ai_decision_debug,
        "llmInput",
        extract_value(latest_ai_event, "llmInput"),
    )

    reject_buy_reason = llm_debug_value(
        "llmRejectBuyReason"
    )

    reject_sell_reason = llm_debug_value(
        "llmRejectSellReason"
    )

    llm_hold_reason = llm_debug_value(
        "llmHoldReason"
    )

    if llm_decision == "HOLD" and llm_hold_reason is None:
        llm_hold_reason = (
            "LLM returned HOLD without exposed reason"
        )

    consensus_input = extract_value(
        ai_decision_debug,
        "consensusInput",
        extract_value(latest_ai_event, "consensusInput"),
    )

    if (
        consensus_input is None
        and (
            lstm_decision is not None
            or llm_output is not None
        )
    ):
        consensus_input = {
            "lstm": lstm_decision,
            "llm": llm_output,
        }

    consensus_reason = extract_value(
        ai_decision_debug,
        "consensusReason",
        extract_value(
            latest_ai_event,
            "consensusReason",
            extract_value(latest_ai_event, "reason"),
        ),
    )

    return {
        "llmInput": safe_debug(llm_input),
        "llmOutput": safe_debug(llm_output),
        "llmDecision": safe_debug(llm_decision),
        "llmDecisionSource": safe_debug(
            llm_debug_value("llmDecisionSource")
        ),
        "llmRuleReason": safe_debug(
            llm_debug_value("llmRuleReason")
        ),
        "llmHoldReason": safe_debug(llm_hold_reason),
        "llmRejectReason": safe_debug(
            llm_debug_value("llmRejectReason")
        ),
        "llmRuleInput": safe_debug(
            llm_debug_value("llmRuleInput")
        ),
        "llmRuleThresholds": safe_debug(
            llm_debug_value("llmRuleThresholds")
        ),
        "llmFallbackUsed": safe_debug(
            llm_debug_value("llmFallbackUsed")
        ),
        "llmFallbackReason": safe_debug(
            llm_debug_value("llmFallbackReason")
        ),
        "llmPromptSummary": safe_debug(
            llm_debug_value("llmPromptSummary")
        ),
        "llmRawOutput": safe_debug(
            llm_debug_value("llmRawOutput")
        ),
        "llmParsedOutput": safe_debug(
            llm_debug_value("llmParsedOutput")
        ),
        "llmParserResult": safe_debug(
            llm_debug_value("llmParserResult")
        ),
        "llmRejectBuyReason": safe_debug(reject_buy_reason),
        "llmRejectSellReason": safe_debug(reject_sell_reason),
        "llmConfidence": safe_debug(
            extract_value(ai_raw_signal, "llmConfidence")
        ),
        "llmScore": safe_debug(
            extract_value(ai_raw_signal, "llmScore")
        ),
        "llmProbability": safe_debug(
            extract_value(ai_raw_signal, "llmProbability")
        ),
        "consensusInput": safe_debug(consensus_input),
        "consensusReason": safe_debug(consensus_reason),
    }

# ============================================================
# TRADING RUNTIME
# ============================================================

class TradingRuntime:

    def __init__(self):

        # ----------------------------------------------------
        # Strategy Engine
        # ----------------------------------------------------

        self.strategy_engine = (
            MicrostructureEdgeStrategy()
        )

        # ----------------------------------------------------
        # Execution Runtime
        # ----------------------------------------------------

        self.execution_runtime = (
            ExecutionRuntime()
        )

        # ----------------------------------------------------
        # AI Runtime
        # ----------------------------------------------------

        self.ai_pipeline = (
            AIPipeline()
        )

        self.runtime_adapter = (
            RuntimeAdapter()
        )
        self.governance_runtime = (
            GovernanceRuntime()
        )

        # ----------------------------------------------------
        # Runtime State
        # ----------------------------------------------------

        self.runtime_healthy = True

    # ========================================================
    # PROCESS EXECUTION PIPELINE
    # ========================================================

    def process_runtime(
        self,
        microstructure_state,
    ):

        debug_result = build_runtime_debug_result()
        debug_result["momentumTrace"] = (
            _new_momentum_trace(microstructure_state)
        )
        debug_result["momentumPipelineTrace"] = (
            _new_momentum_pipeline_trace(microstructure_state)
        )
        debug_result["priceHistoryTrace"] = (
            debug_result["momentumTrace"].get(
                "priceHistoryGeneration"
            )
        )
        debug_result["aiMomentumTrace"] = safe_debug(
            extract_value(
                microstructure_state,
                "aiMomentumTrace",
            )
        )
        debug_result["liquidityInstabilityDebug"] = safe_debug(
            extract_value(
                microstructure_state,
                "liquidityInstabilityDebug",
            )
        )
        debug_result["liquidityDeteriorationDebug"] = safe_debug(
            extract_value(
                microstructure_state,
                "liquidityDeteriorationDebug",
            )
        )

        runtime_debug(
            "TradingRuntime received type=%s state=%s",
            type(microstructure_state).__name__,
            microstructure_state,
        )

        try:

            # ------------------------------------------------
            # AI Shadow Runtime
            # ------------------------------------------------

            try:

                runtime_state = (
                    self.runtime_adapter.build(
                        microstructure_state
                    )
                )

                momentum_trace = debug_result["momentumTrace"]
                missing = object()
                ai_momentum = extract_value(
                    microstructure_state,
                    "aiMomentumPersistence",
                    missing,
                )
                momentum_trace["runtimeAdapterFallbackUsed"] = (
                    ai_momentum is missing
                )
                momentum_trace["runtimeStateValue"] = safe_debug(
                    extract_value(runtime_state, "momentum_score")
                )
                momentum_pipeline_trace = debug_result[
                    "momentumPipelineTrace"
                ]
                momentum_pipeline_trace[
                    "runtimeStateMomentumScore"
                ] = safe_debug(extract_value(
                    runtime_state,
                    "momentum_score",
                ))
                _update_momentum_pipeline_trace_consistency(
                    momentum_pipeline_trace
                )
                _update_momentum_trace_consistency(
                    momentum_trace
                )

                ai_input = {
                    "runtime_state": runtime_state
                }

                debug_result["aiInput"] = safe_debug(
                    ai_input
                )

                runtime_debug(
                    "[STEP56-6][AI_INPUT] %s",
                    debug_result["aiInput"],
                )

                ai_signal, ai_events = (
                    self.ai_pipeline.decide(
                        ai_input
                    )
                )

                latest_ai_event = (
                    ai_events[-1]
                    if isinstance(ai_events, (list, tuple))
                    and ai_events
                    else None
                )

                ai_raw_signal = extract_value(
                    latest_ai_event,
                    "data",
                )

                ai_hold_reason = None

                if ai_signal == "HOLD":
                    ai_hold_reason = extract_value(
                        latest_ai_event,
                        "reason",
                    )

                debug_result.update({
                    "aiRuntimeReached": True,
                    "aiOutput": safe_debug({
                        "signal": ai_signal,
                        "events": ai_events,
                    }),
                    "aiConfidence": safe_debug(
                        extract_value(
                            latest_ai_event,
                            "confidence",
                        )
                    ),
                    "aiScore": safe_debug(
                        extract_value(
                            latest_ai_event,
                            "score",
                            extract_value(ai_raw_signal, "score"),
                        )
                    ),
                    "aiDecision": safe_debug(ai_signal),
                    "aiDirection": safe_debug(ai_signal),
                    "aiHoldReason": safe_debug(ai_hold_reason),
                    "aiLongCandidate": safe_debug(
                        extract_value(
                            latest_ai_event,
                            "longCandidate",
                            extract_value(
                                ai_raw_signal,
                                "longCandidate",
                            ),
                        )
                    ),
                    "aiShortCandidate": safe_debug(
                        extract_value(
                            latest_ai_event,
                            "shortCandidate",
                            extract_value(
                                ai_raw_signal,
                                "shortCandidate",
                            ),
                        )
                    ),
                    "aiRawSignal": safe_debug(ai_raw_signal),
                })

                ai_decision_debug = extract_value(
                    self.ai_pipeline.brain,
                    "latest_decision_debug",
                )
                llm_debug = _build_llm_debug(
                    latest_ai_event,
                    ai_raw_signal,
                    ai_decision_debug,
                )
                debug_result.update(llm_debug)

                trade_brain_input = extract_value(
                    ai_decision_debug,
                    "llmInput",
                )
                trade_brain_runtime_state = extract_value(
                    trade_brain_input,
                    "runtime_state",
                )
                llm_features = extract_value(
                    trade_brain_input,
                    "features",
                )
                llm_feature_map = extract_value(
                    llm_features,
                    "feature_map",
                )
                momentum_trace["tradeBrainValue"] = safe_debug(
                    extract_value(
                        trade_brain_runtime_state,
                        "momentum_score",
                    )
                )
                momentum_trace["tradeBrainFallbackUsed"] = False
                momentum_trace["llmEngineValue"] = safe_debug(
                    extract_value(
                        llm_debug.get("llmRuleInput"),
                        "momentum_score",
                    )
                )
                momentum_trace["llmEngineFallbackUsed"] = False
                momentum_pipeline_trace[
                    "tradeBrainInputMomentumScore"
                ] = safe_debug(extract_value(
                    trade_brain_runtime_state,
                    "momentum_score",
                ))
                momentum_pipeline_trace[
                    "llmInputMomentumScore"
                ] = safe_debug(extract_value(
                    llm_feature_map,
                    "momentum_score",
                ))
                momentum_pipeline_trace[
                    "llmRuleInputMomentumScore"
                ] = safe_debug(extract_value(
                    llm_debug.get("llmRuleInput"),
                    "momentum_score",
                ))
                _update_momentum_pipeline_trace_consistency(
                    momentum_pipeline_trace
                )
                _update_momentum_trace_consistency(
                    momentum_trace
                )

                runtime_debug(
                    "[STEP56-6][AI_OUTPUT] %s",
                    debug_result["aiOutput"],
                )

                if ai_signal == "HOLD":
                    runtime_debug(
                        "[STEP56-6][HOLD_REASON] %s",
                        debug_result["aiHoldReason"],
                    )

                runtime_debug(
                    "AI signal=%s",
                    ai_signal,
                )

            except Exception:

                logger.exception("AI SHADOW ERROR")


            # ------------------------------------------------
            # Strategy Layer
            # ------------------------------------------------

            strategy_result = (
                self.strategy_engine
                .process_microstructure_strategy(
                    microstructure_state
                )
            )

            _record_strategy_debug(
                debug_result,
                strategy_result,
            )

            runtime_debug(
                "[STEP56-6][STRATEGY] %s",
                debug_result["strategyOutput"],
            )

            runtime_debug(
                "Strategy result=%s",
                strategy_result,
            )
            strategy_state = (
                strategy_result["strategy"]
            )

            strategy_result = (
                self.strategy_engine
                .process_microstructure_strategy(
                    microstructure_state
                )
            )

            _record_strategy_debug(
                debug_result,
                strategy_result,
            )

            if not strategy_result["valid"]:

                return {
                    "valid": False,
                    "reason": (
                        "STRATEGY_FAILED"
                    ),
                    **debug_result,
                }

            strategy_state = (
                strategy_result["strategy"]
            )

            governance_input = {
                "strategy_state": strategy_state,
                "ai_signal": ai_signal,
            }

            debug_result["governanceInput"] = safe_debug(
                governance_input
            )

            runtime_debug(
                "[STEP56-6][GOV_INPUT] %s",
                debug_result["governanceInput"],
            )

            governance_decision = (
                self.governance_runtime
                .process_governance(
                    strategy_state,
                    ai_signal,
                )
            )

            governance_allowed = extract_value(
                governance_decision,
                "allowed",
            )

            governance_decision_value = extract_value(
                governance_decision,
                "decision",
            )

            if (
                governance_decision_value is None
                and governance_allowed is not None
            ):
                governance_decision_value = (
                    "ALLOW"
                    if governance_allowed
                    else "BLOCK"
                )

            debug_result.update({
                "governanceRuntimeReached": True,
                "governanceOutput": safe_debug(
                    governance_decision
                ),
                "governanceDecision": safe_debug(
                    governance_decision_value
                ),
                "governanceAllowed": safe_debug(
                    governance_allowed
                ),
                "governanceBlockedReason": safe_debug(
                    extract_value(
                        governance_decision,
                        "blockedReason",
                        extract_value(
                            governance_decision,
                            "blocked_reason",
                            extract_value(
                                governance_decision,
                                "reason",
                            ),
                        ),
                    )
                ),
            })

            runtime_debug(
                "[STEP56-6][GOV_OUTPUT] %s",
                debug_result["governanceOutput"],
            )

            runtime_debug(
                "Governance decision=%s",
                governance_decision,
            )

            # ------------------------------------------------
            # Execution Runtime
            # ------------------------------------------------

            runtime_result = (
                self.execution_runtime
                .process_execution_runtime(
                    strategy_state,
                    governance_decision,
                    current_exposure=0.0,
                )
            )

            runtime_debug(
                "Execution result=%s",
                runtime_result,
            )

            return _attach_runtime_debug(
                runtime_result,
                debug_result,
            )

        except Exception as e:

            self.runtime_healthy = False

            add_log(
                f"❌ TradingRuntime Error: {str(e)}",
                "error",
            )

            return {
                "valid": False,
                "reason": str(e),
                **debug_result,
            }


# ============================================================
# GLOBAL TRADING RUNTIME
# ============================================================

registry.trading_runtime = (
    TradingRuntime()
)
# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return {

        "status": "ok",

        "runtimeHealthy": (
            registry.trading_runtime
            .runtime_healthy
        ),
    }

# ============================================================
# STARTUP EVENT
# ============================================================

@app.on_event("startup")
async def startup_event():
    add_log("🔥 API STARTED")
    add_log("🧠 Production Execution Cognition Runtime Active")


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,

    allow_origins=[

        "*",

    ],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],
)

# ============================================================
# API IMPORTS
# ============================================================

# ------------------------------------------------------------
# API
# ------------------------------------------------------------

from backend.api import bot_api
from backend.api import summary_api
from backend.api import risk as risk_api
from backend.api import websocket as websocket_api
from backend.api import result as result_api
from backend.api import symbol as symbol_api

from backend.api.trade_preview import (
    router as preview_router
)

from backend.api.logs import (
    router as logs_router
)

# ------------------------------------------------------------
# ROUTERS
# ------------------------------------------------------------

from backend.routers.mode import (
    router as mode_router
)

from backend.routers.portfolio import (
    router as portfolio_router
)

from backend.routers.config import (
    router as config_router
)

from backend.routers import positions
# ============================================================
# ROUTER REGISTRATION
# ============================================================

# ------------------------------------------------------------
# GOVERNANCE
# ------------------------------------------------------------

app.include_router(
    governance_router
)

# ------------------------------------------------------------
# BOT
# ------------------------------------------------------------

app.include_router(
    bot_api.router,
    prefix="/api/bot"
)

app.include_router(
    summary_api.router,
    prefix="/api/bot"
)

app.include_router(
    result_api.router,
    prefix="/api/bot"
)

app.include_router(
    symbol_api.router,
    prefix="/api/bot"
)

# ------------------------------------------------------------
# MODE
# ------------------------------------------------------------

app.include_router(
    mode_router,
    prefix="/api/bot"
)

# ------------------------------------------------------------
# PORTFOLIO
# ------------------------------------------------------------

app.include_router(
    portfolio_router,
    prefix="/api/bot"
)

# ------------------------------------------------------------
# POSITIONS
# ------------------------------------------------------------

app.include_router(
    positions.router,
    prefix="/api"
)

# ------------------------------------------------------------
# TRADE PREVIEW
# ------------------------------------------------------------

app.include_router(
    preview_router,
    prefix="/api/bot"
)

# ------------------------------------------------------------
# RISK
# ------------------------------------------------------------

try:

    app.include_router(
        risk_api.router,
        prefix="/api/bot"
    )

except Exception:

    pass

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

app.include_router(
    config_router
)

# ------------------------------------------------------------
# WEBSOCKET
# ------------------------------------------------------------

app.include_router(
    websocket_api.router
)

# ------------------------------------------------------------
# LOGS
# ------------------------------------------------------------

app.include_router(
    logs_router,
    prefix="/api"
)

# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {

        "status": "ok",

        "runtime": (
            "production_execution_cognition"
        ),
    }
