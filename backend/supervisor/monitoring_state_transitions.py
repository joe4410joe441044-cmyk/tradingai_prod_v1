"""Pure deterministic anomaly lifecycle transition engine.

No clock, no I/O, no notification delivery and no trading authority.  The input
state is never mutated; a new validated state (or an explicit no-op result) is
returned.  Cooldown only affects notification eligibility, never anomaly
visibility and never trading authority.
"""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

from .drift_evaluator import DriftResult
from .monitoring_models import aware
from .monitoring_state_models import (
    AnomalyState, Acknowledgement, CooldownPolicy, NOTIFIABLE_SEVERITIES,
    TransitionResult, build_identity, is_degraded, observation_identity,
    severity_rank, source_revision as source_revision_of,
)

_AVAILABILITY_PRIORITY = (
    "UNAVAILABLE", "INVALID", "ERROR", "PARTIAL", "NOT_CAPTURED", "NOT_APPLICABLE",
    "EMPTY", "NOT_AVAILABLE", "UNSUPPORTED_FILTER", "AVAILABLE",
)


def _freshness(result: DriftResult) -> str:
    for value in ("STALE", "UNKNOWN", "FRESH", "NOT_APPLICABLE"):
        if value in result.freshness:
            return value
    return "UNKNOWN"


def _availability(result: DriftResult) -> str:
    for value in _AVAILABILITY_PRIORITY:
        if value in result.availability:
            return value
    return "UNAVAILABLE"


def _content_digest(result: DriftResult, fingerprint: str) -> str:
    parts = (fingerprint, result.state, result.severity, str(result.partial_result),
             _freshness(result), _availability(result), "|".join(sorted(result.reason_codes)))
    return sha256(":".join(parts).encode("utf-8")).hexdigest()


def _cooldown_deadline(now, severity: str, cooldown: CooldownPolicy):
    seconds = cooldown.seconds_for(severity)
    return now + timedelta(seconds=seconds) if seconds else None


def _created(identity, result: DriftResult, *, now, observation_id, revision, severity):
    return AnomalyState(
        fingerprint=identity.fingerprint, episode_key=identity.lineage, family=identity.family,
        metric=result.metric,
        metric_version=result.metric_version, grouping=identity.grouping,
        policy_version=result.policy_version, source_revision=revision, category=result.category,
        lifecycle_state="NEW", current_severity=severity, highest_severity=severity,
        first_seen_at=now, last_seen_at=now, occurrence_count=1, consecutive_count=1,
        last_evaluation_id=result.observation_id, last_observation_id=observation_id,
        last_content_digest=_content_digest(result, identity.fingerprint), active=True,
        partial_result=result.partial_result, freshness=_freshness(result),
        availability=_availability(result), reason_codes=result.reason_codes,
    )


def _updated(previous: AnomalyState, **changes) -> AnomalyState:
    data = previous.model_dump()
    data.update(changes)
    return AnomalyState.model_validate(data)


def _result(previous, state, transition, *, eligible=False, suppression=None, reasons=(),
            persistence=False, conflict=False, duplicate=False) -> TransitionResult:
    fingerprint = state.fingerprint if state is not None else (
        previous.fingerprint if previous is not None else "")
    episode_key = state.episode_key if state is not None else (
        previous.episode_key if previous is not None else "")
    return TransitionResult(
        fingerprint=fingerprint, episode_key=episode_key, transition=transition,
        previous=previous, state=state, notification_eligible=eligible,
        suppression_reason=suppression, reason_codes=tuple(reasons),
        persistence_required=persistence, conflict=conflict, duplicate=duplicate,
    )


