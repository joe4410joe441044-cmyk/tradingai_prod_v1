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
    })


def _attach_runtime_debug(runtime_result, debug_result):

    if isinstance(runtime_result, dict):
        runtime_result.update(debug_result)

    return runtime_result


def _build_llm_debug(
    latest_ai_event,
    ai_raw_signal,
    ai_decision_debug=None,
):

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

    reject_buy_reason = extract_value(
        latest_ai_event,
        "llmRejectBuyReason",
        extract_value(ai_raw_signal, "llmRejectBuyReason"),
    )

    reject_sell_reason = extract_value(
        latest_ai_event,
        "llmRejectSellReason",
        extract_value(ai_raw_signal, "llmRejectSellReason"),
    )

    llm_hold_reason = extract_value(
        latest_ai_event,
        "llmHoldReason",
        extract_value(ai_raw_signal, "llmHoldReason"),
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
        "llmHoldReason": safe_debug(llm_hold_reason),
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

                debug_result.update(
                    _build_llm_debug(
                        latest_ai_event,
                        ai_raw_signal,
                        extract_value(
                            self.ai_pipeline.brain,
                            "latest_decision_debug",
                        ),
                    )
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
