"""In-memory one-shot orchestration of recovered state and Phase 1 results.

Pure reduction (``reduce_monitoring_state``) never persists, never schedules and
never notifies.  Persistence happens only when an explicit store method is
invoked through :class:`MonitoringStateService`.
"""
from __future__ import annotations

from pydantic import Field, field_validator

from .drift_evaluator import DriftResult
from .monitoring_models import Contract, Dimension, Token
from .monitoring_state_models import (
    AnomalyState, CooldownPolicy, MonitoringCycleResult, RecoveryResult,
    StateEvent, Suppression, build_identity,
)
from .monitoring_state_store import AppendOutcome, MonitoringStateStore
from .monitoring_state_transitions import apply_acknowledgement, transition


class AnomalyObservation(Contract):
    """A Phase 1 drift result plus the canonical grouping the state layer needs."""

    result: DriftResult
    grouping: tuple[Dimension, ...] = Field(default=(), max_length=16)
    source_revision: Token | None = None

    @field_validator("grouping")
    @classmethod
    def groups(cls, value):
        if len({v.key for v in value}) != len(value):
            raise ValueError("duplicate grouping key")
        return tuple(sorted(value, key=lambda d: d.key))


def observe(result: DriftResult, *, grouping=(), source_revision=None) -> AnomalyObservation:
    return AnomalyObservation(result=result, grouping=tuple(grouping),
                              source_revision=source_revision)


def _event(transition_result, *, occurred_at, evaluation_id, observation_id) -> StateEvent:
    state = transition_result.state
    return StateEvent(
        occurred_at=occurred_at, fingerprint=state.fingerprint, episode_number=state.episode_number,
        evaluation_id=evaluation_id, observation_id=observation_id,
        transition=transition_result.transition,
        notification_eligible=transition_result.notification_eligible,
        suppression_reason=transition_result.suppression_reason,
        reason_codes=transition_result.reason_codes, state=state,
    )


def reduce_monitoring_state(observations, previous_states=(), *, evaluated_at,
                            cooldown_policy: CooldownPolicy | None = None,
                            acknowledgements=(), recovery: RecoveryResult | None = None,
                            ) -> MonitoringCycleResult:
    """Pure deterministic reduction; no persistence and no side effects."""

    cooldown = cooldown_policy or CooldownPolicy()
    current: dict[str, AnomalyState] = {s.fingerprint: s for s in previous_states}
    by_lineage = {s.episode_key: s.fingerprint for s in previous_states}
    by_family = {s.family: s.fingerprint for s in previous_states}
    transitions = []
    events = []
    eligible: set[str] = set()
    suppressed = []
    warnings: set[str] = set()

    def apply(tr, evaluation_id, observation_id):
        transitions.append(tr)
        if tr.state is not None:
            current[tr.state.fingerprint] = tr.state
            by_lineage[tr.state.episode_key] = tr.state.fingerprint
            by_family[tr.state.family] = tr.state.fingerprint
        if tr.conflict:
            warnings.add("DEDUP_CONFLICT")
        if tr.notification_eligible:
            eligible.add(tr.fingerprint)
        if tr.suppression_reason:
            severity = tr.state.current_severity if tr.state is not None else "NONE"
            suppressed.append(Suppression(fingerprint=tr.fingerprint, severity=severity,
                                          reason=tr.suppression_reason))
        if tr.persistence_required and tr.state is not None:
            events.append(_event(tr, occurred_at=evaluated_at, evaluation_id=evaluation_id,
                                 observation_id=observation_id))

    for ack in acknowledgements:
        previous = current.get(ack.fingerprint)
        tr = apply_acknowledgement(previous, ack, evaluated_at=evaluated_at, cooldown=cooldown)
        evaluation_id = ack.expected_event_id or f"ack:{ack.fingerprint}:{ack.acknowledged_at.isoformat()}"
        observation_id = previous.last_observation_id if previous is not None else ack.fingerprint
        apply(tr, evaluation_id, observation_id)

    ordered = sorted(observations, key=lambda o: (o.result.metric, o.result.observation_id))
    for item in ordered:
        result = item.result
        identity = build_identity(result, grouping=item.grouping)
        previous = current.get(identity.fingerprint)
        if previous is None and identity.lineage in by_lineage:
            previous = current.get(by_lineage[identity.lineage])
        if previous is None and identity.family in by_family:
            previous = current.get(by_family[identity.family])
        tr = transition(previous, result, evaluated_at=evaluated_at, cooldown=cooldown,
                        grouping=item.grouping, revision=item.source_revision)
        observation_id = tr.state.last_observation_id if tr.state is not None else identity.fingerprint
        apply(tr, result.observation_id, observation_id)

    if recovery is not None:
        if recovery.partial:
            warnings.add("RECOVERY_PARTIAL")
        if recovery.corruption_count:
            warnings.add("RECOVERY_CORRUPTION_ISOLATED")

    return MonitoringCycleResult(
        states=tuple(sorted(current.values(), key=lambda s: s.fingerprint)),
        transitions=tuple(transitions), eligible_for_notification=tuple(eligible),
        suppressed=tuple(sorted(suppressed, key=lambda s: (s.fingerprint, s.reason))),
        events=tuple(events), warnings=tuple(warnings), recovery=recovery,
    )


class MonitoringStateService:
    """Thin orchestration over an explicit, restart-safe state store."""

    def __init__(self, *, store: MonitoringStateStore, cooldown: CooldownPolicy | None = None):
        if not isinstance(store, MonitoringStateStore):
            raise TypeError("an explicit MonitoringStateStore is required")
        self.store = store
        self.cooldown = cooldown or CooldownPolicy()

    def reduce(self, observations, *, evaluated_at, acknowledgements=()) -> MonitoringCycleResult:
        recovery = self.store.recover()
        return reduce_monitoring_state(
            observations, recovery.states, evaluated_at=evaluated_at,
            cooldown_policy=self.cooldown, acknowledgements=acknowledgements, recovery=recovery)

    def persist(self, cycle: MonitoringCycleResult):
        return [self.store.append(event) for event in cycle.events]

    def run(self, observations, *, evaluated_at, acknowledgements=()) -> MonitoringCycleResult:
        cycle = self.reduce(observations, evaluated_at=evaluated_at,
                            acknowledgements=acknowledgements)
        outcomes = self.persist(cycle)
        warnings = set(cycle.warnings)
        if any(o.outcome is AppendOutcome.CONFLICT for o in outcomes):
            warnings.add("PERSISTENCE_CONFLICT")
        if any(not o.written and not o.idempotent for o in outcomes):
            warnings.add("PERSISTENCE_REJECTED")
        return cycle.model_copy(update={"warnings": tuple(sorted(warnings))})