def apply_acknowledgement(previous: AnomalyState, acknowledgement: Acknowledgement, *,
                          evaluated_at, cooldown: CooldownPolicy) -> TransitionResult:
    """Idempotent state-level acknowledgement; never resolves or changes severity."""
    now = aware(evaluated_at)
    if previous is None or acknowledgement.fingerprint != previous.fingerprint:
        return _result(previous, None, "CONFLICT", reasons=("ACKNOWLEDGEMENT_UNKNOWN_EPISODE",),
                       conflict=True)
    if not previous.active:
        return _result(previous, previous, "CONFLICT", reasons=("ACKNOWLEDGEMENT_RESOLVED_EPISODE",),
                       conflict=True)
    if previous.acknowledged_at == acknowledgement.acknowledged_at and \
            previous.acknowledged_by == acknowledgement.actor:
        return _result(previous, previous, "ACK_REPEAT", duplicate=True)
    if acknowledgement.expected_revision is not None and \
            acknowledgement.expected_revision != previous.state_revision:
        return _result(previous, previous, "CONFLICT", reasons=("STALE_STATE_REVISION",),
                       conflict=True)
    if acknowledgement.expected_event_id is not None and \
            acknowledgement.expected_event_id != previous.last_event_id:
        return _result(previous, previous, "CONFLICT", reasons=("STALE_EVENT_IDENTITY",),
                       conflict=True)
    suppress = (previous.current_severity in NOTIFIABLE_SEVERITIES
                and now < acknowledgement.acknowledged_at + timedelta(
                    seconds=cooldown.acknowledgement_suppression_seconds))
    state = _updated(
        previous, lifecycle_state="ACKNOWLEDGED", acknowledged_at=acknowledgement.acknowledged_at,
        acknowledged_by=acknowledgement.actor, state_revision=previous.state_revision + 1,
    )
    return _result(previous, state, "ACKNOWLEDGED", eligible=False,
                   suppression="ACKNOWLEDGED" if suppress else None,
                   reasons=("ACKNOWLEDGED",) if suppress else (), persistence=True)


def _normal_observation(previous: AnomalyState, result: DriftResult, *, now,
                        cooldown: CooldownPolicy) -> TransitionResult:
    if previous.lifecycle_state == "RESOLVED":
        return _result(previous, None, "NORMAL", reasons=("NO_ACTIVE_EPISODE",))
    count = previous.consecutive_normal_count + 1
    since = previous.consecutive_normal_since or now
    span = (now - since).total_seconds()
    base = dict(
        last_seen_at=now, last_evaluation_id=result.observation_id,
        last_observation_id=observation_identity(
            result, build_identity(result, grouping=previous.grouping)),
        last_content_digest=_content_digest(result, previous.fingerprint),
        consecutive_normal_count=count, consecutive_normal_since=since,
        consecutive_count=0, state_revision=previous.state_revision + 1,
        partial_result=result.partial_result, freshness=_freshness(result),
        availability=_availability(result), reason_codes=result.reason_codes,
    )
    if count >= cooldown.resolution_consecutive_normal and span >= cooldown.resolution_span_seconds:
        state = _updated(previous, lifecycle_state="RESOLVED", active=False,
                         current_severity="NONE",
                         resolved_at=now, resolution_reason="CONSECUTIVE_NORMAL_VALID", **base)
        return _result(previous, state, "RESOLVED", suppression="RESOLVED",
                       reasons=("CONSECUTIVE_NORMAL_VALID",), persistence=True)
    state = _updated(previous, lifecycle_state="ACTIVE", **base)
    return _result(previous, state, "NORMAL", reasons=("RESOLUTION_PENDING",), persistence=True)


def _degraded_observation(previous: AnomalyState, result: DriftResult, *, now) -> TransitionResult:
    state = _updated(
        previous, lifecycle_state="UNKNOWN", last_seen_at=now,
        last_evaluation_id=result.observation_id,
        last_observation_id=observation_identity(
            result, build_identity(result, grouping=previous.grouping)),
        last_content_digest=_content_digest(result, previous.fingerprint),
        consecutive_count=0, consecutive_normal_count=0, consecutive_normal_since=None,
        state_revision=previous.state_revision + 1, partial_result=True,
        freshness=_freshness(result), availability=_availability(result),
        reason_codes=tuple(result.reason_codes) + ("DEGRADED_INPUT",),
    )
    return _result(previous, state, "DEGRADED", suppression="DEGRADED_INPUT",
                   reasons=("DEGRADED_INPUT",), persistence=True)


