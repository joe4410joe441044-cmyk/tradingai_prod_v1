"""Knowledge Core authority vocabulary.

These enums are descriptive *metadata* used to describe existing components
and sources.  They do not grant authority; the Knowledge Core itself has
``KnowledgeAuthority.INFORMATION_ONLY`` and defines no execution/action
interface.
"""

from __future__ import annotations

from enum import Enum


class KnowledgeAuthority(str, Enum):
    """Authority carried by a Knowledge Core object.

    Every Knowledge Core object is INFORMATION_ONLY.  It describes truth, it
    does not hold runtime authority.
    """

    INFORMATION_ONLY = "INFORMATION_ONLY"


class TruthLevel(str, Enum):
    """Truth hierarchy for Knowledge Provenance.

    Order matters: lower enum value is higher truth priority.

    1. CANONICAL_SPECIFICATION
    2. CURRENT_SOURCE_RUNTIME
    3. VALIDATED_KNOWLEDGE
    4. OBSERVATION_FINDING
    5. HYPOTHESIS
    """

    CANONICAL_SPECIFICATION = "CANONICAL_SPECIFICATION"
    CURRENT_SOURCE_RUNTIME = "CURRENT_SOURCE_RUNTIME"
    VALIDATED_KNOWLEDGE = "VALIDATED_KNOWLEDGE"
    OBSERVATION_FINDING = "OBSERVATION_FINDING"
    HYPOTHESIS = "HYPOTHESIS"


TRUTH_PRIORITY = {
    TruthLevel.CANONICAL_SPECIFICATION: 1,
    TruthLevel.CURRENT_SOURCE_RUNTIME: 2,
    TruthLevel.VALIDATED_KNOWLEDGE: 3,
    TruthLevel.OBSERVATION_FINDING: 4,
    TruthLevel.HYPOTHESIS: 5,
}


class SourceCategory(str, Enum):
    """Source Index categories.

    Mirrors the D-1 minimum source categories.
    """

    SPECIFICATION = "SPECIFICATION"
    SOURCE_CODE = "SOURCE_CODE"
    RUNTIME = "RUNTIME"
    API = "API"
    CONTRACT = "CONTRACT"
    TEST = "TEST"
    HISTORY = "HISTORY"


class AuthorityClass(str, Enum):
    """Runtime authority class of a *described component*.

    This describes the system being indexed, NOT the Knowledge Core.  The
    Knowledge Core never takes one of these values itself.
    """

    EXECUTION_AUTHORITY = "EXECUTION_AUTHORITY"
    GOVERNANCE_AUTHORITY = "GOVERNANCE_AUTHORITY"
    CONFIGURATION_AUTHORITY = "CONFIGURATION_AUTHORITY"
    RECORDING_AUTHORITY = "RECORDING_AUTHORITY"
    OBSERVATION_READ_ONLY = "OBSERVATION_READ_ONLY"
    RESEARCH_READ_ONLY = "RESEARCH_READ_ONLY"
