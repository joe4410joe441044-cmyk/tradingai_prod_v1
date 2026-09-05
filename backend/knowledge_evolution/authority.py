"""Authority vocabulary and mutation proof for the D-8 Knowledge Evolution pipeline.

The D-8 pipeline has a strictly bounded, non-operational authority ladder.  No
D-8 object carries operational, execution, governance, MM, strategy, canonical
or order authority.  This module defines the authority labels and a
deterministic mutation-surface proof so failures to contain authority are loud.

Truth hierarchy (never inverted):

    1. CANONICAL_SPECIFICATION
    2. CURRENT_SOURCE_RUNTIME
    3. VALIDATED_KNOWLEDGE
    4. OBSERVATION_FINDING
    5. HYPOTHESIS

Experience Memory is historical evidence, NOT current runtime and NOT
validated knowledge.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from backend.knowledge_core.core import mutation_interface_names


class KnowledgeEvolutionAuthority(str, Enum):
    """Explicit authority labels carried by D-8 objects.

    ``None``-like labels are rendered as strings; no D-8 object grants any
    operational capability.
    """

    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    ANALYSIS_ONLY = "ANALYSIS_ONLY"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"
    HYPOTHESIS_ONLY = "HYPOTHESIS_ONLY"
    INFORMATION_ONLY = "INFORMATION_ONLY"
    READ_ONLY = "READ_ONLY"
    READ_ONLY_ANALYSIS = "READ_ONLY_ANALYSIS"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    NONE = "NONE"


# --------------------------------------------------------------------------- #
# Named authority constants (the contract in task section 44).
# --------------------------------------------------------------------------- #
EXPERIENCE_MEMORY_AUTHORITY = KnowledgeEvolutionAuthority.EVIDENCE_ONLY
INVESTIGATION_AUTHORITY = KnowledgeEvolutionAuthority.ANALYSIS_ONLY
PATTERN_AUTHORITY = KnowledgeEvolutionAuthority.OBSERVATION_ONLY
FINDING_AUTHORITY = KnowledgeEvolutionAuthority.OBSERVATION_ONLY
HYPOTHESIS_AUTHORITY = KnowledgeEvolutionAuthority.HYPOTHESIS_ONLY
VALIDATION_AUTHORITY = KnowledgeEvolutionAuthority.ANALYSIS_ONLY
VALIDATED_KNOWLEDGE_AUTHORITY = KnowledgeEvolutionAuthority.INFORMATION_ONLY
KNOWLEDGE_PROMOTION_AUTHORITY = KnowledgeEvolutionAuthority.HUMAN_REVIEW_REQUIRED
ADVISOR_AUTHORITY = KnowledgeEvolutionAuthority.READ_ONLY
SUPERVISOR_AUTHORITY = KnowledgeEvolutionAuthority.READ_ONLY_ANALYSIS
OPERATIONAL_AUTHORITY = KnowledgeEvolutionAuthority.NONE
EXECUTION_AUTHORITY = KnowledgeEvolutionAuthority.NONE
STRATEGY_MUTATION_AUTHORITY = KnowledgeEvolutionAuthority.NONE
MONEY_MANAGEMENT_MUTATION_AUTHORITY = KnowledgeEvolutionAuthority.NONE
CANONICAL_MUTATION_AUTHORITY = KnowledgeEvolutionAuthority.NONE

# Operational mutation verbs that must NEVER appear on a D-8 object surface.
_MUTATION_VERBS = frozenset({
    "submit", "cancel", "replace", "order", "enable", "disable", "start", "stop",
    "lock", "unlock", "override", "place", "execute", "mutate", "set", "update",
    "delete", "remove", "append", "add", "put", "promote", "change", "force",
    "write", "clear", "reset", "restore", "recover", "dispatch", "apply",
    "switch", "approve_live", "confirm", "emergency", "deploy", "restart",
})


def mutation_interfaces(obj: Any) -> tuple[str, ...]:
    """Return the public callable/mapping names on ``obj`` that look mutative.

    Empty tuple proves no mutation surface.  The D-7 ``mutation_interface_names``
    is extended here with the D-8-aware verbs above.
    """
    base = mutation_interface_names(obj)
    found = set(base)
    for name in dir(obj):
        if name.startswith("_"):
            continue
        member = getattr(obj, name)
        if callable(member):
            stem = name.lower().rstrip("_s")
            first = stem.split("_")[0]
            if first in _MUTATION_VERBS and name not in found:
                found.add(name)
    return tuple(sorted(found))


def assert_no_mutation(obj: Any) -> None:
    """Raise ``AssertionError`` if ``obj`` exposes a mutation surface."""
    names = mutation_interfaces(obj)
    if names:
        raise AssertionError(f"mutation surface detected: {', '.join(names)}")


__all__ = [
    "ADVISOR_AUTHORITY",
    "CANONICAL_MUTATION_AUTHORITY",
    "EXECUTION_AUTHORITY",
    "EXPERIENCE_MEMORY_AUTHORITY",
    "FINDING_AUTHORITY",
    "HYPOTHESIS_AUTHORITY",
    "INVESTIGATION_AUTHORITY",
    "KNOWLEDGE_PROMOTION_AUTHORITY",
    "KnowledgeEvolutionAuthority",
    "MONEY_MANAGEMENT_MUTATION_AUTHORITY",
    "OPERATIONAL_AUTHORITY",
    "PATTERN_AUTHORITY",
    "STRATEGY_MUTATION_AUTHORITY",
    "SUPERVISOR_AUTHORITY",
    "VALIDATED_KNOWLEDGE_AUTHORITY",
    "VALIDATION_AUTHORITY",
    "assert_no_mutation",
    "mutation_interfaces",
]