def _anomaly_observation(previous: AnomalyState, result: DriftResult, *, now,
                         cooldown: CooldownPolicy, revision: str,
                         prior: AnomalyState | None = None) -> TransitionResult:
    prior = prior or previous
    if previous.lifecycle_state == "RESOLVED":
        state = _created(build_identity(result, grouping=previous.grouping), result, now=now,
                         observation_id=observation_identity(
                             result, build_identity(result, grouping=previous.grouping)),
                         revision=revision, severity=result.severity)
        state = _updated(state, episode_number=previous.episode_number + 1,
                         lifecycle_state="ACTIVE", highest_severity=result.severity)
        eligible = result.severity in NOTIFIABLE_SEVERITIES and not result.partial_result
        if eligible:
            state = _updated(state, cooldown_until=_cooldown_deadline(now, result.severity, cooldown),
                             last_eligible_at=now)
        return _result(previous, state, "RECURRED", eligible=eligible,
                       reasons=("RECURRENCE",), persistence=True)

    new_rank = severity_rank(result.severity)
    prev_rank = severity_rank(previous.current_severity)
    escalated = new_rank > prev_rank
    source_changed = revision != previous.source_revision
    ack_active = previous.acknowledged_at is not None and \
        now < previous.acknowledged_at + timedelta(
            seconds=cooldown.acknowledgement_suppression_seconds)
    cooldown_active = previous.cooldown_until is not None and now < previous.cooldown_until

    reasons = set(previous.reason_codes) | set(result.reason_codes)
    changes = dict(
        last_seen_at=now, last_evaluation_id=result.observation_id,
        last_observation_id=observation_identity(
            result, build_identity(result, grouping=previous.grouping)),
        last_content_digest=_content_digest(result, previous.fingerprint),
        occurrence_count=previous.occurrence_count + 1,
        consecutive_count=previous.consecutive_count + 1,
        consecutive_normal_count=0, consecutive_normal_since=None,
        state_revision=previous.state_revision + 1, source_revision=revision,
        partial_result=result.partial_result, freshness=_freshness(result),
        availability=_availability(result),
    )
    eligible = False
    suppression = None
    if escalated:
        changes["escalation_version"] = previous.escalation_version + 1
        changes["highest_severity"] = result.severity
        changes["current_severity"] = result.severity
        changes["lifecycle_state"] = "ESCALATED"
        transition = "ESCALATED"
        eligible = result.severity in NOTIFIABLE_SEVERITIES and not result.partial_result and (
            cooldown.escalation_bypass or not cooldown_active)
        reasons.add("ESCALATION")
        if eligible:
            changes["cooldown_until"] = _cooldown_deadline(now, result.severity, cooldown)
            changes["last_eligible_at"] = now
    elif new_rank < prev_rank:
        changes["current_severity"] = previous.current_severity
        changes["lifecycle_state"] = "ACTIVE"
        transition = "REPEATED"
        reasons.add("SEVERITY_DECREASE_HELD")
        suppression = "SEVERITY_DECREASE_HELD"
    elif source_changed:
        changes["lifecycle_state"] = "ACTIVE"
        transition = "SOURCE_REVISION"
        reasons.add("SOURCE_REVISION_CHANGED")
        suppression = "SOURCE_REVISION_CHANGED"
    elif ack_active:
        changes["lifecycle_state"] = "ACKNOWLEDGED"
        transition = "ACK_REPEAT"
        reasons.add("ACKNOWLEDGED_REPEAT")
        suppression = "ACKNOWLEDGED"
    elif result.severity in NOTIFIABLE_SEVERITIES:
        if cooldown_active:
            changes["lifecycle_state"] = "SUPPRESSED"
            transition = "SUPPRESSED"
            suppression = "COOLDOWN_ACTIVE"
            reasons.add("COOLDOWN_ACTIVE")
        else:
            changes["lifecycle_state"] = "ACTIVE"
            transition = "REPEATED"
            eligible = not result.partial_result
            if eligible:
                changes["cooldown_until"] = _cooldown_deadline(now, result.severity, cooldown)
                changes["last_eligible_at"] = now
    else:
        changes["lifecycle_state"] = "ACTIVE"
        transition = "REPEATED"
        suppression = "INFO_NOT_ELIGIBLE"
    changes["reason_codes"] = tuple(reasons)
    state = _updated(previous, **changes)
    return _result(previous, state, transition, eligible=eligible, suppression=suppression,
                   reasons=reasons, persistence=True)


