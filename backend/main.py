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



# ============================================================
# LOG
# ============================================================

from backend.utils.log_buffer import add_log

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

        print(
            "[TRADING_RUNTIME] PROCESS START"
        )

        print(
            "[TRADING_RUNTIME] MICRO:",
            microstructure_state
        )


        print(
            "RUNTIME INPUT TYPE:",
            type(microstructure_state)
        )

        print(
            "RUNTIME INPUT:",
            microstructure_state
        )

        print(
            "RUNTIME INPUT TYPE:",
            type(microstructure_state)
        )

        print(
            "RUNTIME INPUT:",
            microstructure_state
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

                ai_signal, ai_events = (
                    self.ai_pipeline.decide({
                        "runtime_state": runtime_state
                    })
                )

                print(
                    f"AI SIGNAL: {ai_signal}"
                )

                add_log(
                    f"AI SIGNAL: {ai_signal}"
                )

            except Exception as e:

                import traceback

                traceback.print_exc()

                print(
                    f"AI SHADOW ERROR: {e}"
                )

                add_log(
                    f"AI SHADOW ERROR: {e}"
                )


            # ------------------------------------------------
            # Strategy Layer
            # ------------------------------------------------

            strategy_result = (
                self.strategy_engine
                .process_microstructure_strategy(
                    microstructure_state
                )
            )

            print(
                "STRATEGY RESULT:",
                strategy_result,
            )
            strategy_state = (
                strategy_result["strategy"]
            )

            print(
                "[TRADING_RUNTIME] STRATEGY:",
                strategy_state
            )

            print(
                "STRATEGY STATE:",
                strategy_state,
            )
            
            strategy_result = (
                self.strategy_engine
                .process_microstructure_strategy(
                    microstructure_state
                )
            )

            if not strategy_result["valid"]:

                return {
                    "valid": False,
                    "reason": (
                        "STRATEGY_FAILED"
                    ),
                }

            strategy_state = (
                strategy_result["strategy"]
            )
            governance_decision = (
                self.governance_runtime
                .process_governance(
                    strategy_state,
                    ai_signal,
                )
            )

            print(
                "[TRADING_RUNTIME] GOVERNANCE:",
                governance_decision
            )

            print(
                f"GOVERNANCE: {governance_decision}"
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

            print(
                "[TRADING_RUNTIME] EXECUTION:",
                runtime_result
            )

            return runtime_result

        except Exception as e:

            self.runtime_healthy = False

            add_log(
                f"❌ TradingRuntime Error: {str(e)}"
            )

            return {
                "valid": False,
                "reason": str(e),
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
    print(">>> STARTUP EVENT ENTERED", flush=True)

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
    