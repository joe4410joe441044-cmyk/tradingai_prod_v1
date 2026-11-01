"""Complete PROP evaluation provenance with no I/O or execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Optional, Tuple

from backend.accounts.models import (
    AccountId,
    AccountIdentity,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
    PropPhase,
    PropProgram,
)
from backend.prop_trading.contracts import (
    Completeness,
    EvaluationState,
    PropAccountObservation,
    PropRuleEvaluation,
    RuleOperation,
)
from backend.prop_trading.provenance import (
    RULE_EVALUATION_EVIDENCE_LINK_V2_SCHEMA_VERSION,
    CompleteEvaluationPurpose,
    DailyBaselineSource,
    SnapshotVerificationStatus,
    TradingRulesSnapshot,
    _DIGEST_RE,
    _codes,
    _enum,
    _json_value,
    _optional_ref,
    _parse_datetime,
    _positive_int,
    _ref,
    _refs,
    _serialized_tuple,
    _strict,
    _utc,
    _validate_or_set_digest,
    canonical_content_digest,
    object_content_digest,
)
from backend.prop_trading.rule_engine import (
    PROP_RULE_ENGINE_CALCULATION_VERSION,
    GainTreatment,
    PropRuleEngine,
    RuleEnginePolicy,
    RuleProfileStatus,
    RuleType,
    ThresholdBoundary,
    ValueBasis,
    trading_day_at,
)


ACTIVE_RULES_SELECTION_SCHEMA_VERSION = "tradingai-prop-active-rules-selection/v1"
REQUIRED_RULE_COVERAGE_SCHEMA_VERSION = "tradingai-prop-required-rule-coverage/v1"
COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION = "tradingai-prop-complete-evaluation-bundle/v1"
COMPLETE_EVALUATION_OUTCOME_SCHEMA_VERSION = "tradingai-prop-complete-evaluation-outcome/v1"


class SelectionPurpose(str, Enum):
    OPERATIONAL_CANDIDATE = "OPERATIONAL_CANDIDATE"
    READ_ONLY_MONITORING = "READ_ONLY_MONITORING"


class SelectionSourceKind(str, Enum):
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    OPERATOR_ASSERTED = "OPERATOR_ASSERTED"
    VERIFIED_PROCESS = "VERIFIED_PROCESS"


class SelectionConfirmationStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED_FOR_EVALUATION = "CONFIRMED_FOR_EVALUATION"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class RuleRequirementStatus(str, Enum):
    CONFIRMED_REQUIRED = "CONFIRMED_REQUIRED"
    CONFIRMED_NOT_REQUIRED = "CONFIRMED_NOT_REQUIRED"
    UNRESOLVED = "UNRESOLVED"


class RuleCoverageRole(str, Enum):
    ENTRY_RISK_GATE = "ENTRY_RISK_GATE"
    PROGRESS_ONLY = "PROGRESS_ONLY"
    POST_ENTRY_OBLIGATION = "POST_ENTRY_OBLIGATION"
    OTHER = "OTHER"


class EvaluatorSupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class OperationalCandidateStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    CANDIDATE_COMPATIBLE = "CANDIDATE_COMPATIBLE"


_SUPPORTED_RULE_CODES = frozenset(item.value for item in RuleType)


def _digest(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{name} must be a SHA-256 digest")
    return value


def _optional_datetime(name: str, value: Optional[datetime]) -> Optional[datetime]:
    return None if value is None else _utc(name, value)


def _parse_optional_datetime(name: str, value: Any) -> Optional[datetime]:
    return None if value is None else _parse_datetime(name, value)


def _policy_from_dict(data: Mapping[str, Any]) -> RuleEnginePolicy:
    names = {
        "profile_status", "required_rule_codes", "entry_gate_rule_codes",
        "observation_max_age_seconds", "future_tolerance_seconds",
        "maximum_loss_basis", "daily_loss_basis", "profit_target_basis",
        "loss_boundary", "maximum_loss_gain_treatment", "daily_loss_gain_treatment",
    }
    _strict("rule engine policy", data, names)

    def duration(name: str) -> timedelta:
        raw = data[name]
        if not isinstance(raw, str):
            raise TypeError(f"{name} must be a decimal string")
        try:
            seconds = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"{name} must be a decimal string") from exc
        if not seconds.is_finite() or seconds < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
        micros = seconds * Decimal("1000000")
        if micros != micros.to_integral_value():
            raise ValueError(f"{name} exceeds timedelta microsecond precision")
        return timedelta(microseconds=int(micros))

    return RuleEnginePolicy(
        profile_status=data["profile_status"],
        required_rule_codes=_serialized_tuple(
            "required_rule_codes", data["required_rule_codes"]
        ),
        entry_gate_rule_codes=_serialized_tuple(
            "entry_gate_rule_codes", data["entry_gate_rule_codes"]
        ),
        observation_max_age=duration("observation_max_age_seconds"),
        future_tolerance=duration("future_tolerance_seconds"),
        maximum_loss_basis=data["maximum_loss_basis"],
        daily_loss_basis=data["daily_loss_basis"],
        profit_target_basis=data["profit_target_basis"],
        loss_boundary=data["loss_boundary"],
        maximum_loss_gain_treatment=data["maximum_loss_gain_treatment"],
        daily_loss_gain_treatment=data["daily_loss_gain_treatment"],
    )


@dataclass(frozen=True)
class ActiveRulesSelection:
    schema_version: str
    selection_id: str
    selection_revision: int
    supersedes_selection_id: Optional[str]
    account_id: AccountId
    identity_revision: int
    execution_mode: ExecutionMode
    execution_venue: ExecutionVenue
    prop_program: PropProgram
    plan_id: str
    phase: PropPhase
    purpose: SelectionPurpose
    snapshot_id: str
    snapshot_digest: str
    rule_set_id: str
    rule_set_revision: int
    effective_from: datetime
    effective_to: Optional[datetime]
    selected_at: datetime
    invalidated_at: Optional[datetime]
    source_kind: SelectionSourceKind
    confirmation_status: SelectionConfirmationStatus
    selector_ref: str
    evidence_refs: Tuple[str, ...]
    unresolved_requirements: Tuple[str, ...]
    content_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != ACTIVE_RULES_SELECTION_SCHEMA_VERSION:
            raise ValueError("unsupported active rules selection schema")
        for name in (
            "selection_id", "plan_id", "snapshot_id", "rule_set_id", "selector_ref",
        ):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        object.__setattr__(
            self, "supersedes_selection_id",
            _optional_ref("supersedes_selection_id", self.supersedes_selection_id),
        )
        if self.supersedes_selection_id == self.selection_id:
            raise ValueError("selection cannot supersede itself")
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _positive_int("selection_revision", self.selection_revision)
        _positive_int("identity_revision", self.identity_revision)
        _positive_int("rule_set_revision", self.rule_set_revision)
        for name, enum_type in (
            ("execution_mode", ExecutionMode),
            ("execution_venue", ExecutionVenue),
            ("prop_program", PropProgram),
            ("phase", PropPhase),
            ("purpose", SelectionPurpose),
            ("source_kind", SelectionSourceKind),
            ("confirmation_status", SelectionConfirmationStatus),
        ):
            object.__setattr__(
                self, name, _enum(enum_type, name, getattr(self, name))
            )
        object.__setattr__(self, "snapshot_digest", _digest(
            "snapshot_digest", self.snapshot_digest
        ))
        effective_from = _utc("effective_from", self.effective_from)
        effective_to = _optional_datetime("effective_to", self.effective_to)
        if effective_to is not None and effective_to <= effective_from:
            raise ValueError("selection effective_to must follow effective_from")
        selected_at = _utc("selected_at", self.selected_at)
        invalidated_at = _optional_datetime("invalidated_at", self.invalidated_at)
        if selected_at > effective_from:
            raise ValueError("selection must be recorded by effective_from")
        if invalidated_at is not None and invalidated_at < selected_at:
            raise ValueError("selection invalidation cannot precede selection")
        object.__setattr__(self, "effective_from", effective_from)
        object.__setattr__(self, "effective_to", effective_to)
        object.__setattr__(self, "selected_at", selected_at)
        object.__setattr__(self, "invalidated_at", invalidated_at)
        evidence = _refs("evidence_refs", self.evidence_refs)
        unresolved = _codes("unresolved_requirements", self.unresolved_requirements)
        object.__setattr__(self, "evidence_refs", evidence)
        object.__setattr__(self, "unresolved_requirements", unresolved)
        if (
            self.confirmation_status
            is SelectionConfirmationStatus.CONFIRMED_FOR_EVALUATION
            and not evidence
        ):
            raise ValueError("confirmed selection requires evidence")
        _validate_or_set_digest(self, self._content_dict())

    def _content_dict(self) -> dict[str, Any]:
        return {
            name: _json_value(getattr(self, name))
            for name in self.__dataclass_fields__
            if name != "content_digest"
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "content_digest": self.content_digest}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActiveRulesSelection":
        _strict("active rules selection", data, set(cls.__dataclass_fields__))
        if not data["content_digest"]:
            raise ValueError("serialized selection requires content_digest")
        values = dict(data)
        values["account_id"] = AccountId(values["account_id"])
        for name in ("effective_from", "selected_at"):
            values[name] = _parse_datetime(name, values[name])
        for name in ("effective_to", "invalidated_at"):
            values[name] = _parse_optional_datetime(name, values[name])
        values["evidence_refs"] = _serialized_tuple(
            "evidence_refs", values["evidence_refs"]
        )
        values["unresolved_requirements"] = _serialized_tuple(
            "unresolved_requirements", values["unresolved_requirements"]
        )
        return cls(**values)


def validate_active_selection(
    *,
    selection: ActiveRulesSelection,
    account: AccountIdentity,
    snapshot: TradingRulesSnapshot,
    evaluated_at: datetime,
    expected_purpose: SelectionPurpose,
) -> None:
    if not isinstance(selection, ActiveRulesSelection):
        raise TypeError("selection must be ActiveRulesSelection")
    if not isinstance(account, AccountIdentity) or account.account_type is not AccountType.PROP:
        raise TypeError("account must be a PROP AccountIdentity")
    if not isinstance(snapshot, TradingRulesSnapshot):
        raise TypeError("snapshot must be TradingRulesSnapshot")
    moment = _utc("evaluated_at", evaluated_at)
    purpose = _enum(SelectionPurpose, "expected_purpose", expected_purpose)
    if not snapshot.binds(account):
        raise ValueError("snapshot account binding mismatch")
    if (
        selection.account_id != account.account_id
        or selection.identity_revision != account.revision
        or selection.execution_mode is not account.execution_mode
        or selection.execution_venue is not account.execution_venue
        or selection.prop_program is not account.prop_program
        or selection.phase is not account.prop_phase
        or selection.plan_id != snapshot.plan_id
    ):
        raise ValueError("selection account, plan, or phase mismatch")
    if (
        selection.snapshot_id != snapshot.snapshot_id
        or selection.snapshot_digest != snapshot.content_digest
        or selection.rule_set_id != snapshot.rule_definition.rule_set_id
        or selection.rule_set_revision != snapshot.rule_definition.rule_set_revision
    ):
        raise ValueError("selection snapshot reference mismatch")
    if selection.purpose is not purpose:
        raise ValueError("selection purpose mismatch")
    if not (
        selection.effective_from <= moment
        and (selection.effective_to is None or moment < selection.effective_to)
    ):
        raise ValueError("selection is not effective")
    if selection.selected_at > moment:
        raise ValueError("selection was not available at evaluation time")
    if selection.invalidated_at is not None and selection.invalidated_at <= moment:
        raise ValueError("selection is stale or invalidated")
    if selection.confirmation_status in {
        SelectionConfirmationStatus.REVOKED,
        SelectionConfirmationStatus.SUPERSEDED,
    }:
        raise ValueError("selection is revoked or superseded")
    if selection.confirmation_status is not SelectionConfirmationStatus.CONFIRMED_FOR_EVALUATION:
        raise ValueError("selection is not confirmed for evaluation")
    if selection.unresolved_requirements:
        raise ValueError("selection has unresolved requirements")
    if purpose is SelectionPurpose.OPERATIONAL_CANDIDATE:
        if selection.source_kind is not SelectionSourceKind.VERIFIED_PROCESS:
            raise ValueError("operational selection requires verified process evidence")
        if not snapshot.is_current_entry_eligible(moment):
            raise ValueError("snapshot is not eligible for operational selection")
        if snapshot.verified_at is None or snapshot.verified_at > selection.selected_at:
            raise ValueError("snapshot was not verified when selected")
    elif selection.source_kind is SelectionSourceKind.SYNTHETIC_FIXTURE:
        if (
            snapshot.verification_status is not SnapshotVerificationStatus.SYNTHETIC
            or account.execution_mode is ExecutionMode.LIVE
        ):
            raise ValueError("synthetic selection requires synthetic non-live snapshot")


def resolve_active_selection(
    *,
    candidates: Tuple[ActiveRulesSelection, ...],
    selection_id: str,
    account: AccountIdentity,
    snapshot: TradingRulesSnapshot,
    evaluated_at: datetime,
    expected_purpose: SelectionPurpose,
) -> ActiveRulesSelection:
    selected_id = _ref("selection_id", selection_id)
    if not isinstance(candidates, (tuple, list)):
        raise TypeError("candidates must be a tuple or list")
    if any(not isinstance(item, ActiveRulesSelection) for item in candidates):
        raise TypeError("candidates must contain ActiveRulesSelection values")
    matches = tuple(item for item in candidates if item.selection_id == selected_id)
    if len(matches) != 1:
        raise ValueError("explicit selection is missing or ambiguous")
    validate_active_selection(
        selection=matches[0],
        account=account,
        snapshot=snapshot,
        evaluated_at=evaluated_at,
        expected_purpose=expected_purpose,
    )
    return matches[0]


@dataclass(frozen=True)
class RuleCoverageItem:
    rule_code: str
    requirement_status: RuleRequirementStatus
    role: RuleCoverageRole
    support_status: EvaluatorSupportStatus
    evidence_refs: Tuple[str, ...]
    unresolved_reason_codes: Tuple[str, ...]

    def __post_init__(self) -> None:
        code = _codes("rule_code", (self.rule_code,))[0]
        object.__setattr__(self, "rule_code", code)
        for name, enum_type in (
            ("requirement_status", RuleRequirementStatus),
            ("role", RuleCoverageRole),
            ("support_status", EvaluatorSupportStatus),
        ):
            object.__setattr__(
                self, name, _enum(enum_type, name, getattr(self, name))
            )
        evidence = _refs("evidence_refs", self.evidence_refs)
        reasons = _codes("unresolved_reason_codes", self.unresolved_reason_codes)
        object.__setattr__(self, "evidence_refs", evidence)
        object.__setattr__(self, "unresolved_reason_codes", reasons)
        if self.requirement_status is RuleRequirementStatus.UNRESOLVED and not reasons:
            raise ValueError("unresolved rule requires reason codes")
        if self.requirement_status is not RuleRequirementStatus.UNRESOLVED and reasons:
            raise ValueError("resolved rule cannot carry unresolved reason codes")

    def to_dict(self) -> dict[str, Any]:
        return {name: _json_value(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleCoverageItem":
        _strict("rule coverage item", data, set(cls.__dataclass_fields__))
        values = dict(data)
        values["evidence_refs"] = _serialized_tuple(
            "evidence_refs", values["evidence_refs"]
        )
        values["unresolved_reason_codes"] = _serialized_tuple(
            "unresolved_reason_codes", values["unresolved_reason_codes"]
        )
        return cls(**values)


@dataclass(frozen=True)
class RequiredRuleCoverage:
    schema_version: str
    coverage_id: str
    account_id: AccountId
    identity_revision: int
    snapshot_id: str
    snapshot_digest: str
    plan_id: str
    phase: PropPhase
    evaluator_version: str
    assessed_at: datetime
    verification_status: SnapshotVerificationStatus
    completeness: Completeness
    evidence_refs: Tuple[str, ...]
    unresolved_requirements: Tuple[str, ...]
    items: Tuple[RuleCoverageItem, ...]
    content_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != REQUIRED_RULE_COVERAGE_SCHEMA_VERSION:
            raise ValueError("unsupported required rule coverage schema")
        for name in ("coverage_id", "snapshot_id", "plan_id", "evaluator_version"):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _positive_int("identity_revision", self.identity_revision)
        object.__setattr__(self, "snapshot_digest", _digest(
            "snapshot_digest", self.snapshot_digest
        ))
        object.__setattr__(self, "phase", _enum(PropPhase, "phase", self.phase))
        object.__setattr__(self, "assessed_at", _utc("assessed_at", self.assessed_at))
        object.__setattr__(
            self,
            "verification_status",
            _enum(SnapshotVerificationStatus, "verification_status", self.verification_status),
        )
        object.__setattr__(
            self, "completeness", _enum(Completeness, "completeness", self.completeness)
        )
        evidence = _refs("evidence_refs", self.evidence_refs)
        unresolved = _codes("unresolved_requirements", self.unresolved_requirements)
        items = tuple(self.items)
        if any(not isinstance(item, RuleCoverageItem) for item in items):
            raise TypeError("items must contain RuleCoverageItem values")
        if len({item.rule_code for item in items}) != len(items):
            raise ValueError("coverage contains duplicate rule codes")
        object.__setattr__(self, "evidence_refs", evidence)
        object.__setattr__(self, "unresolved_requirements", unresolved)
        object.__setattr__(self, "items", items)
        if self.evaluator_version != PROP_RULE_ENGINE_CALCULATION_VERSION:
            raise ValueError("coverage evaluator version is unsupported")
        for item in items:
            expected = (
                EvaluatorSupportStatus.SUPPORTED
                if item.rule_code in _SUPPORTED_RULE_CODES
                else EvaluatorSupportStatus.UNSUPPORTED
            )
            if item.support_status is not expected:
                raise ValueError("coverage support status contradicts evaluator capability")
        if self.completeness is Completeness.COMPLETE and (
            unresolved
            or any(
                item.requirement_status is RuleRequirementStatus.UNRESOLVED
                for item in items
            )
        ):
            raise ValueError("complete coverage cannot contain unresolved rules")
        if self.verification_status is SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT:
            if (
                self.completeness is not Completeness.COMPLETE
                or not evidence
                or unresolved
                or any(
                    item.requirement_status
                    is RuleRequirementStatus.CONFIRMED_REQUIRED
                    and not item.evidence_refs
                    for item in items
                )
            ):
                raise ValueError(
                    "verified account coverage requires complete evidence"
                )
        _validate_or_set_digest(self, self._content_dict())

    def _content_dict(self) -> dict[str, Any]:
        return {
            name: _json_value(getattr(self, name))
            for name in self.__dataclass_fields__
            if name != "content_digest"
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "content_digest": self.content_digest}

    def validate_policy(
        self, policy: RuleEnginePolicy, snapshot: TradingRulesSnapshot
    ) -> None:
        if not isinstance(policy, RuleEnginePolicy):
            raise TypeError("policy must be RuleEnginePolicy")
        if (
            self.account_id != snapshot.account_id
            or self.identity_revision != snapshot.identity_revision
            or self.snapshot_id != snapshot.snapshot_id
            or self.snapshot_digest != snapshot.content_digest
            or self.plan_id != snapshot.plan_id
            or self.phase is not snapshot.phase
        ):
            raise ValueError("coverage snapshot/account binding mismatch")
        selected = {
            item.rule_code
            for item in self.items
            if item.requirement_status
            in {
                RuleRequirementStatus.CONFIRMED_REQUIRED,
                RuleRequirementStatus.UNRESOLVED,
            }
        }
        if selected != set(policy.required_rule_codes):
            raise ValueError("policy required rules do not match coverage inventory")
        by_code = {item.rule_code: item for item in self.items}
        for gate in policy.entry_gate_rule_codes:
            item = by_code.get(gate)
            if item is None or item.role is not RuleCoverageRole.ENTRY_RISK_GATE:
                raise ValueError("entry gate is not evidenced as a risk gate")
        target = by_code.get(RuleType.PROFIT_TARGET.value)
        if target is not None and target.role is not RuleCoverageRole.PROGRESS_ONLY:
            raise ValueError("profit target coverage must be progress-only")

    @property
    def operationally_complete(self) -> bool:
        return (
            self.verification_status is SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT
            and self.completeness is Completeness.COMPLETE
            and not self.unresolved_requirements
            and bool(self.items)
            and all(
                item.requirement_status is not RuleRequirementStatus.UNRESOLVED
                and (
                    item.requirement_status
                    is RuleRequirementStatus.CONFIRMED_NOT_REQUIRED
                    or item.support_status is EvaluatorSupportStatus.SUPPORTED
                )
                for item in self.items
            )
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RequiredRuleCoverage":
        _strict("required rule coverage", data, set(cls.__dataclass_fields__))
        if not data["content_digest"]:
            raise ValueError("serialized coverage requires content_digest")
        values = dict(data)
        values["account_id"] = AccountId(values["account_id"])
        values["assessed_at"] = _parse_datetime("assessed_at", values["assessed_at"])
        for name in ("evidence_refs", "unresolved_requirements"):
            values[name] = _serialized_tuple(name, values[name])
        if not isinstance(values["items"], list):
            raise TypeError("items must be a list")
        values["items"] = tuple(
            RuleCoverageItem.from_dict(item) for item in values["items"]
        )
        return cls(**values)


def validate_temporal_provenance(
    *,
    purpose: CompleteEvaluationPurpose,
    evaluated_at: datetime,
    knowledge_cutoff_at: datetime,
    snapshot: TradingRulesSnapshot,
    baseline: Optional[DailyBaselineSource],
    observation: PropAccountObservation,
) -> None:
    purpose = _enum(CompleteEvaluationPurpose, "purpose", purpose)
    moment = _utc("evaluated_at", evaluated_at)
    cutoff = _utc("knowledge_cutoff_at", knowledge_cutoff_at)
    if cutoff < moment:
        raise ValueError("knowledge cutoff cannot precede evaluation")
    if purpose is not CompleteEvaluationPurpose.RETROACTIVE_ANALYSIS and cutoff != moment:
        raise ValueError("as-of evaluation requires cutoff equal to evaluated_at")
    if not (
        snapshot.applicable_from <= moment
        and (snapshot.applicable_to is None or moment < snapshot.applicable_to)
    ):
        raise ValueError("snapshot is not applicable at evaluation time")
    if snapshot.verified_at is not None and snapshot.verified_at > cutoff:
        raise ValueError("snapshot verification was unavailable at knowledge cutoff")
    if not isinstance(observation, PropAccountObservation):
        raise TypeError("observation must be PropAccountObservation")
    if observation.observed_at > cutoff:
        raise ValueError("observation source time was unavailable at knowledge cutoff")
    if observation.received_at > cutoff:
        raise ValueError("observation receipt was unavailable at knowledge cutoff")
    if baseline is None:
        return
    if baseline.effective_at > moment:
        raise ValueError("baseline effective time follows evaluation")
    if baseline.observed_at is not None and baseline.observed_at > cutoff:
        raise ValueError("baseline observation was unavailable at knowledge cutoff")
    if baseline.captured_at > cutoff:
        raise ValueError("baseline capture was unavailable at knowledge cutoff")


@dataclass(frozen=True)
class CompleteEvaluationBundle:
    schema_version: str
    bundle_id: str
    purpose: CompleteEvaluationPurpose
    account: AccountIdentity
    selection: Optional[ActiveRulesSelection]
    snapshot: TradingRulesSnapshot
    baseline: Optional[DailyBaselineSource]
    observation: PropAccountObservation
    policy: RuleEnginePolicy
    coverage: RequiredRuleCoverage
    operation: RuleOperation
    evaluated_at: datetime
    knowledge_cutoff_at: datetime
    evaluator_version: str
    content_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION:
            raise ValueError("unsupported complete evaluation bundle schema")
        object.__setattr__(self, "bundle_id", _ref("bundle_id", self.bundle_id))
        object.__setattr__(
            self, "purpose", _enum(CompleteEvaluationPurpose, "purpose", self.purpose)
        )
        if not isinstance(self.account, AccountIdentity) or self.account.account_type is not AccountType.PROP:
            raise TypeError("account must be a PROP AccountIdentity")
        if not isinstance(self.snapshot, TradingRulesSnapshot):
            raise TypeError("snapshot must be TradingRulesSnapshot")
        if self.baseline is not None and not isinstance(self.baseline, DailyBaselineSource):
            raise TypeError("baseline must be DailyBaselineSource or None")
        if not isinstance(self.observation, PropAccountObservation):
            raise TypeError("observation must be PropAccountObservation")
        if not isinstance(self.policy, RuleEnginePolicy):
            raise TypeError("policy must be RuleEnginePolicy")
        if not isinstance(self.coverage, RequiredRuleCoverage):
            raise TypeError("coverage must be RequiredRuleCoverage")
        object.__setattr__(
            self, "operation", _enum(RuleOperation, "operation", self.operation)
        )
        moment = _utc("evaluated_at", self.evaluated_at)
        cutoff = _utc("knowledge_cutoff_at", self.knowledge_cutoff_at)
        object.__setattr__(self, "evaluated_at", moment)
        object.__setattr__(self, "knowledge_cutoff_at", cutoff)
        object.__setattr__(
            self, "evaluator_version", _ref("evaluator_version", self.evaluator_version)
        )
        if self.evaluator_version != PROP_RULE_ENGINE_CALCULATION_VERSION:
            raise ValueError("bundle evaluator version is unsupported")
        if not self.snapshot.binds(self.account):
            raise ValueError("bundle snapshot account binding mismatch")
        if (
            self.observation.account_id != self.account.account_id
            or self.observation.identity_revision != self.account.revision
        ):
            raise ValueError("bundle observation account binding mismatch")
        if self.observation.currency != self.snapshot.rule_definition.currency:
            raise ValueError("bundle observation currency mismatch")
        self.coverage.validate_policy(self.policy, self.snapshot)
        if self.coverage.assessed_at > cutoff:
            raise ValueError(
                "rule coverage assessment was unavailable at knowledge cutoff"
            )
        validate_temporal_provenance(
            purpose=self.purpose,
            evaluated_at=moment,
            knowledge_cutoff_at=cutoff,
            snapshot=self.snapshot,
            baseline=self.baseline,
            observation=self.observation,
        )
        current_purposes = {
            CompleteEvaluationPurpose.READ_ONLY_CURRENT,
            CompleteEvaluationPurpose.OPERATIONAL_CANDIDATE,
        }
        if self.purpose in current_purposes:
            if self.selection is None:
                raise ValueError("current bundle requires active selection")
            expected = (
                SelectionPurpose.OPERATIONAL_CANDIDATE
                if self.purpose is CompleteEvaluationPurpose.OPERATIONAL_CANDIDATE
                else SelectionPurpose.READ_ONLY_MONITORING
            )
            validate_active_selection(
                selection=self.selection,
                account=self.account,
                snapshot=self.snapshot,
                evaluated_at=moment,
                expected_purpose=expected,
            )
        elif self.selection is not None:
            raise ValueError("historical/retroactive bundle must not use active selection")
        if (
            self.purpose is CompleteEvaluationPurpose.OPERATIONAL_CANDIDATE
            and self.operation is not RuleOperation.ENTRY
        ):
            raise ValueError("operational candidate requires ENTRY operation")
        if (
            self.purpose is CompleteEvaluationPurpose.READ_ONLY_CURRENT
            and self.operation is not RuleOperation.READ_ONLY
        ):
            raise ValueError("read-only current bundle requires READ_ONLY operation")
        daily_required = RuleType.DAILY_LOSS.value in self.policy.required_rule_codes
        if daily_required != (self.baseline is not None):
            raise ValueError("baseline presence must exactly match daily rule requirement")
        if self.baseline is not None:
            baseline = self.baseline
            if (
                baseline.account_id != self.account.account_id
                or baseline.identity_revision != self.account.revision
                or baseline.execution_mode is not self.account.execution_mode
                or baseline.execution_venue is not self.account.execution_venue
                or baseline.rules_snapshot_id != self.snapshot.snapshot_id
                or baseline.rules_snapshot_digest != self.snapshot.content_digest
                or baseline.rule_set_id != self.snapshot.rule_definition.rule_set_id
                or baseline.rule_set_revision
                != self.snapshot.rule_definition.rule_set_revision
                or baseline.currency != self.snapshot.rule_definition.currency
                or baseline.value_basis is not self.policy.daily_loss_basis
                or baseline.timezone_name
                != self.snapshot.rule_definition.day_boundary_timezone
                or baseline.day_boundary_local_time
                != self.snapshot.rule_definition.day_boundary_local_time
            ):
                raise ValueError("bundle baseline provenance mismatch")
            if baseline.trading_day != trading_day_at(
                moment, baseline.timezone_name, baseline.day_boundary_local_time
            ):
                raise ValueError("bundle baseline trading day mismatch")
            if (
                self.purpose is CompleteEvaluationPurpose.OPERATIONAL_CANDIDATE
                and baseline.verification_status
                is not SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT
            ):
                raise ValueError("operational candidate requires verified baseline")
        _validate_or_set_digest(self, self._content_dict())

    def _content_dict(self) -> dict[str, Any]:
        return {
            name: _json_value(getattr(self, name))
            for name in self.__dataclass_fields__
            if name != "content_digest"
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "content_digest": self.content_digest}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompleteEvaluationBundle":
        _strict("complete evaluation bundle", data, set(cls.__dataclass_fields__))
        if not data["content_digest"]:
            raise ValueError("serialized bundle requires content_digest")
        return cls(
            schema_version=data["schema_version"],
            bundle_id=data["bundle_id"],
            purpose=data["purpose"],
            account=AccountIdentity.from_dict(data["account"]),
            selection=(
                None
                if data["selection"] is None
                else ActiveRulesSelection.from_dict(data["selection"])
            ),
            snapshot=TradingRulesSnapshot.from_dict(data["snapshot"]),
            baseline=(
                None
                if data["baseline"] is None
                else DailyBaselineSource.from_dict(data["baseline"])
            ),
            observation=PropAccountObservation.from_dict(data["observation"]),
            policy=_policy_from_dict(data["policy"]),
            coverage=RequiredRuleCoverage.from_dict(data["coverage"]),
            operation=data["operation"],
            evaluated_at=_parse_datetime("evaluated_at", data["evaluated_at"]),
            knowledge_cutoff_at=_parse_datetime(
                "knowledge_cutoff_at", data["knowledge_cutoff_at"]
            ),
            evaluator_version=data["evaluator_version"],
            content_digest=data["content_digest"],
        )


@dataclass(frozen=True)
class RuleEvaluationEvidenceLinkV2:
    schema_version: str
    link_id: str
    bundle_id: str
    bundle_digest: str
    evaluation_id: str
    evaluation_digest: str
    purpose: CompleteEvaluationPurpose
    account_id: AccountId
    identity_revision: int
    observation_id: str
    observation_digest: str
    snapshot_id: str
    snapshot_digest: str
    baseline_id: Optional[str]
    baseline_digest: Optional[str]
    baseline_revision: Optional[int]
    policy_digest: str
    evaluated_at: datetime
    knowledge_cutoff_at: datetime
    evaluator_version: str
    result_schema_version: str
    content_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != RULE_EVALUATION_EVIDENCE_LINK_V2_SCHEMA_VERSION:
            raise ValueError("unsupported evaluation evidence link v2 schema")
        for name in (
            "link_id", "bundle_id", "evaluation_id", "observation_id",
            "snapshot_id", "evaluator_version", "result_schema_version",
        ):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        object.__setattr__(
            self, "purpose", _enum(CompleteEvaluationPurpose, "purpose", self.purpose)
        )
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _positive_int("identity_revision", self.identity_revision)
        for name in (
            "bundle_digest", "evaluation_digest", "observation_digest",
            "snapshot_digest", "policy_digest",
        ):
            object.__setattr__(self, name, _digest(name, getattr(self, name)))
        all_none = (
            self.baseline_id is None
            and self.baseline_digest is None
            and self.baseline_revision is None
        )
        all_present = (
            self.baseline_id is not None
            and self.baseline_digest is not None
            and self.baseline_revision is not None
        )
        if not (all_none or all_present):
            raise ValueError("baseline reference fields must be all present or all absent")
        if all_present:
            object.__setattr__(self, "baseline_id", _ref("baseline_id", self.baseline_id))
            object.__setattr__(
                self, "baseline_digest", _digest("baseline_digest", self.baseline_digest)
            )
            _positive_int("baseline_revision", self.baseline_revision)
        moment = _utc("evaluated_at", self.evaluated_at)
        cutoff = _utc("knowledge_cutoff_at", self.knowledge_cutoff_at)
        if cutoff < moment:
            raise ValueError("knowledge cutoff cannot precede evaluation")
        if self.purpose is not CompleteEvaluationPurpose.RETROACTIVE_ANALYSIS and cutoff != moment:
            raise ValueError("as-of evidence link requires equal cutoff and evaluation time")
        object.__setattr__(self, "evaluated_at", moment)
        object.__setattr__(self, "knowledge_cutoff_at", cutoff)
        _validate_or_set_digest(self, self._content_dict())

    def _content_dict(self) -> dict[str, Any]:
        return {
            name: _json_value(getattr(self, name))
            for name in self.__dataclass_fields__
            if name != "content_digest"
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "content_digest": self.content_digest}

    @classmethod
    def bind(
        cls,
        *, link_id: str, bundle: CompleteEvaluationBundle,
        evaluation: PropRuleEvaluation,
    ) -> "RuleEvaluationEvidenceLinkV2":
        if not isinstance(bundle, CompleteEvaluationBundle):
            raise TypeError("bundle must be CompleteEvaluationBundle")
        if not isinstance(evaluation, PropRuleEvaluation):
            raise TypeError("evaluation must be PropRuleEvaluation")
        if (
            evaluation.account_id != bundle.account.account_id
            or evaluation.observation_id != bundle.observation.observation_id
            or evaluation.rule_set_id != bundle.snapshot.rule_definition.rule_set_id
            or evaluation.rule_set_revision
            != bundle.snapshot.rule_definition.rule_set_revision
            or evaluation.evaluated_at != bundle.evaluated_at
            or evaluation.operation is not bundle.operation
            or evaluation.calculation_version != bundle.evaluator_version
        ):
            raise ValueError("evaluation does not match complete bundle")
        baseline = bundle.baseline
        return cls(
            schema_version=RULE_EVALUATION_EVIDENCE_LINK_V2_SCHEMA_VERSION,
            link_id=link_id,
            bundle_id=bundle.bundle_id,
            bundle_digest=bundle.content_digest,
            evaluation_id=evaluation.evaluation_id,
            evaluation_digest=object_content_digest(evaluation),
            purpose=bundle.purpose,
            account_id=bundle.account.account_id,
            identity_revision=bundle.account.revision,
            observation_id=bundle.observation.observation_id,
            observation_digest=object_content_digest(bundle.observation),
            snapshot_id=bundle.snapshot.snapshot_id,
            snapshot_digest=bundle.snapshot.content_digest,
            baseline_id=None if baseline is None else baseline.baseline_id,
            baseline_digest=None if baseline is None else baseline.content_digest,
            baseline_revision=None if baseline is None else baseline.revision,
            policy_digest=canonical_content_digest(bundle.policy.to_dict()),
            evaluated_at=bundle.evaluated_at,
            knowledge_cutoff_at=bundle.knowledge_cutoff_at,
            evaluator_version=evaluation.calculation_version,
            result_schema_version=evaluation.schema_version,
        )

    def validate_inputs(
        self, *, bundle: CompleteEvaluationBundle, evaluation: PropRuleEvaluation
    ) -> None:
        rebuilt = type(self).bind(
            link_id=self.link_id, bundle=bundle, evaluation=evaluation
        )
        if rebuilt != self:
            raise ValueError("evidence link v2 does not match bundle/evaluation")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleEvaluationEvidenceLinkV2":
        _strict("evaluation evidence link v2", data, set(cls.__dataclass_fields__))
        if data["schema_version"] != RULE_EVALUATION_EVIDENCE_LINK_V2_SCHEMA_VERSION:
            raise ValueError("v1 evidence link cannot be promoted to v2")
        if not data["content_digest"]:
            raise ValueError("serialized evidence link v2 requires content_digest")
        values = dict(data)
        values["account_id"] = AccountId(values["account_id"])
        values["evaluated_at"] = _parse_datetime("evaluated_at", values["evaluated_at"])
        values["knowledge_cutoff_at"] = _parse_datetime(
            "knowledge_cutoff_at", values["knowledge_cutoff_at"]
        )
        return cls(**values)


def derive_operational_candidate_status(
    *, bundle: CompleteEvaluationBundle, evaluation: PropRuleEvaluation
) -> OperationalCandidateStatus:
    """Derive the non-authoritative candidate status from canonical inputs."""

    if not isinstance(bundle, CompleteEvaluationBundle):
        raise TypeError("bundle must be CompleteEvaluationBundle")
    if not isinstance(evaluation, PropRuleEvaluation):
        raise TypeError("evaluation must be PropRuleEvaluation")
    if bundle.purpose is not CompleteEvaluationPurpose.OPERATIONAL_CANDIDATE:
        return OperationalCandidateStatus.NOT_APPLICABLE
    if not bundle.coverage.operationally_complete:
        return OperationalCandidateStatus.UNKNOWN
    if evaluation.overall_state is EvaluationState.BLOCK:
        return OperationalCandidateStatus.BLOCKED
    if (
        evaluation.overall_state is EvaluationState.PASS
        and evaluation.entry_allowed is True
    ):
        return OperationalCandidateStatus.CANDIDATE_COMPATIBLE
    return OperationalCandidateStatus.UNKNOWN


@dataclass(frozen=True)
class CompleteEvaluationOutcome:
    schema_version: str
    bundle: CompleteEvaluationBundle
    evaluation: PropRuleEvaluation
    evidence_link: RuleEvaluationEvidenceLinkV2
    operational_candidate_status: OperationalCandidateStatus
    execution_authority_granted: bool = False
    content_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != COMPLETE_EVALUATION_OUTCOME_SCHEMA_VERSION:
            raise ValueError("unsupported complete evaluation outcome schema")
        if not isinstance(self.bundle, CompleteEvaluationBundle):
            raise TypeError("bundle must be CompleteEvaluationBundle")
        if not isinstance(self.evaluation, PropRuleEvaluation):
            raise TypeError("evaluation must be PropRuleEvaluation")
        if not isinstance(self.evidence_link, RuleEvaluationEvidenceLinkV2):
            raise TypeError("evidence_link must be RuleEvaluationEvidenceLinkV2")
        object.__setattr__(
            self,
            "operational_candidate_status",
            _enum(
                OperationalCandidateStatus,
                "operational_candidate_status",
                self.operational_candidate_status,
            ),
        )
        if self.execution_authority_granted is not False:
            raise ValueError("complete outcome cannot grant execution authority")
        self.evidence_link.validate_inputs(
            bundle=self.bundle, evaluation=self.evaluation
        )
        _validate_or_set_digest(self, self._content_dict())
        expected_candidate_status = derive_operational_candidate_status(
            bundle=self.bundle, evaluation=self.evaluation
        )
        if self.operational_candidate_status is not expected_candidate_status:
            raise ValueError(
                "operational candidate status does not match bundle/evaluation"
            )

    def _content_dict(self) -> dict[str, Any]:
        return {
            name: _json_value(getattr(self, name))
            for name in self.__dataclass_fields__
            if name != "content_digest"
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "content_digest": self.content_digest}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompleteEvaluationOutcome":
        _strict("complete evaluation outcome", data, set(cls.__dataclass_fields__))
        if not data["content_digest"]:
            raise ValueError("serialized outcome requires content_digest")
        return cls(
            schema_version=data["schema_version"],
            bundle=CompleteEvaluationBundle.from_dict(data["bundle"]),
            evaluation=PropRuleEvaluation.from_dict(data["evaluation"]),
            evidence_link=RuleEvaluationEvidenceLinkV2.from_dict(
                data["evidence_link"]
            ),
            operational_candidate_status=data["operational_candidate_status"],
            execution_authority_granted=data["execution_authority_granted"],
            content_digest=data["content_digest"],
        )


def evaluate_complete_bundle(
    *, bundle: CompleteEvaluationBundle, evaluation_id: str, link_id: str
) -> CompleteEvaluationOutcome:
    """Validate, calculate, digest, and link one immutable input set."""

    if not isinstance(bundle, CompleteEvaluationBundle):
        raise TypeError("bundle must be CompleteEvaluationBundle")
    evaluation = PropRuleEngine().evaluate(
        evaluation_id=evaluation_id,
        account=bundle.account,
        definition=bundle.snapshot.rule_definition,
        observation=bundle.observation,
        daily_baseline=(
            None if bundle.baseline is None else bundle.baseline.to_daily_baseline()
        ),
        evaluated_at=bundle.evaluated_at,
        policy=bundle.policy,
        operation=bundle.operation,
    )
    link = RuleEvaluationEvidenceLinkV2.bind(
        link_id=link_id, bundle=bundle, evaluation=evaluation
    )
    candidate = derive_operational_candidate_status(
        bundle=bundle, evaluation=evaluation
    )
    return CompleteEvaluationOutcome(
        schema_version=COMPLETE_EVALUATION_OUTCOME_SCHEMA_VERSION,
        bundle=bundle,
        evaluation=evaluation,
        evidence_link=link,
        operational_candidate_status=candidate,
        execution_authority_granted=False,
    )