def transition(previous, result: DriftResult | None, *, evaluated_at, cooldown: CooldownPolicy,
               grouping=(), family: str | None = None, revision: str | None = None,
               acknowledgement: Acknowledgement | None = None) -> TransitionResult:
    """Pure transition; the input state/result are never mutated."""
    now = aware(evaluated_at)

    def run(base):
        identity = build_identity(result, grouping=grouping, family=family)
        observation_id = observation_identity(result, identity)
        source_rev = revision if revision is not None else source_revision_of(result)
        if base is None:
            if is_degraded(result):
                return _result(None, None, "DEGRADED", suppression="DEGRADED_INPUT",
                               reasons=("DEGRADED_INPUT",))
            if result.state == "NORMAL" and result.severity == "NONE":
                return _result(None, None, "NONE", reasons=("NO_ACTIVE_EPISODE",))
            state = _created(identity, result, now=now, observation_id=observation_id,
                             revision=source_rev, severity=result.severity)
            eligible = result.severity in NOTIFIABLE_SEVERITIES and not result.partial_result
            suppression = "INFO_NOT_ELIGIBLE" if result.severity == "INFO" else None
            if eligible:
                state = _updated(
                    state, cooldown_until=_cooldown_deadline(now, result.severity, cooldown),
                    last_eligible_at=now)
            return _result(None, state, "CREATED", eligible=eligible, suppression=suppression,
                           persistence=True)
        if base.fingerprint != identity.fingerprint:
            if base.episode_key == identity.lineage:
                state = _created(identity, result, now=now, observation_id=observation_id,
                                 revision=source_rev, severity=result.severity)
                eligible = result.severity in NOTIFIABLE_SEVERITIES and not result.partial_result
                return _result(base, state, "POLICY_REVISION", eligible=eligible,
                               reasons=("POLICY_EPOCH_CHANGED",), persistence=True)
            if is_degraded(result) and base.family == identity.family:
                return _degraded_observation(base, result, now=now)
            state = _created(identity, result, now=now, observation_id=observation_id,
                             revision=source_rev, severity=result.severity)
            return _result(base, state, "CREATED", persistence=True)
        if result.observation_id == base.last_evaluation_id:
            if _content_digest(result, identity.fingerprint) == base.last_content_digest:
                return _result(base, base, "DUPLICATE", duplicate=True)
            return _result(base, base, "CONFLICT",
                           reasons=("EVALUATION_CONTENT_CONFLICT",), conflict=True)
        if observation_id == base.last_observation_id:
            return _result(base, base, "DUPLICATE", duplicate=True)
        if base.lifecycle_state != "RESOLVED" and (
                result.state == "NORMAL" and result.severity == "NONE"):
            return _normal_observation(base, result, now=now, cooldown=cooldown)
        if result.state == "NORMAL" and result.severity == "NONE":
            return _result(base, None, "NONE", reasons=("NO_ACTIVE_EPISODE",))
        if base.lifecycle_state != "RESOLVED" and is_degraded(result):
            return _degraded_observation(base, result, now=now)
        if is_degraded(result):
            return _result(base, None, "DEGRADED", suppression="DEGRADED_INPUT",
                           reasons=("DEGRADED_INPUT",))
        return _anomaly_observation(base, result, now=now, cooldown=cooldown,
                                    revision=source_rev)

    if acknowledgement is not None:
        ack = apply_acknowledgement(previous, acknowledgement, evaluated_at=now, cooldown=cooldown)
        if result is None or ack.conflict:
            return ack
        base = ack.state if ack.state is not None else previous
        outcome = run(base)
        return _result(previous, outcome.state, outcome.transition,
                       eligible=outcome.notification_eligible,
                       suppression=outcome.suppression_reason,
                       reasons=tuple(outcome.reason_codes) + ("ACKNOWLEDGED",),
                       persistence=outcome.persistence_required,
                       conflict=outcome.conflict, duplicate=outcome.duplicate)
    return run(previous)
