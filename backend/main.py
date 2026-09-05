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

import time
import json

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
from backend.bot_manager.bot_manager import (
    get_bot_manager,
    get_existing_bot_manager,
)
from backend.api.runtime import router as runtime_api_router
from backend.api.ai_advisor import (
    build_authoritative_runtime,
    create_advice_router,
    create_runtime_router,
)
from backend.ai_advisor.credential_loader import EnvironmentCredentialLoader
from backend.ai_advisor.production_composition import (
    ProviderInteractionPolicy,
    build_ai_advisor_production_composition,
)
from backend.ai_advisor.provider_failure_observation import StructuredLoggingProviderFailureObservationSink
from backend.ai_advisor.response_safety_observation import (
    StructuredLoggingResponseSafetyRejectionObservationSink,
)
from backend.ai_advisor.authoritative_knowledge import (
    load_authoritative_specifications,
)
from backend.ai_advisor.production_config_loader import (
    EnvironmentProductionConfigLoader,
)
from backend.ai_advisor.api_rate_limit import (
    AdvisorConcurrencyLimiter,
    AdvisorRateLimiter,
)
from backend.ai_advisor.browser_gateway import (
    AdvisorGatewayPreflightDenyMiddleware,
    AdvisorBrowserGatewayComposition,
    create_browser_gateway_router,
    load_browser_gateway_config,
)
from backend.ai_advisor.conversation_store import (
    AdvisorConversationStore,
)
from backend.auth.auth_config import load_operator_auth_config
from backend.auth.operator_session import OperatorSessionManager
from backend.auth.operator_auth import OperatorAuthenticator, hash_operator_credential
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.auth.csrf import OperatorCsrfProtection
from backend.auth.api import create_operator_auth_router
from backend.money_management.loss_application_registration import (
    get_money_management_config,
    start_money_management_cash_flow_runtime,
    shutdown_money_management_application,
    startup_money_management_application,
)
from backend.money_management.loss_runtime_hook import (
    register_money_management_runtime_hook,
    unregister_money_management_runtime_hook,
)
from backend.money_management.loss_execution_integration import (
    register_money_management_execution_entry_gate,
    unregister_money_management_execution_entry_gate,
)
from backend.money_management.loss_http_api import (
    register_money_management_http_boundary,
    unregister_money_management_http_boundary,
)
from backend.api.recorder_proxy import (
    create_recorder_proxy_router,
)
from backend.api.trading_trace import router as trading_trace_router
from backend.api.supervisor import router as supervisor_router

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


def _record_runtime_stage(
    debug_result,
    stage_id,
    status="OK",
    reason=None,
):
    """Record observation-only stage timing for Runtime Health Monitor."""

    debug_result.setdefault("runtimeStageTrace", {})[stage_id] = {
        "reached": True,
        "status": status,
        "reason": safe_debug(reason),
        "timestamp": time.time(),
    }


