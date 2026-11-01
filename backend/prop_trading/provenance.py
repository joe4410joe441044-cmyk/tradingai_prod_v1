"""Immutable account-bound PROP rule and evaluation provenance contracts.

The SHA-256 digests in this module detect content changes.  They are not
authentication, signatures, execution authority, or active-profile approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    PropAccountObservation,
    PropRuleDefinition,
    PropRuleEvaluation,
    VerificationStatus,
)
from backend.prop_trading.rule_engine import (
    PROP_DAILY_BASELINE_SCHEMA_VERSION,
    PROP_RULE_ENGINE_CALCULATION_VERSION,
    DailyBaseline,
    RuleEnginePolicy,
    RuleType,
    ValueBasis,
    trading_day_at,
)


TRADING_RULES_SNAPSHOT_SCHEMA_VERSION = "tradingai-prop-rules-snapshot/v1"
DAILY_BASELINE_SOURCE_SCHEMA_VERSION = "tradingai-prop-daily-baseline-source/v1"
RULE_EVALUATION_EVIDENCE_LINK_SCHEMA_VERSION = "tradingai-prop-evaluation-evidence-link/v1"
RULE_EVALUATION_EVIDENCE_LINK_V2_SCHEMA_VERSION = "tradingai-prop-evaluation-evidence-link/v2"
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SAFE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,127}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z0-9]{3,12}$")


class SnapshotVerificationStatus(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    UNVERIFIED = "UNVERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    VERIFIED_FOR_ACCOUNT = "VERIFIED_FOR_ACCOUNT"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class BaselineSourceKind(str, Enum):
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    VENUE_OBSERVATION = "VENUE_OBSERVATION"
    OPERATOR_PROVIDED = "OPERATOR_PROVIDED"
    PROP_DASHBOARD = "PROP_DASHBOARD"


class EvaluationPurpose(str, Enum):
    CURRENT_ENTRY = "CURRENT_ENTRY"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"


class CompleteEvaluationPurpose(str, Enum):
    """Purpose with explicit information-time semantics for complete evaluations."""

    READ_ONLY_CURRENT = "READ_ONLY_CURRENT"
    OPERATIONAL_CANDIDATE = "OPERATIONAL_CANDIDATE"
    HISTORICAL_AS_OF = "HISTORICAL_AS_OF"
    RETROACTIVE_ANALYSIS = "RETROACTIVE_ANALYSIS"


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _ref(name: str, value: Any) -> str:
    normalized = _text(name, value)
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ValueError(f"{name} must be an opaque safe reference")
    return normalized


def _optional_ref(name: str, value: Any) -> Optional[str]:
    return None if value is None else _ref(name, value)


def _enum(enum_type, name: str, value: Any):
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unknown {name}") from exc


def _utc(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_datetime(name: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an RFC3339 string")
    try:
        return _utc(name, datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"{name} must be an RFC3339 timestamp") from exc


def _parse_date(name: str, value: Any) -> date:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _finite_decimal(name: str, value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def _parse_decimal(name: str, value: Any) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a decimal string")
    try:
        return _finite_decimal(name, Decimal(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal string") from exc


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _refs(name: str, values: Any) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{name} must be a tuple or list")
    normalized = tuple(_ref(name, value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


def _codes(name: str, values: Any) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{name} must be a tuple or list")
    normalized = tuple(_text(name, value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    if any(not _SAFE_CODE_RE.fullmatch(value) for value in normalized):
        raise ValueError(f"{name} must contain safe typed codes")
    return normalized


def _strict(label: str, data: Any, names: set[str]) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError(f"{label} must be a mapping")
    if set(data) != names:
        raise ValueError(f"{label} fields must exactly match schema")
    return data


def _serialized_tuple(name: str, value: Any) -> Tuple[Any, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return tuple(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, AccountId):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def canonical_content_digest(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise TypeError("digest payload must be a mapping")
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def object_content_digest(value: Any) -> str:
    if not hasattr(value, "to_dict"):
        raise TypeError("digest object must provide to_dict")
    return canonical_content_digest(value.to_dict())


def _validate_or_set_digest(instance: Any, payload: Mapping[str, Any]) -> None:
    expected = canonical_content_digest(payload)
    supplied = instance.content_digest
    if supplied == "":
        object.__setattr__(instance, "content_digest", expected)
        return
    if not isinstance(supplied, str) or not _DIGEST_RE.fullmatch(supplied):
        raise ValueError("content_digest must be sha256:<64 lowercase hex>")
    if supplied != expected:
        raise ValueError("content_digest mismatch")


def _boundary_candidates(
    trading_day: date, timezone_name: str, boundary_local_time: str
) -> Tuple[datetime, ...]:
    try:
        zone = ZoneInfo(_text("timezone_name", timezone_name))
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone_name must be an IANA timezone") from exc
    try:
        boundary = time.fromisoformat(_text("day_boundary_local_time", boundary_local_time))
    except ValueError as exc:
        raise ValueError("day_boundary_local_time must be an ISO local time") from exc
    if boundary.tzinfo is not None:
        raise ValueError("day_boundary_local_time must not include an offset")
    naive = datetime.combine(trading_day, boundary)
    candidates = []
    for fold in (0, 1):
        instant = naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        round_trip = instant.astimezone(zone)
        if round_trip.replace(tzinfo=None) == naive and round_trip.fold == fold:
            candidates.append(instant)
    return tuple(dict.fromkeys(candidates))


@dataclass(frozen=True)
class TradingRulesSnapshot:
    schema_version: str
    snapshot_id: str
    account_id: AccountId
    identity_revision: int
    execution_mode: ExecutionMode
    execution_venue: ExecutionVenue
    prop_program: PropProgram
    plan_id: str
    phase: PropPhase
    applicable_from: datetime
    applicable_to: Optional[datetime]
    rule_definition: PropRuleDefinition
    verification_status: SnapshotVerificationStatus
    verified_at: Optional[datetime]
    verifier_ref: Optional[str]
    source_evidence_refs: Tuple[str, ...]
    unresolved_requirements: Tuple[str, ...]
    supersedes_snapshot_id: Optional[str]
    content_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != TRADING_RULES_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported trading rules snapshot schema")
        object.__setattr__(self, "snapshot_id", _ref("snapshot_id", self.snapshot_id))
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _positive_int("identity_revision", self.identity_revision)
        object.__setattr__(
            self, "execution_mode", _enum(ExecutionMode, "execution_mode", self.execution_mode)
        )
        object.__setattr__(
            self, "execution_venue", _enum(ExecutionVenue, "execution_venue", self.execution_venue)
        )
        object.__setattr__(
            self, "prop_program", _enum(PropProgram, "prop_program", self.prop_program)
        )
        object.__setattr__(self, "plan_id", _ref("plan_id", self.plan_id))
        object.__setattr__(self, "phase", _enum(PropPhase, "phase", self.phase))
        applicable_from = _utc("applicable_from", self.applicable_from)
        object.__setattr__(self, "applicable_from", applicable_from)
        if self.applicable_to is not None:
            applicable_to = _utc("applicable_to", self.applicable_to)
            if applicable_to <= applicable_from:
                raise ValueError("applicable_to must be after applicable_from")
            object.__setattr__(self, "applicable_to", applicable_to)
        if not isinstance(self.rule_definition, PropRuleDefinition):
            raise TypeError("rule_definition must be PropRuleDefinition")
        if (
            self.rule_definition.prop_program is not self.prop_program
            or self.rule_definition.phase is not self.phase
            or self.rule_definition.program_product != self.plan_id
        ):
            raise ValueError("snapshot program, plan, and phase must match rule definition")
        if applicable_from < self.rule_definition.effective_from:
            raise ValueError("snapshot cannot apply before rule definition")
        if (
            self.rule_definition.effective_to is not None
            and (self.applicable_to is None or self.applicable_to > self.rule_definition.effective_to)
        ):
            raise ValueError("snapshot applicability exceeds rule definition")
        status = _enum(
            SnapshotVerificationStatus, "verification_status", self.verification_status
        )
        object.__setattr__(self, "verification_status", status)
        if self.verified_at is not None:
            object.__setattr__(self, "verified_at", _utc("verified_at", self.verified_at))
        object.__setattr__(self, "verifier_ref", _optional_ref("verifier_ref", self.verifier_ref))
        evidence = _refs("source_evidence_refs", self.source_evidence_refs)
        unresolved = _codes("unresolved_requirements", self.unresolved_requirements)
        object.__setattr__(self, "source_evidence_refs", evidence)
        object.__setattr__(self, "unresolved_requirements", unresolved)
        object.__setattr__(
            self,
            "supersedes_snapshot_id",
            _optional_ref("supersedes_snapshot_id", self.supersedes_snapshot_id),
        )
        if self.supersedes_snapshot_id == self.snapshot_id:
            raise ValueError("snapshot cannot supersede itself")
        if status is SnapshotVerificationStatus.SYNTHETIC:
            if (
                not self.plan_id.startswith("SYNTHETIC")
                or not self.rule_definition.program_product.startswith("SYNTHETIC")
                or self.execution_mode is ExecutionMode.LIVE
            ):
                raise ValueError("synthetic snapshot requires synthetic non-live scope")
        if status is SnapshotVerificationStatus.PARTIALLY_VERIFIED and not unresolved:
            raise ValueError("partially verified snapshot requires unresolved requirements")
        if status is SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT:
            if (
                self.verified_at is None
                or self.verifier_ref is None
                or not evidence
                or unresolved
                or self.rule_definition.verification_status is not VerificationStatus.VERIFIED
                or self.rule_definition.completeness is not Completeness.COMPLETE
                or self.plan_id.startswith("SYNTHETIC")
            ):
                raise ValueError("verified snapshot requires complete account evidence")
        _validate_or_set_digest(self, self._content_dict())

    def _content_dict(self) -> dict[str, Any]:
        return {
            name: _json_value(getattr(self, name))
            for name in self.__dataclass_fields__
            if name != "content_digest"
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "content_digest": self.content_digest}

    def binds(self, account: AccountIdentity) -> bool:
        return (
            isinstance(account, AccountIdentity)
            and account.account_type is AccountType.PROP
            and account.account_id == self.account_id
            and account.revision == self.identity_revision
            and account.execution_mode is self.execution_mode
            and account.execution_venue is self.execution_venue
            and account.prop_program is self.prop_program
            and account.prop_phase is self.phase
        )

    def is_current_entry_eligible(self, evaluated_at: datetime) -> bool:
        moment = _utc("evaluated_at", evaluated_at)
        return (
            self.verification_status is SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT
            and self.applicable_from <= moment
            and (self.applicable_to is None or moment < self.applicable_to)
            and not self.unresolved_requirements
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TradingRulesSnapshot":
        _strict("trading rules snapshot", data, set(cls.__dataclass_fields__))
        if not data["content_digest"]:
            raise ValueError("serialized snapshot requires content_digest")
        return cls(
            schema_version=data["schema_version"],
            snapshot_id=data["snapshot_id"],
            account_id=AccountId(data["account_id"]),
            identity_revision=data["identity_revision"],
            execution_mode=data["execution_mode"],
            execution_venue=data["execution_venue"],
            prop_program=data["prop_program"],
            plan_id=data["plan_id"],
            phase=data["phase"],
            applicable_from=_parse_datetime("applicable_from", data["applicable_from"]),
            applicable_to=(
                None
                if data["applicable_to"] is None
                else _parse_datetime("applicable_to", data["applicable_to"])
            ),
            rule_definition=PropRuleDefinition.from_dict(data["rule_definition"]),
            verification_status=data["verification_status"],
            verified_at=(
                None
                if data["verified_at"] is None
                else _parse_datetime("verified_at", data["verified_at"])
            ),
            verifier_ref=data["verifier_ref"],
            source_evidence_refs=_serialized_tuple(
                "source_evidence_refs", data["source_evidence_refs"]
            ),
            unresolved_requirements=_serialized_tuple(
                "unresolved_requirements", data["unresolved_requirements"]
            ),
            supersedes_snapshot_id=data["supersedes_snapshot_id"],
            content_digest=data["content_digest"],
        )


@dataclass(frozen=True)
class DailyBaselineSource:
    schema_version: str
    baseline_id: str
    revision: int
    supersedes_baseline_id: Optional[str]
    account_id: AccountId
    identity_revision: int
    execution_mode: ExecutionMode
    execution_venue: ExecutionVenue
    rules_snapshot_id: str
    rules_snapshot_digest: str
    rule_set_id: str
    rule_set_revision: int
    trading_day: date
    timezone_name: str
    day_boundary_local_time: str
    boundary_fold: Optional[int]
    effective_at: datetime
    observed_at: Optional[datetime]
    captured_at: datetime
    value_basis: ValueBasis
    reference_value: Decimal
    currency: str
    source_kind: BaselineSourceKind
    evidence_ref: Optional[str]
    verification_status: SnapshotVerificationStatus
    completeness: Completeness
    unresolved_requirements: Tuple[str, ...]
    content_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != DAILY_BASELINE_SOURCE_SCHEMA_VERSION:
            raise ValueError("unsupported daily baseline source schema")
        object.__setattr__(self, "baseline_id", _ref("baseline_id", self.baseline_id))
        _positive_int("revision", self.revision)
        object.__setattr__(
            self,
            "supersedes_baseline_id",
            _optional_ref("supersedes_baseline_id", self.supersedes_baseline_id),
        )
        if self.supersedes_baseline_id == self.baseline_id:
            raise ValueError("baseline cannot supersede itself")
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _positive_int("identity_revision", self.identity_revision)
        object.__setattr__(
            self, "execution_mode", _enum(ExecutionMode, "execution_mode", self.execution_mode)
        )
        object.__setattr__(
            self, "execution_venue", _enum(ExecutionVenue, "execution_venue", self.execution_venue)
        )
        object.__setattr__(
            self, "rules_snapshot_id", _ref("rules_snapshot_id", self.rules_snapshot_id)
        )
        if not isinstance(self.rules_snapshot_digest, str) or not _DIGEST_RE.fullmatch(
            self.rules_snapshot_digest
        ):
            raise ValueError("rules_snapshot_digest must be a SHA-256 digest")
        object.__setattr__(self, "rule_set_id", _ref("rule_set_id", self.rule_set_id))
        _positive_int("rule_set_revision", self.rule_set_revision)
        if not isinstance(self.trading_day, date) or isinstance(self.trading_day, datetime):
            raise TypeError("trading_day must be date")
        candidates = _boundary_candidates(
            self.trading_day, self.timezone_name, self.day_boundary_local_time
        )
        if not candidates:
            raise ValueError("daily boundary is nonexistent")
        if len(candidates) == 1:
            if self.boundary_fold is not None:
                raise ValueError("unambiguous boundary must not declare fold")
            selected = candidates[0]
        else:
            if isinstance(self.boundary_fold, bool) or self.boundary_fold not in (0, 1):
                raise ValueError("ambiguous boundary requires fold 0 or 1")
            selected = candidates[self.boundary_fold]
        effective_at = _utc("effective_at", self.effective_at)
        if effective_at != selected:
            raise ValueError("effective_at does not match resolved daily boundary")
        object.__setattr__(self, "effective_at", effective_at)
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", _utc("observed_at", self.observed_at))
        captured_at = _utc("captured_at", self.captured_at)
        if captured_at < effective_at:
            raise ValueError("captured_at cannot precede effective_at")
        if self.observed_at is not None and self.observed_at > captured_at:
            raise ValueError("observed_at cannot follow captured_at")
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "value_basis", _enum(ValueBasis, "value_basis", self.value_basis))
        _finite_decimal("reference_value", self.reference_value)
        currency = _text("currency", self.currency).upper()
        if not _CURRENCY_RE.fullmatch(currency):
            raise ValueError("currency must be a 3-12 character uppercase asset code")
        object.__setattr__(self, "currency", currency)
        source_kind = _enum(BaselineSourceKind, "source_kind", self.source_kind)
        status = _enum(
            SnapshotVerificationStatus, "verification_status", self.verification_status
        )
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "verification_status", status)
        object.__setattr__(self, "evidence_ref", _optional_ref("evidence_ref", self.evidence_ref))
        object.__setattr__(self, "completeness", _enum(Completeness, "completeness", self.completeness))
        unresolved = _codes("unresolved_requirements", self.unresolved_requirements)
        object.__setattr__(self, "unresolved_requirements", unresolved)
        if status is SnapshotVerificationStatus.SYNTHETIC:
            if source_kind is not BaselineSourceKind.SYNTHETIC_FIXTURE:
                raise ValueError("synthetic baseline requires synthetic fixture source")
        if status is SnapshotVerificationStatus.PARTIALLY_VERIFIED and not unresolved:
            raise ValueError("partially verified baseline requires unresolved requirements")
        if status is SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT:
            if (
                source_kind is BaselineSourceKind.SYNTHETIC_FIXTURE
                or self.evidence_ref is None
                or self.completeness is not Completeness.COMPLETE
                or unresolved
            ):
                raise ValueError("verified baseline requires complete non-synthetic evidence")
        _validate_or_set_digest(self, self._content_dict())

    def _content_dict(self) -> dict[str, Any]:
        return {
            name: _json_value(getattr(self, name))
            for name in self.__dataclass_fields__
            if name != "content_digest"
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "content_digest": self.content_digest}

    def to_daily_baseline(self) -> DailyBaseline:
        verification = (
            VerificationStatus.VERIFIED
            if self.verification_status
            in {
                SnapshotVerificationStatus.SYNTHETIC,
                SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT,
            }
            else VerificationStatus.UNVERIFIED
        )
        return DailyBaseline(
            schema_version=PROP_DAILY_BASELINE_SCHEMA_VERSION,
            baseline_id=self.baseline_id,
            account_id=self.account_id,
            rule_set_id=self.rule_set_id,
            rule_set_revision=self.rule_set_revision,
            trading_day=self.trading_day,
            timezone_name=self.timezone_name,
            day_boundary_local_time=self.day_boundary_local_time,
            effective_at=self.effective_at,
            value_basis=self.value_basis,
            reference_value=self.reference_value,
            currency=self.currency,
            source=self.source_kind.value,
            verification_status=verification,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DailyBaselineSource":
        _strict("daily baseline source", data, set(cls.__dataclass_fields__))
        if not data["content_digest"]:
            raise ValueError("serialized baseline source requires content_digest")
        return cls(
            schema_version=data["schema_version"],
            baseline_id=data["baseline_id"],
            revision=data["revision"],
            supersedes_baseline_id=data["supersedes_baseline_id"],
            account_id=AccountId(data["account_id"]),
            identity_revision=data["identity_revision"],
            execution_mode=data["execution_mode"],
            execution_venue=data["execution_venue"],
            rules_snapshot_id=data["rules_snapshot_id"],
            rules_snapshot_digest=data["rules_snapshot_digest"],
            rule_set_id=data["rule_set_id"],
            rule_set_revision=data["rule_set_revision"],
            trading_day=_parse_date("trading_day", data["trading_day"]),
            timezone_name=data["timezone_name"],
            day_boundary_local_time=data["day_boundary_local_time"],
            boundary_fold=data["boundary_fold"],
            effective_at=_parse_datetime("effective_at", data["effective_at"]),
            observed_at=(
                None
                if data["observed_at"] is None
                else _parse_datetime("observed_at", data["observed_at"])
            ),
            captured_at=_parse_datetime("captured_at", data["captured_at"]),
            value_basis=data["value_basis"],
            reference_value=_parse_decimal("reference_value", data["reference_value"]),
            currency=data["currency"],
            source_kind=data["source_kind"],
            evidence_ref=data["evidence_ref"],
            verification_status=data["verification_status"],
            completeness=data["completeness"],
            unresolved_requirements=_serialized_tuple(
                "unresolved_requirements", data["unresolved_requirements"]
            ),
            content_digest=data["content_digest"],
        )


@dataclass(frozen=True)
class RuleEvaluationEvidenceLink:
    schema_version: str
    link_id: str
    evaluation_id: str
    purpose: EvaluationPurpose
    account_id: AccountId
    identity_revision: int
    execution_mode: ExecutionMode
    execution_venue: ExecutionVenue
    prop_program: PropProgram
    plan_id: str
    phase: PropPhase
    observation_id: str
    observation_digest: str
    rules_snapshot_id: str
    rules_snapshot_digest: str
    rule_set_id: str
    rule_set_revision: int
    baseline_id: Optional[str]
    baseline_digest: Optional[str]
    baseline_revision: Optional[int]
    evaluated_at: datetime
    evaluator_version: str
    policy_digest: str
    result_schema_version: str
    content_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != RULE_EVALUATION_EVIDENCE_LINK_SCHEMA_VERSION:
            raise ValueError("unsupported evaluation evidence link schema")
        for name in (
            "link_id", "evaluation_id", "plan_id", "observation_id",
            "rules_snapshot_id", "rule_set_id", "evaluator_version", "result_schema_version",
        ):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        object.__setattr__(self, "purpose", _enum(EvaluationPurpose, "purpose", self.purpose))
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _positive_int("identity_revision", self.identity_revision)
        object.__setattr__(
            self, "execution_mode", _enum(ExecutionMode, "execution_mode", self.execution_mode)
        )
        object.__setattr__(
            self, "execution_venue", _enum(ExecutionVenue, "execution_venue", self.execution_venue)
        )
        object.__setattr__(
            self, "prop_program", _enum(PropProgram, "prop_program", self.prop_program)
        )
        object.__setattr__(self, "phase", _enum(PropPhase, "phase", self.phase))
        for name in (
            "observation_digest", "rules_snapshot_digest", "policy_digest",
        ):
            if not isinstance(getattr(self, name), str) or not _DIGEST_RE.fullmatch(
                getattr(self, name)
            ):
                raise ValueError(f"{name} must be a SHA-256 digest")
        all_baseline_none = (
            self.baseline_id is None
            and self.baseline_digest is None
            and self.baseline_revision is None
        )
        all_baseline_present = (
            self.baseline_id is not None
            and self.baseline_digest is not None
            and self.baseline_revision is not None
        )
        if not (all_baseline_none or all_baseline_present):
            raise ValueError("baseline reference fields must be all present or all absent")
        if all_baseline_present:
            object.__setattr__(self, "baseline_id", _ref("baseline_id", self.baseline_id))
            if not _DIGEST_RE.fullmatch(self.baseline_digest):
                raise ValueError("baseline_digest must be a SHA-256 digest")
            _positive_int("baseline_revision", self.baseline_revision)
        _positive_int("rule_set_revision", self.rule_set_revision)
        object.__setattr__(self, "evaluated_at", _utc("evaluated_at", self.evaluated_at))
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
        *,
        link_id: str,
        purpose: EvaluationPurpose,
        account: AccountIdentity,
        observation: PropAccountObservation,
        snapshot: TradingRulesSnapshot,
        baseline: Optional[DailyBaselineSource],
        policy: RuleEnginePolicy,
        evaluation: PropRuleEvaluation,
    ) -> "RuleEvaluationEvidenceLink":
        if not isinstance(account, AccountIdentity) or account.account_type is not AccountType.PROP:
            raise TypeError("account must be a PROP AccountIdentity")
        if not snapshot.binds(account):
            raise ValueError("snapshot account binding mismatch")
        if (
            observation.account_id != account.account_id
            or observation.identity_revision != account.revision
        ):
            raise ValueError("observation account binding mismatch")
        if (
            evaluation.account_id != account.account_id
            or evaluation.observation_id != observation.observation_id
            or evaluation.rule_set_id != snapshot.rule_definition.rule_set_id
            or evaluation.rule_set_revision != snapshot.rule_definition.rule_set_revision
        ):
            raise ValueError("evaluation references do not match inputs")
        purpose = _enum(EvaluationPurpose, "purpose", purpose)
        if not (
            snapshot.applicable_from <= evaluation.evaluated_at
            and (
                snapshot.applicable_to is None
                or evaluation.evaluated_at < snapshot.applicable_to
            )
        ):
            raise ValueError("snapshot is not applicable at evaluation time")
        if evaluation.calculation_version != PROP_RULE_ENGINE_CALCULATION_VERSION:
            raise ValueError("evaluator version is not supported")
        if observation.currency != snapshot.rule_definition.currency:
            raise ValueError("observation currency does not match snapshot")
        if purpose is EvaluationPurpose.CURRENT_ENTRY:
            if not snapshot.is_current_entry_eligible(evaluation.evaluated_at):
                raise ValueError("snapshot is not eligible for current entry")
            if evaluation.entry_allowed is not True:
                raise ValueError("current entry link requires passing entry gates")
            raise ValueError("current entry activation is not implemented")
        daily_required = RuleType.DAILY_LOSS.value in policy.required_rule_codes
        if daily_required and baseline is None:
            raise ValueError("daily rule requires baseline provenance")
        if not daily_required and baseline is not None:
            raise ValueError("baseline provenance is unexpected for selected rules")
        if baseline is not None:
            if (
                baseline.account_id != account.account_id
                or baseline.identity_revision != account.revision
                or baseline.execution_mode is not account.execution_mode
                or baseline.execution_venue is not account.execution_venue
                or baseline.rules_snapshot_id != snapshot.snapshot_id
                or baseline.rules_snapshot_digest != snapshot.content_digest
                or baseline.rule_set_id != snapshot.rule_definition.rule_set_id
                or baseline.rule_set_revision != snapshot.rule_definition.rule_set_revision
                or baseline.currency != snapshot.rule_definition.currency
                or baseline.value_basis is not policy.daily_loss_basis
                or baseline.timezone_name
                != snapshot.rule_definition.day_boundary_timezone
                or baseline.day_boundary_local_time
                != snapshot.rule_definition.day_boundary_local_time
            ):
                raise ValueError("baseline provenance does not match snapshot/account")
            expected_day = trading_day_at(
                evaluation.evaluated_at,
                baseline.timezone_name,
                baseline.day_boundary_local_time,
            )
            if baseline.trading_day != expected_day:
                raise ValueError("baseline trading day does not match evaluation")
            if purpose is EvaluationPurpose.CURRENT_ENTRY and (
                baseline.verification_status
                is not SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT
            ):
                raise ValueError("current entry requires verified account baseline")
        return cls(
            schema_version=RULE_EVALUATION_EVIDENCE_LINK_SCHEMA_VERSION,
            link_id=link_id,
            evaluation_id=evaluation.evaluation_id,
            purpose=purpose,
            account_id=account.account_id,
            identity_revision=account.revision,
            execution_mode=account.execution_mode,
            execution_venue=account.execution_venue,
            prop_program=account.prop_program,
            plan_id=snapshot.plan_id,
            phase=account.prop_phase,
            observation_id=observation.observation_id,
            observation_digest=object_content_digest(observation),
            rules_snapshot_id=snapshot.snapshot_id,
            rules_snapshot_digest=snapshot.content_digest,
            rule_set_id=evaluation.rule_set_id,
            rule_set_revision=evaluation.rule_set_revision,
            baseline_id=None if baseline is None else baseline.baseline_id,
            baseline_digest=None if baseline is None else baseline.content_digest,
            baseline_revision=None if baseline is None else baseline.revision,
            evaluated_at=evaluation.evaluated_at,
            evaluator_version=evaluation.calculation_version,
            policy_digest=canonical_content_digest(policy.to_dict()),
            result_schema_version=evaluation.schema_version,
        )

    def validate_inputs(
        self,
        *,
        account: AccountIdentity,
        observation: PropAccountObservation,
        snapshot: TradingRulesSnapshot,
        baseline: Optional[DailyBaselineSource],
        policy: RuleEnginePolicy,
        evaluation: PropRuleEvaluation,
    ) -> None:
        rebuilt = type(self).bind(
            link_id=self.link_id,
            purpose=self.purpose,
            account=account,
            observation=observation,
            snapshot=snapshot,
            baseline=baseline,
            policy=policy,
            evaluation=evaluation,
        )
        if rebuilt != self:
            raise ValueError("evaluation evidence link does not match supplied inputs")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleEvaluationEvidenceLink":
        _strict("evaluation evidence link", data, set(cls.__dataclass_fields__))
        if not data["content_digest"]:
            raise ValueError("serialized evaluation link requires content_digest")
        return cls(
            schema_version=data["schema_version"],
            link_id=data["link_id"],
            evaluation_id=data["evaluation_id"],
            purpose=data["purpose"],
            account_id=AccountId(data["account_id"]),
            identity_revision=data["identity_revision"],
            execution_mode=data["execution_mode"],
            execution_venue=data["execution_venue"],
            prop_program=data["prop_program"],
            plan_id=data["plan_id"],
            phase=data["phase"],
            observation_id=data["observation_id"],
            observation_digest=data["observation_digest"],
            rules_snapshot_id=data["rules_snapshot_id"],
            rules_snapshot_digest=data["rules_snapshot_digest"],
            rule_set_id=data["rule_set_id"],
            rule_set_revision=data["rule_set_revision"],
            baseline_id=data["baseline_id"],
            baseline_digest=data["baseline_digest"],
            baseline_revision=data["baseline_revision"],
            evaluated_at=_parse_datetime("evaluated_at", data["evaluated_at"]),
            evaluator_version=data["evaluator_version"],
            policy_digest=data["policy_digest"],
            result_schema_version=data["result_schema_version"],
            content_digest=data["content_digest"],
        )
