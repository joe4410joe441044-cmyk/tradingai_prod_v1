"""Internal composition entry point for ``tradingai-context/v1``.

The composer is a pure function. It merges an existing Supervisor snapshot
with injected runtime projections and delegates the canonical pack to
``build_canonical_context``. It does not add an HTTP route, call an exchange,
or mutate runtime authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from backend.supervisor.contracts import ReadOnlySupervisorSnapshot

from .builder import RuntimeTruthSource, build_canonical_context
from .runtime_truth import read_runtime_sections
from .schema import (
    CanonicalContext,
    ContextObservation,
    FieldObservation,
    GeneratorInfo,
    ProjectTruth,
    ProvenanceEntry,
    SectionMeta,
    SourceTruth,
    ValueState,
)


def _require_snapshot(snapshot: ReadOnlySupervisorSnapshot | None) -> None:
    if snapshot is not None and not isinstance(snapshot, ReadOnlySupervisorSnapshot):
        raise TypeError("supervisor_snapshot must be a ReadOnlySupervisorSnapshot or None")


def _provenance_key(entry: ProvenanceEntry) -> tuple[str, str, str, str]:
    return (
        entry.source,
        entry.reader,
        entry.observedAt.isoformat() if entry.observedAt else "",
        entry.detail or "",
    )


def _chain(base: ContextObservation, addition: ContextObservation) -> tuple[ProvenanceEntry, ...]:
    unique: dict[tuple[str, str, str, str], ProvenanceEntry] = {}
    for entry in tuple(base.meta.provenance) + tuple(addition.meta.provenance):
        unique[_provenance_key(entry)] = entry
    return tuple(unique[key] for key in sorted(unique))


def _fail_closed(addition: Mapping[str, FieldObservation]) -> bool:
    evidence = addition.get("realOrderAllowedEvidence")
    allowed = addition.get("realOrderAllowed")
    return (
        evidence is not None
        and evidence.value == "FAIL_CLOSED"
        and allowed is not None
        and allowed.state is ValueState.UNKNOWN
    )


def merge_runtime_observation(
    base: ContextObservation, addition: ContextObservation
) -> ContextObservation:
    """Keep Supervisor fields and overlay injected runtime fields."""

    fields: dict[str, FieldObservation] = {item.name: item for item in base.fields}
    incoming = {item.name: item for item in addition.fields}
    for name in ("selectedMode", "tradeMode", "realOrderAllowed"):
        current = fields.get(name)
        nxt = incoming.get(name)
        if current is None or nxt is None or current.value == nxt.value:
            continue
        if name == "realOrderAllowed" and _fail_closed(incoming):
            continue
        fields[f"supervisor{name[:1].upper()}{name[1:]}"] = current.model_copy(
            update={"name": f"supervisor{name[:1].upper()}{name[1:]}"}
        )
    preserve_explicit_allowed = (
        _fail_closed(incoming)
        and "realOrderAllowed" in fields
        and fields["realOrderAllowed"].state is ValueState.PRESENT
        and isinstance(fields["realOrderAllowed"].value, bool)
    )
    for name, item in incoming.items():
        if preserve_explicit_allowed and name in {
            "realOrderAllowed",
            "realOrderAllowedEvidence",
        }:
            continue
        fields[name] = item
    meta = SectionMeta(
        source=addition.meta.source,
        observedAt=addition.meta.observedAt,
        freshness=addition.meta.freshness,
        availability=addition.meta.availability,
        provenance=_chain(base, addition),
        detail=addition.meta.detail,
    )
    ordered = tuple(sorted(fields.values(), key=lambda item: item.name))
    return ContextObservation(meta=meta, fields=ordered)


def _composer_generator(generator: GeneratorInfo | None) -> GeneratorInfo:
    if generator is not None:
        return generator
    base = GeneratorInfo()
    if "runtime-truth-composer" in base.components:
        return base
    return base.model_copy(
        update={"components": base.components + ("runtime-truth-composer",)}
    )


def compose_tradingai_context(
    *,
    generated_at: datetime,
    source_truth: SourceTruth | None = None,
    project_truth: ProjectTruth | None = None,
    supervisor_snapshot: ReadOnlySupervisorSnapshot | None = None,
    bot_status: Mapping[str, object] | None = None,
    account_projection: Mapping[str, object] | None = None,
    mm_projection: Mapping[str, object] | None = None,
    trading_cycle_projection: Mapping[str, object] | None = None,
    position_projection: Mapping[str, object] | None = None,
    position_account: Mapping[str, object] | None = None,
    position_mode: str | None = None,
    position_now: datetime | float | int | str | None = None,
    position_symbol: str | None = None,
    position_price: float | None = None,
    position_observation: Mapping[str, object] | None = None,
    execution_projection: Mapping[str, object] | None = None,
    generator: GeneratorInfo | None = None,
) -> CanonicalContext:
    """Compose SOURCE, RUNTIME, and PROJECT truth into one context pack.

    ``generated_at`` is the context stamp only. Runtime readers do not receive
    it and cannot use it as a producer timestamp.
    """

    _require_snapshot(supervisor_snapshot)
    base = build_canonical_context(
        generated_at=generated_at,
        source_truth=source_truth,
        runtime_truth=RuntimeTruthSource(snapshot=supervisor_snapshot),
        project_truth=project_truth,
        generator=generator,
    )
    sections = read_runtime_sections(
        bot_status=bot_status,
        account_projection=account_projection,
        mm_projection=mm_projection,
        trading_cycle_projection=trading_cycle_projection,
        position_projection=position_projection,
        position_account=position_account,
        position_mode=position_mode,
        position_now=position_now,
        position_symbol=position_symbol,
        position_price=position_price,
        position_observation=position_observation,
        execution_projection=execution_projection,
    )
    if not sections:
        return base
    extras = {
        name: merge_runtime_observation(getattr(base, name), observation)
        for name, observation in sections.items()
    }
    return build_canonical_context(
        generated_at=generated_at,
        source_truth=source_truth,
        runtime_truth=RuntimeTruthSource(snapshot=supervisor_snapshot, extra=extras),
        project_truth=project_truth,
        generator=_composer_generator(generator),
    )
