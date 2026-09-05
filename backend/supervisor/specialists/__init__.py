"""Deterministic Specialist architecture for the D-6 Master/Specialist Supervisor.

This package implements the D-6 deterministic specialist layer:

    Authoritative / read-only evidence
        -> deterministic specialist evaluation
        -> typed SpecialistFinding
        -> deterministic Master aggregation (MasterSupervisorAssessment)
        -> optional bounded LLM interpretation

Every Specialist has:

    Authority             = READ_ONLY_ANALYSIS
    Operational Authority = NONE
    Mutation Authority    = NONE
"""

from .contracts import (
    CrossDomainFinding,
    MasterSupervisorAssessment,
    SourceReference,
    SpecialistFinding,
    SpecialistObservation,
    SpecialistSeverity,
    SpecialistStatus,
    reference_from_provenance,
)
from .severity import status_from_finding_severity, worst_severity, worst_status
from .system_health import SPECIALIST_ID as SYSTEM_HEALTH_SPECIALIST_ID, evaluate_system_health
from .execution import SPECIALIST_ID as EXECUTION_SPECIALIST_ID, evaluate_execution
from .money_management import SPECIALIST_ID as MONEY_MANAGEMENT_SPECIALIST_ID, evaluate_money_management
from .strategy import SPECIALIST_ID as STRATEGY_SPECIALIST_ID, evaluate_strategy
from .master import aggregate_specialists
from .bounded_context import (
    BoundedContextLimits,
    BoundedLlmContext,
    build_bounded_llm_context,
)

# Convenience aliases for the four specialist identifiers.
SPECIALIST_IDS = (
    SYSTEM_HEALTH_SPECIALIST_ID,
    EXECUTION_SPECIALIST_ID,
    MONEY_MANAGEMENT_SPECIALIST_ID,
    STRATEGY_SPECIALIST_ID,
)

__all__ = [
    "BoundedContextLimits",
    "BoundedLlmContext",
    "CrossDomainFinding",
    "MasterSupervisorAssessment",
    "SourceReference",
    "SpecialistFinding",
    "SpecialistObservation",
    "SpecialistSeverity",
    "SpecialistStatus",
    "aggregate_specialists",
    "build_bounded_llm_context",
    "evaluate_execution",
    "evaluate_money_management",
    "evaluate_strategy",
    "evaluate_system_health",
    "reference_from_provenance",
    "status_from_finding_severity",
    "worst_severity",
    "worst_status",
]
