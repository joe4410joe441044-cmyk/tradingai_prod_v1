"""Canonical 15-stage definitions and stage-input vocabulary (WORK I P0).

This module is pure reference data for the canonical cycle-evidence capture
orchestrator.  It binds the contract's fifteen lifecycle stages (§ E) to the
closed :class:`~backend.runtime.cycle_evidence.EvidenceType` vocabulary (§ G).

It reads and writes nothing, has no authority and never invents a value.  Its
only job is to resolve a caller-supplied stage (by number or by name) to the
single canonical definition, rejecting any number/name mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, FrozenSet, Mapping, Optional, Tuple

from backend.runtime.cycle_evidence import (
    EvidenceType,
    LIFECYCLE_STAGE_NAMES,
    LifecycleStage,
)

CANONICAL_STAGE_ORDER: Tuple[int, ...] = tuple(range(15))


class StageResolutionError(ValueError):
    """The stage is unknown, out of range, or the number/name disagree."""


class StageUnknownError(StageResolutionError):
    """The stage number/name is unknown or out of the canonical range."""


class StageMismatchError(StageResolutionError):
    """The supplied stage number and stage name disagree."""


@dataclass(frozen=True)
class StageDefinition:
    """One canonical lifecycle stage and the evidence types it may carry."""

    number: int
    name: str
    description: str
    evidence_types: FrozenSet[EvidenceType]


_E = EvidenceType

_STAGE_DESCRIPTIONS = {
    0: "parameter set + configured/effective revisions + unit provenance",
    1: "AUTO candidate set + selection reason",
    2: "market context observation",
    3: "feature evidence",
    4: "micro edge strategy signal / rejection",
    5: "AI decision + reason / rejection reason",
    6: "money-management decision / risk / quantity / leverage",
    7: "governance decision / permission / block reason",
    8: "intended/normalized order, exchange request, ACK, fill, fee, latency",
    9: "position state",
    10: "exit decision",
    11: "settlement / exit execution (close request + close fill)",
    12: "position closed / final exchange state",
    13: "trade / parameter performance record",
    14: "ready for next trade / cycle completion",
}

_STAGE_EVIDENCE_TYPES: Mapping[int, FrozenSet[EvidenceType]] = {
    0: frozenset({_E.PARAMETER_CONTEXT, _E.PARAMETER_REVISION, _E.PROVENANCE}),
    1: frozenset({_E.AUTO_CANDIDATE_SELECTION}),
    2: frozenset({_E.MARKET_CONTEXT}),
    3: frozenset({_E.FEATURE_EVIDENCE}),
    4: frozenset({_E.STRATEGY_SIGNAL}),
    5: frozenset({_E.AI_DECISION}),
    6: frozenset({_E.MONEY_MANAGEMENT_DECISION}),
    7: frozenset({_E.GOVERNANCE_DECISION}),
    8: frozenset(
        {
            _E.INTENDED_ORDER,
            _E.NORMALIZED_ORDER,
            _E.EXCHANGE_REQUEST,
            _E.EXCHANGE_ACK,
            _E.PARTIAL_FILL,
            _E.FILL,
            _E.REJECT,
            _E.FEE,
            _E.SLIPPAGE,
            _E.LATENCY,
        }
    ),
    9: frozenset({_E.POSITION}),
    10: frozenset({_E.EXIT_DECISION}),
    11: frozenset({_E.CLOSE_REQUEST, _E.CLOSE_FILL}),
    12: frozenset({_E.FINAL_EXCHANGE_STATE, _E.RECONCILIATION}),
    13: frozenset({_E.TRADE_PERFORMANCE, _E.GROSS_NET_PNL}),
    14: frozenset({_E.CYCLE_READINESS, _E.PROVENANCE}),
}

STAGE_DEFINITIONS: Mapping[int, StageDefinition] = {
    number: StageDefinition(
        number=number,
        name=LIFECYCLE_STAGE_NAMES[number],
        description=_STAGE_DESCRIPTIONS[number],
        evidence_types=_STAGE_EVIDENCE_TYPES[number],
    )
    for number in CANONICAL_STAGE_ORDER
}

_NAME_TO_NUMBER = {
    definition.name.upper(): definition.number
    for definition in STAGE_DEFINITIONS.values()
}


def stage_name(number: Any) -> str:
    """Return the canonical stage name for an integer stage number."""

    resolved = _number_from(number)
    return STAGE_DEFINITIONS[resolved].name


def stage_number(name: Any) -> int:
    """Return the canonical stage number for a stage name."""

    if not isinstance(name, str):
        raise StageUnknownError(f"stage name must be a string: {name!r}")
    text = name.strip().upper()
    if text not in _NAME_TO_NUMBER:
        raise StageUnknownError(f"unknown stage name: {name!r}")
    return _NAME_TO_NUMBER[text]


def allowed_evidence_types(number: Any) -> FrozenSet[EvidenceType]:
    """Return the evidence types permitted for a stage number/name."""

    resolved = _number_from(number)
    return STAGE_DEFINITIONS[resolved].evidence_types


def _number_from(value: Any) -> int:
    if isinstance(value, LifecycleStage):
        return int(value)
    if isinstance(value, bool):
        raise StageUnknownError("stage must be an integer 0..14")
    if isinstance(value, int):
        if value not in CANONICAL_STAGE_ORDER:
            raise StageUnknownError(f"stage number out of range: {value!r}")
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return _number_from(int(text))
        return stage_number(text)
    raise StageUnknownError(f"unsupported stage value: {value!r}")


def resolve_stage(
    *,
    stage: Any = None,
    stage_number: Any = None,
    stage_name: Any = None,
) -> StageDefinition:
    """Resolve a stage (number and/or name) to its canonical definition.

    A caller may pass ``stage`` (number or name), or ``stage_number`` /
    ``stage_name``.  When more than one form is supplied they must agree; any
    disagreement is rejected rather than guessed.
    """

    candidates = [
        value
        for value in (stage, stage_number, stage_name)
        if value is not None
    ]
    if not candidates:
        raise StageUnknownError("stage number or stage name is required")
    numbers = {_number_from(value) for value in candidates}
    if len(numbers) != 1:
        raise StageMismatchError(
            "stage number and stage name disagree: "
            + ", ".join(repr(value) for value in candidates)
        )
    return STAGE_DEFINITIONS[numbers.pop()]


def is_canonical_order(stages) -> bool:
    """Return whether the given stage numbers are the canonical 0..14 order."""

    try:
        values = tuple(_number_from(value) for value in stages)
    except StageResolutionError:
        return False
    return values == CANONICAL_STAGE_ORDER


def definition_for(number: Any) -> StageDefinition:
    """Return the definition for a stage number/name."""

    return STAGE_DEFINITIONS[_number_from(number)]


def optional_definition(value: Optional[Any]) -> Optional[StageDefinition]:
    """Resolve an optional stage value, returning ``None`` when absent."""

    if value is None:
        return None
    return definition_for(value)
