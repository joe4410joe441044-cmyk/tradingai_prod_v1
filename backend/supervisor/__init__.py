"""Public contracts and fail-closed boundaries for TradingAI Supervisors."""

from .agent_registry import REGISTRY, get_agent_registration
from .contracts import (
    CapitalCondition, Freshness, HumanAttention, MasterSupervisorDecision,
    MMSupervisorAssessment, ReadOnlySupervisorSnapshot, RiskDirection, SnapshotWarning,
    SupervisorAgentId, SupervisorMode, SupervisorState, TradingRecommendation,
)
from .failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from .conversation_contracts import (
    ConversationStatus, SupervisorConversationRequest, SupervisorConversationResponse,
)
from .conversation_service import SupervisorConversationService
from .audit_store import SupervisorAuditStore
from .history_contracts import SupervisorHistoryEvent, SupervisorHistoryPage, SupervisorReplay
from .ollama_provider import OllamaLocalProvider
from .provider_configuration import SupervisorProviderConfiguration,SupervisorProviderMode,load_supervisor_provider_configuration
from .provider_status import (
    LLMInterpretationStatus, SupervisorCoreStatus, build_provider_status,
    derive_core_status, derive_llm_status,
)
from .mm_context_builder import MMShadowContext, build_mm_shadow_context
from .mm_shadow_audit import MMShadowAuditEvent
from .mm_shadow_runtime import (
    MMShadowProviderRequest, MMShadowRuntimeResult, evaluate_mm_shadow,
)
from .master_context_builder import MasterShadowContext, build_master_shadow_context
from .master_shadow_audit import MasterShadowAuditEvent
from .master_shadow_runtime import (
    MasterShadowProviderRequest, MasterShadowRuntimeResult, evaluate_master_shadow,
)
from .operator_constitution import (
    ConstitutionIdentity, OperatorConstitution, TRADINGAI_OPERATOR_CONSTITUTION,
    constitution_identity,
)

__all__ = [
    "CapitalCondition", "Freshness", "HumanAttention", "MasterSupervisorDecision",
    "MMSupervisorAssessment", "ReadOnlySupervisorSnapshot", "REGISTRY", "RiskDirection",
    "MMShadowAuditEvent", "MMShadowContext", "MMShadowProviderRequest",
    "MMShadowRuntimeResult", "MasterShadowAuditEvent", "MasterShadowContext",
    "MasterShadowProviderRequest", "MasterShadowRuntimeResult", "OperatorConstitution",
    "ConstitutionIdentity", "SnapshotWarning", "TRADINGAI_OPERATOR_CONSTITUTION",
    "SupervisorAgentId", "SupervisorBoundaryError", "SupervisorFailureCode", "SupervisorMode",
    "SupervisorState", "TradingRecommendation", "build_mm_shadow_context",
    "ConversationStatus", "SupervisorConversationRequest", "SupervisorConversationResponse",
    "SupervisorConversationService",
    "SupervisorAuditStore", "SupervisorHistoryEvent", "SupervisorHistoryPage", "SupervisorReplay",
    "OllamaLocalProvider", "SupervisorProviderConfiguration", "SupervisorProviderMode", "load_supervisor_provider_configuration",
    "SupervisorCoreStatus", "LLMInterpretationStatus", "build_provider_status",
    "derive_core_status", "derive_llm_status",
    "build_master_shadow_context", "constitution_identity", "evaluate_master_shadow",
    "evaluate_mm_shadow", "get_agent_registration",
]