def _attach_runtime_debug(runtime_result, debug_result):
    """Attach mainline telemetry without evaluating archived AI diagnostics."""

    if not isinstance(runtime_result, dict):
        return runtime_result
    runtime_result.update(debug_result)
    runtime_result["runtimeDebug"] = {
        "tradingAiMode": "OFF",
        "tradingAiStatus": "NOT_INSTALLED",
        "aiRuntimeReached": False,
        "aiDecision": None,
        "aiFallback": None,
        "momentumTrace": safe_debug(debug_result.get("momentumTrace")),
        "priceHistoryTrace": safe_debug(debug_result.get("priceHistoryTrace")),
        "liquidityInstabilityDebug": safe_debug(
            debug_result.get("liquidityInstabilityDebug")
        ),
        "liquidityDeteriorationDebug": safe_debug(
            debug_result.get("liquidityDeteriorationDebug")
        ),
    }
    return runtime_result


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
        active_symbol=None,
        runtime_id=None,
    ):

        from backend.runtime.runtime_symbol_context import (
            build_runtime_symbol_context,
        )

        symbol_context = build_runtime_symbol_context(
            active_symbol, runtime_id,
        )
        symbol_context_payload = (
            symbol_context.to_dict() if symbol_context is not None else None
        )
        microstructure_state = dict(microstructure_state)
        if symbol_context is not None:
            microstructure_state["symbol"] = symbol_context.symbol
            microstructure_state["runtimeId"] = symbol_context.runtime_id
            microstructure_state["runtimeSymbolContext"] = symbol_context_payload

        debug_result = build_runtime_debug_result()
        debug_result["runtimeSymbolContext"] = symbol_context_payload
        _record_runtime_stage(
            debug_result,
            "trading-runtime",
            status="ACTIVE",
        )
        # Strategy telemetry remains available without constructing the
        # archived AI adapter/consensus momentum pipeline.
        debug_result["momentumTrace"] = safe_debug({
            "sourceGenerator": (
                "MicrostructureStateBuilder.compute_momentum_persistence"
            ),
            "sourceField": "microstructure_state.momentumPersistence",
            "sourceValue": extract_value(
                microstructure_state,
                "momentumPersistence",
            ),
            "sourceComputation": extract_value(
                microstructure_state,
                "momentumPersistenceDebug",
            ),
        })
        debug_result["momentumPipelineTrace"] = None
        debug_result["priceHistoryTrace"] = safe_debug(extract_value(
            microstructure_state,
            "priceHistoryGenerationDebug",
        ))
        debug_result["aiMomentumTrace"] = None
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

            # Trading AI is an optional subsystem. No implementation is
            # installed and no archived heuristic is invoked or used as a
            # fallback by the production mainline.
            debug_result.update({
                "tradingAiMode": "OFF",
                "tradingAiStatus": "NOT_INSTALLED",
                "aiRuntimeReached": False,
                "aiDecision": None,
                "aiDirection": None,
                "aiConfidence": None,
                "aiHoldReason": None,
            })

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
            _record_runtime_stage(debug_result, "strategy-plugin")

            runtime_debug(
                "[STEP56-6][STRATEGY] %s",
                debug_result["strategyOutput"],
            )

            runtime_debug(
                "Strategy result=%s",
                strategy_result,
            )
            if not strategy_result["valid"]:

                return {
                    "valid": False,
                    "reason": "STRATEGY_FAILED",
                    **debug_result,
                }

            strategy_state = dict(strategy_result["strategy"])
            if symbol_context is not None:
                strategy_state["symbol"] = symbol_context.symbol
                strategy_state["runtimeId"] = symbol_context.runtime_id
                strategy_state["runtimeSymbolContext"] = symbol_context_payload

            # Authoritative mainline: Strategy → Money Management →
            # Governance → Execution. Trading AI is optional, OFF, and not
            # consulted as an approval or fallback authority.
            runtime_result = (
                self.execution_runtime.process_execution_runtime(
                    strategy_state,
                    governance_resolver=(
                        self.governance_runtime.process_governance
                    ),
                    current_exposure=0.0,
                    runtime_symbol_context=symbol_context_payload,
                )
            )

            for key in (
                "moneyManagementReached",
                "moneyManagementDecision",
                "governanceRuntimeReached",
                "governanceOutput",
                "governanceDecision",
                "governanceAllowed",
                "governanceBlockedReason",
            ):
                if key in runtime_result:
                    debug_result[key] = safe_debug(runtime_result.get(key))

            debug_result["governanceInput"] = safe_debug({
                "strategy_state": strategy_state,
                "tradingAiMode": "OFF",
                "runtimeSymbolContext": symbol_context_payload,
            })
            if runtime_result.get("governanceRuntimeReached"):
                _record_runtime_stage(
                    debug_result,
                    "governance-runtime",
                    reason=runtime_result.get("governanceBlockedReason"),
                )
            _record_runtime_stage(
                debug_result,
                "execution-runtime",
                reason=extract_value(
                    extract_value(runtime_result, "runtime", {}),
                    "reason",
                ),
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
    startup_money_management_application(app, logger=logger)
    start_money_management_cash_flow_runtime(app, logger=logger)
    saved_mm_config_provider = lambda: get_money_management_config(app)
    get_bot_manager().configure_money_management_config_provider(
        saved_mm_config_provider
    )
    get_bot_manager().configure_production_ams_read_model(
        saved_mm_config_provider
    )
    from backend.auto_market_selection.paper_production import (
        attach_production_paper_auto_selection,
    )
    attach_production_paper_auto_selection(get_bot_manager())
    register_money_management_runtime_hook(
        app,
        get_bot_manager,
        logger=logger,
    )
    register_money_management_http_boundary(
        app,
        capital_authority_provider=(
            lambda: get_bot_manager().get_official_mm_capital_authority()
        ),
    )
    register_money_management_execution_entry_gate(
        app,
        get_bot_manager,
    )


@app.on_event("shutdown")
async def shutdown_event():
    unregister_money_management_execution_entry_gate(app)
    unregister_money_management_http_boundary(app)
    unregister_money_management_runtime_hook(app, logger=logger)
    bot_manager = get_existing_bot_manager()
    if bot_manager is None:
        add_log("SHUTDOWN_SNAPSHOT_NOT_AVAILABLE: BOT_MANAGER_UNAVAILABLE")
        shutdown_money_management_application(app, logger=logger)
        return

    try:
        result = bot_manager.shutdown()
        safe_result = {
            "eventId": (
                result.get("eventId")
                if isinstance(result, dict)
                else "STOPPED_PAPER_SHUTDOWN_CAPTURE"
            ),
            "success": result.get("success") is True
            if isinstance(result, dict) else False,
            "completed": result.get("completed") is True
            if isinstance(result, dict) else False,
            "durablePersisted": result.get("durablePersisted") is True
            if isinstance(result, dict) else False,
            "stateUnknown": result.get("stateUnknown") is not False
            if isinstance(result, dict) else True,
            "reason": result.get("reason")
            if isinstance(result, dict) else "SHUTDOWN_RESULT_INVALID",
            "captureAttempted": result.get("captureAttempted") is True
            if isinstance(result, dict) else False,
            "captureSucceeded": result.get("captureSucceeded") is True
            if isinstance(result, dict) else False,
            "shutdownRuntimeInstanceId": result.get(
                "shutdownRuntimeInstanceId"
            ) if isinstance(result, dict) else None,
            "evidenceRuntimeInstanceId": result.get(
                "evidenceRuntimeInstanceId"
            ) if isinstance(result, dict) else None,
            "runtimeInstanceId": result.get("runtimeInstanceId")
            if isinstance(result, dict) else None,
            "generation": result.get("generation")
            if isinstance(result, dict) else None,
            "capturedAt": result.get("capturedAt")
            if isinstance(result, dict) else None,
            "originMode": result.get("originMode")
            if isinstance(result, dict) else "NO_DURABLE_EVIDENCE",
            "evidenceReused": result.get("evidenceReused") is True
            if isinstance(result, dict) else False,
        }
        logger.info(
            "Shutdown safety capture: %s",
            json.dumps(safe_result, sort_keys=True, separators=(",", ":")),
        )
    except Exception as exc:
        logger.error("SNAPSHOT_PERSIST_FAILED during shutdown: %s", exc)

    shutdown_money_management_application(app, logger=logger)


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
# OPERATOR AUTHENTICATION
# ============================================================

_auth_config = load_operator_auth_config()
_auth_configured = (
    _auth_config.credential_hash is not None
    and _auth_config.session_secret is not None
)

if _auth_configured:
    try:
        _session_manager = OperatorSessionManager(
            _auth_config.session_secret,
            _auth_config.session_ttl_seconds,
        )
        _authenticator = OperatorAuthenticator(_auth_config.credential_hash)
    except ValueError:
        _auth_configured = False

if _auth_configured:
    app.add_middleware(
        OperatorSessionMiddleware,
        session_manager=_session_manager,
        config=_auth_config,
    )

    _csrf_protected = frozenset({
        "/api/auth/logout",
        "/api/ai-advisor/conversation",
        "/api/ai-advisor/conversation/clear",
        "/api/bot/start",
        "/api/bot/stop",
        "/api/bot/loop/start",
        "/api/bot/loop/stop",
        "/api/bot/live-auto/approve",
        "/api/bot/live-auto/start",
        "/api/bot/live-auto/stop",
        "/api/bot/paper-account/capital",
        "/api/governance/mode",
        "/api/governance/execution",
        "/api/governance/risk-profile",
        "/api/governance/emergency-stop",
        "/api/governance/emergency-orchestrate",
        "/api/governance/emergency/unlock",
        "/api/governance/emergency/retry",
        "/api/runtime/stopped-paper-safety/refresh",
        "/api/runtime/paper-auto/start",
        "/api/runtime/paper-auto/cycle",
        "/api/runtime/paper-auto/stop",
    })
    app.add_middleware(
        OperatorCsrfProtection,
        csrf_required_paths=_csrf_protected,
    )
else:
    _session_manager = None
    _authenticator = None

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
from backend.api.money_management import (
    router as money_management_router,
)

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

app.include_router(
    runtime_api_router
)

app.include_router(
    money_management_router
)

app.include_router(
    create_recorder_proxy_router()
)

app.include_router(trading_trace_router)

app.include_router(supervisor_router)

_ai_advisor_production = build_ai_advisor_production_composition(
    provider_interaction_policy=ProviderInteractionPolicy.INTERACTIVE,
    config_loader=EnvironmentProductionConfigLoader(),
    authentication_credential_loader=EnvironmentCredentialLoader(
        ("AI_ADVISOR_AUTH_TOKEN",),
    ),
    provider_credential_loader=EnvironmentCredentialLoader(
        ("OPENAI_API_KEY",),
    ),
    allowed_authentication_credential_ids=(
        "AI_ADVISOR_AUTH_TOKEN",
    ),
    allowed_provider_credential_ids=(
        "OPENAI_API_KEY",
    ),
    failure_observation_sink=StructuredLoggingProviderFailureObservationSink(),
    response_safety_observation_sink=(
        StructuredLoggingResponseSafetyRejectionObservationSink()
    ),
)

app.include_router(
    create_runtime_router(
        _ai_advisor_production.apiComposition,
    ),
    prefix="/api/ai-advisor",
)

app.include_router(
    create_advice_router(
        _ai_advisor_production.apiComposition,
    ),
    prefix="/api/ai-advisor",
)

_ai_advisor_browser_config = load_browser_gateway_config()
try:
    _ai_advisor_conversation_store = AdvisorConversationStore()
except Exception:
    # Conversation memory must never break core TradingAI startup.  A storage
    # failure degrades the Advisor to an empty (fresh) conversation instead of
    # affecting BOT / Loop / Execution / MM / Governance / Emergency.
    _ai_advisor_conversation_store = None
app.include_router(
    create_browser_gateway_router(
        AdvisorBrowserGatewayComposition(
            config=_ai_advisor_browser_config,
            service=_ai_advisor_production.apiComposition.service,
            rateLimiter=AdvisorRateLimiter(
                limit=_ai_advisor_production.apiComposition.config.rateLimitRequests,
                window_seconds=(
                    _ai_advisor_production.apiComposition.config.rateLimitWindowSeconds
                ),
                clock=time.monotonic,
            ),
            concurrencyLimiter=AdvisorConcurrencyLimiter(
                limit=_ai_advisor_production.apiComposition.config.concurrencyLimit,
                acquire_timeout_seconds=(
                    _ai_advisor_production.apiComposition.config
                    .concurrencyAcquireTimeoutSeconds
                ),
            ),
            externalStatus=(
                "AVAILABLE"
                if (
                    _ai_advisor_production.operationalStatus.networkReady is True
                    and _ai_advisor_production.operationalStatus.providerReady is True
                )
                else "OFFLINE"
            ),
            approvedSpecifications=load_authoritative_specifications(),
            runtimeSource=lambda: build_authoritative_runtime(app),
            conversationStore=_ai_advisor_conversation_store,
        )
    )
)
app.add_middleware(AdvisorGatewayPreflightDenyMiddleware)

if _auth_configured and _authenticator is not None and _session_manager is not None:
    app.include_router(
        create_operator_auth_router(
            _authenticator,
            _session_manager,
            _auth_config,
        ),
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
