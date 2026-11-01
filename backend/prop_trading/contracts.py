"""Immutable PROP rule, observation, and evaluation contracts.

No HyroTrader threshold is embedded here.  Values must come from a separately
verified, versioned rule source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import re
from typing import Any, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.accounts.models import AccountId, PropPhase, PropProgram


PROP_RULE_DEFINITION_SCHEMA_VERSION = "tradingai-prop-rule-definition/v1"
PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION = "tradingai-prop-account-observation/v1"
PROP_RULE_EVALUATION_SCHEMA_VERSION = "tradingai-prop-rule-evaluation/v1"
_CURRENCY_RE = re.compile(r"^[A-Z0-9]{3,12}$")
_SAFE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,127}$")
_RULE_UNKNOWN_FIELD_NAMES = frozenset({
    "profit_target_pct", "daily_loss_limit_pct", "maximum_loss_limit_pct",
    "minimum_trading_days", "per_trade_profit_cap_pct", "per_day_profit_cap_pct",
    "maximum_total_margin_pct", "maximum_notional_multiple", "loss_model",
    "day_boundary_timezone", "day_boundary_local_time", "equity_components",
    "breach_policy",
})


_BREACH_UNKNOWN_FIELD_NAMES = frozenset(
    {"warning_count_before_failure", "failure_transition"}
)
_OBSERVATION_VALUE_FIELD_NAMES = frozenset({
    "balance", "equity", "available_balance", "realized_pnl", "unrealized_pnl",
    "open_position_count", "open_order_count", "fees", "funding",
    "day_start_equity", "day_realized_pnl", "day_profit", "total_margin_used",
    "total_notional", "trading_days_count",
})

class Completeness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class DataQuality(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"


class LossModel(str, Enum):
    STATIC = "STATIC"
    TRAILING = "TRAILING"
    UNKNOWN = "UNKNOWN"


class SourceKind(str, Enum):
    DOCUMENT = "DOCUMENT"
    API = "API"
    OPERATOR_VERIFIED = "OPERATOR_VERIFIED"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


class EquityComponentState(str, Enum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    UNKNOWN = "UNKNOWN"


class RuleOperation(str, Enum):
    ENTRY = "ENTRY"
    CANCEL = "CANCEL"
    PROTECTIVE = "PROTECTIVE"
    REDUCE_OR_CLOSE = "REDUCE_OR_CLOSE"
    READ_ONLY = "READ_ONLY"


class EvaluationState(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _texts(name: str, values: Any) -> Tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{name} must be a tuple or list")
    normalized = tuple(_text(name, value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


def _codes(name: str, values: Any) -> Tuple[str, ...]:
    normalized = _texts(name, values)
    if any(not _SAFE_CODE_RE.fullmatch(value) for value in normalized):
        raise ValueError(f"{name} must contain safe typed codes")
    return normalized


def _enum(enum_type, name: str, value: Any):
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unknown {name}") from exc


def _serialized_list(name: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


def _utc(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_dt(name: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an RFC3339 string")
    try:
        return _utc(name, datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"{name} must be an RFC3339 timestamp") from exc


def _decimal(name: str, value: Any, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be > 0")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def _optional_decimal(name: str, value: Any, *, nonnegative: bool = False) -> Optional[Decimal]:
    if value is None:
        return None
    return _decimal(name, value, nonnegative=nonnegative)


def _parse_decimal(name: str, value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a decimal string or None")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal string") from exc


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, AccountId):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _strict_mapping(
    label: str, data: Any, *, required: set[str], optional: set[str] = frozenset()
) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError(f"{label} must be a mapping")
    missing = required - set(data)
    unknown = set(data) - required - optional
    if missing:
        raise ValueError(f"missing {label} fields: " + ", ".join(sorted(missing)))
    if unknown:
        raise ValueError(f"unknown {label} fields")
    return data


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class EquityComponent:
    component: str
    state: EquityComponentState

    def __post_init__(self) -> None:
        object.__setattr__(self, "component", _text("component", self.component))
        object.__setattr__(self, "state", _enum(EquityComponentState, "equity component state", self.state))

    def to_dict(self) -> dict[str, Any]:
        return {"component": self.component, "state": self.state.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EquityComponent":
        _strict_mapping("equity component", data, required={"component", "state"})
        return cls(component=data["component"], state=data["state"])


@dataclass(frozen=True)
class BreachPolicy:
    warning_count_before_failure: Optional[int]
    failure_transition: Optional[str]
    unknown_fields: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.warning_count_before_failure is not None and (
            isinstance(self.warning_count_before_failure, bool)
            or not isinstance(self.warning_count_before_failure, int)
            or self.warning_count_before_failure < 0
        ):
            raise ValueError("warning_count_before_failure must be nonnegative or None")
        if self.failure_transition is not None:
            object.__setattr__(self, "failure_transition", _text("failure_transition", self.failure_transition))
        unknown = _texts("unknown_fields", self.unknown_fields)
        if not set(unknown).issubset(_BREACH_UNKNOWN_FIELD_NAMES):
            raise ValueError("unknown_fields contains unsupported breach policy field names")
        object.__setattr__(self, "unknown_fields", unknown)

    def to_dict(self) -> dict[str, Any]:
        return {
            "warning_count_before_failure": self.warning_count_before_failure,
            "failure_transition": self.failure_transition,
            "unknown_fields": list(self.unknown_fields),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BreachPolicy":
        _strict_mapping(
            "breach policy",
            data,
            required={"warning_count_before_failure", "failure_transition", "unknown_fields"},
        )
        return cls(
            warning_count_before_failure=data["warning_count_before_failure"],
            failure_transition=data["failure_transition"],
            unknown_fields=tuple(_serialized_list("unknown_fields", data["unknown_fields"])),
        )


@dataclass(frozen=True)
class PropRuleDefinition:
    schema_version: str
    rule_set_id: str
    rule_set_revision: int
    prop_program: PropProgram
    program_product: str
    phase: PropPhase
    effective_from: datetime
    initial_balance: Decimal
    currency: str
    loss_model: LossModel
    day_boundary_timezone: str
    day_boundary_local_time: str
    equity_components: Tuple[EquityComponent, ...]
    breach_policy: BreachPolicy
    source_kind: SourceKind
    source_reference: str
    source_observed_at: datetime
    verification_status: VerificationStatus
    completeness: Completeness
    effective_to: Optional[datetime] = None
    profit_target_pct: Optional[Decimal] = None
    daily_loss_limit_pct: Optional[Decimal] = None
    maximum_loss_limit_pct: Optional[Decimal] = None
    minimum_trading_days: Optional[int] = None
    per_trade_profit_cap_pct: Optional[Decimal] = None
    per_day_profit_cap_pct: Optional[Decimal] = None
    maximum_total_margin_pct: Optional[Decimal] = None
    maximum_notional_multiple: Optional[Decimal] = None
    unknown_fields: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != PROP_RULE_DEFINITION_SCHEMA_VERSION:
            raise ValueError("unsupported PROP rule definition schema")
        object.__setattr__(self, "rule_set_id", _text("rule_set_id", self.rule_set_id))
        _positive_int("rule_set_revision", self.rule_set_revision)
        object.__setattr__(self, "prop_program", _enum(PropProgram, "prop_program", self.prop_program))
        program_product = _text("program_product", self.program_product)
        if not _SAFE_CODE_RE.fullmatch(program_product):
            raise ValueError("program_product must be a safe identifier")
        object.__setattr__(self, "program_product", program_product)
        object.__setattr__(self, "phase", _enum(PropPhase, "phase", self.phase))
        effective_from = _utc("effective_from", self.effective_from)
        object.__setattr__(self, "effective_from", effective_from)
        if self.effective_to is not None:
            effective_to = _utc("effective_to", self.effective_to)
            if effective_to <= effective_from:
                raise ValueError("effective_to must be after effective_from")
            object.__setattr__(self, "effective_to", effective_to)
        _decimal("initial_balance", self.initial_balance, positive=True)
        currency = _text("currency", self.currency).upper()
        if not _CURRENCY_RE.fullmatch(currency):
            raise ValueError("currency must be a 3-12 character uppercase asset code")
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "loss_model", _enum(LossModel, "loss_model", self.loss_model))
        timezone_name = _text("day_boundary_timezone", self.day_boundary_timezone)
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("day_boundary_timezone must be an IANA timezone") from exc
        object.__setattr__(self, "day_boundary_timezone", timezone_name)
        boundary = _text("day_boundary_local_time", self.day_boundary_local_time)
        try:
            time.fromisoformat(boundary)
        except ValueError as exc:
            raise ValueError("day_boundary_local_time must be an ISO local time") from exc
        object.__setattr__(self, "day_boundary_local_time", boundary)
        components = tuple(self.equity_components)
        if any(not isinstance(item, EquityComponent) for item in components):
            raise TypeError("equity_components must contain EquityComponent values")
        if len({item.component for item in components}) != len(components):
            raise ValueError("equity_components must not contain duplicate components")
        object.__setattr__(self, "equity_components", components)
        if not isinstance(self.breach_policy, BreachPolicy):
            raise TypeError("breach_policy must be BreachPolicy")
        object.__setattr__(self, "source_kind", _enum(SourceKind, "source_kind", self.source_kind))
        object.__setattr__(self, "source_reference", _text("source_reference", self.source_reference))
        object.__setattr__(self, "source_observed_at", _utc("source_observed_at", self.source_observed_at))
        object.__setattr__(self, "verification_status", _enum(VerificationStatus, "verification_status", self.verification_status))
        object.__setattr__(self, "completeness", _enum(Completeness, "completeness", self.completeness))
        for name in (
            "profit_target_pct", "daily_loss_limit_pct", "maximum_loss_limit_pct",
            "per_trade_profit_cap_pct", "per_day_profit_cap_pct", "maximum_total_margin_pct",
        ):
            value = _optional_decimal(name, getattr(self, name), nonnegative=True)
            if value is not None and value > Decimal("100"):
                raise ValueError(f"{name} must be <= 100")
        _optional_decimal("maximum_notional_multiple", self.maximum_notional_multiple, nonnegative=True)
        if self.minimum_trading_days is not None and (
            isinstance(self.minimum_trading_days, bool)
            or not isinstance(self.minimum_trading_days, int)
            or self.minimum_trading_days < 0
        ):
            raise ValueError("minimum_trading_days must be nonnegative or None")
        unknown = _texts("unknown_fields", self.unknown_fields)
        if not set(unknown).issubset(_RULE_UNKNOWN_FIELD_NAMES):
            raise ValueError("unknown_fields contains unsupported rule field names")
        if self.completeness is Completeness.COMPLETE and unknown:
            raise ValueError("COMPLETE rule definition cannot have unknown_fields")
        object.__setattr__(self, "unknown_fields", unknown)

    def to_dict(self) -> dict[str, Any]:
        return {name: _serialize(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PropRuleDefinition":
        names = set(cls.__dataclass_fields__)
        _strict_mapping("PROP rule definition", data, required=names)
        values = dict(data)
        for name in (
            "initial_balance", "profit_target_pct", "daily_loss_limit_pct",
            "maximum_loss_limit_pct", "per_trade_profit_cap_pct", "per_day_profit_cap_pct",
            "maximum_total_margin_pct", "maximum_notional_multiple",
        ):
            values[name] = _parse_decimal(name, values[name])
        for name in ("effective_from", "source_observed_at"):
            values[name] = _parse_dt(name, values[name])
        values["effective_to"] = None if values["effective_to"] is None else _parse_dt("effective_to", values["effective_to"])
        values["equity_components"] = tuple(
            EquityComponent.from_dict(item)
            for item in _serialized_list("equity_components", values["equity_components"])
        )
        values["breach_policy"] = BreachPolicy.from_dict(values["breach_policy"])
        values["unknown_fields"] = tuple(_serialized_list("unknown_fields", values["unknown_fields"]))
        return cls(**values)


@dataclass(frozen=True)
class PropAccountObservation:
    schema_version: str
    observation_id: str
    account_id: AccountId
    identity_revision: int
    observed_at: datetime
    received_at: datetime
    source: str
    source_revision: str
    freshness: FreshnessState
    quality: DataQuality
    currency: str
    balance: Optional[Decimal]
    equity: Optional[Decimal]
    available_balance: Optional[Decimal]
    realized_pnl: Optional[Decimal]
    unrealized_pnl: Optional[Decimal]
    open_position_count: Optional[int]
    open_order_count: Optional[int]
    fees: Optional[Decimal] = None
    funding: Optional[Decimal] = None
    day_start_equity: Optional[Decimal] = None
    day_realized_pnl: Optional[Decimal] = None
    day_profit: Optional[Decimal] = None
    total_margin_used: Optional[Decimal] = None
    total_notional: Optional[Decimal] = None
    trading_days_count: Optional[int] = None
    missing_fields: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION:
            raise ValueError("unsupported PROP observation schema")
        object.__setattr__(self, "observation_id", _text("observation_id", self.observation_id))
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        _positive_int("identity_revision", self.identity_revision)
        observed = _utc("observed_at", self.observed_at)
        received = _utc("received_at", self.received_at)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "received_at", received)
        object.__setattr__(self, "source", _text("source", self.source))
        object.__setattr__(self, "source_revision", _text("source_revision", self.source_revision))
        object.__setattr__(self, "freshness", _enum(FreshnessState, "freshness", self.freshness))
        object.__setattr__(self, "quality", _enum(DataQuality, "quality", self.quality))
        currency = _text("currency", self.currency).upper()
        if not _CURRENCY_RE.fullmatch(currency):
            raise ValueError("currency must be a 3-12 character uppercase asset code")
        object.__setattr__(self, "currency", currency)
        for name in (
            "balance", "equity", "available_balance", "realized_pnl", "unrealized_pnl",
            "fees", "funding", "day_start_equity", "day_realized_pnl", "day_profit",
            "total_margin_used", "total_notional",
        ):
            _optional_decimal(name, getattr(self, name))
        for name in ("open_position_count", "open_order_count", "trading_days_count"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        missing = _texts("missing_fields", self.missing_fields)
        if not set(missing).issubset(_OBSERVATION_VALUE_FIELD_NAMES):
            raise ValueError("missing_fields contains unsupported observation field names")
        warnings = _codes("warnings", self.warnings)
        expected_missing = {
            name for name in _OBSERVATION_VALUE_FIELD_NAMES if getattr(self, name) is None
        }
        if set(missing) != expected_missing:
            raise ValueError("missing_fields must exactly match observation values that are None")
        if self.quality is DataQuality.COMPLETE and missing:
            raise ValueError("COMPLETE observation cannot have missing fields")
        object.__setattr__(self, "missing_fields", missing)
        object.__setattr__(self, "warnings", warnings)

    def to_dict(self) -> dict[str, Any]:
        return {name: _serialize(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PropAccountObservation":
        names = set(cls.__dataclass_fields__)
        _strict_mapping("PROP account observation", data, required=names)
        values = dict(data)
        values["account_id"] = AccountId(values["account_id"])
        values["observed_at"] = _parse_dt("observed_at", values["observed_at"])
        values["received_at"] = _parse_dt("received_at", values["received_at"])
        for name in (
            "balance", "equity", "available_balance", "realized_pnl", "unrealized_pnl",
            "fees", "funding", "day_start_equity", "day_realized_pnl", "day_profit",
            "total_margin_used", "total_notional",
        ):
            values[name] = _parse_decimal(name, values[name])
        values["missing_fields"] = tuple(_serialized_list("missing_fields", values["missing_fields"]))
        values["warnings"] = tuple(_serialized_list("warnings", values["warnings"]))
        return cls(**values)


@dataclass(frozen=True)
class RuleResult:
    rule_code: str
    state: EvaluationState
    unit: str
    actual: Optional[Decimal]
    threshold: Optional[Decimal]
    headroom: Optional[Decimal]
    reason_code: Optional[str]

    def __post_init__(self) -> None:
        rule_code = _text("rule_code", self.rule_code)
        if not _SAFE_CODE_RE.fullmatch(rule_code):
            raise ValueError("rule_code must be a safe typed code")
        object.__setattr__(self, "rule_code", rule_code)
        object.__setattr__(self, "state", _enum(EvaluationState, "rule result state", self.state))
        object.__setattr__(self, "unit", _text("unit", self.unit))
        for name in ("actual", "threshold", "headroom"):
            _optional_decimal(name, getattr(self, name))
        if self.reason_code is not None:
            reason_code = _text("reason_code", self.reason_code)
            if not _SAFE_CODE_RE.fullmatch(reason_code):
                raise ValueError("reason_code must be a safe typed code")
            object.__setattr__(self, "reason_code", reason_code)
        if self.state in {EvaluationState.BLOCK, EvaluationState.UNKNOWN} and self.reason_code is None:
            raise ValueError("BLOCK/UNKNOWN rule result requires reason_code")

    def to_dict(self) -> dict[str, Any]:
        return {name: _serialize(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleResult":
        names = set(cls.__dataclass_fields__)
        _strict_mapping("rule result", data, required=names)
        values = dict(data)
        for name in ("actual", "threshold", "headroom"):
            values[name] = _parse_decimal(name, values[name])
        return cls(**values)


@dataclass(frozen=True)
class PropRuleEvaluation:
    schema_version: str
    evaluation_id: str
    account_id: AccountId
    rule_set_id: str
    rule_set_revision: int
    observation_id: str
    evaluated_at: datetime
    operation: RuleOperation
    overall_state: EvaluationState
    entry_allowed: Optional[bool]
    rule_results: Tuple[RuleResult, ...]
    blocking_rule_codes: Tuple[str, ...]
    unknown_rule_codes: Tuple[str, ...]
    warnings: Tuple[str, ...]
    freshness_state: FreshnessState
    calculation_version: str

    def __post_init__(self) -> None:
        if self.schema_version != PROP_RULE_EVALUATION_SCHEMA_VERSION:
            raise ValueError("unsupported PROP evaluation schema")
        object.__setattr__(self, "evaluation_id", _text("evaluation_id", self.evaluation_id))
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        object.__setattr__(self, "rule_set_id", _text("rule_set_id", self.rule_set_id))
        _positive_int("rule_set_revision", self.rule_set_revision)
        object.__setattr__(self, "observation_id", _text("observation_id", self.observation_id))
        object.__setattr__(self, "evaluated_at", _utc("evaluated_at", self.evaluated_at))
        object.__setattr__(self, "operation", _enum(RuleOperation, "operation", self.operation))
        object.__setattr__(self, "overall_state", _enum(EvaluationState, "overall_state", self.overall_state))
        if self.entry_allowed is not None and type(self.entry_allowed) is not bool:
            raise TypeError("entry_allowed must be bool or None")
        results = tuple(self.rule_results)
        if any(not isinstance(item, RuleResult) for item in results):
            raise TypeError("rule_results must contain RuleResult values")
        if len({item.rule_code for item in results}) != len(results):
            raise ValueError("rule_results must not contain duplicate rule codes")
        object.__setattr__(self, "rule_results", results)
        object.__setattr__(self, "blocking_rule_codes", _codes("blocking_rule_codes", self.blocking_rule_codes))
        object.__setattr__(self, "unknown_rule_codes", _codes("unknown_rule_codes", self.unknown_rule_codes))
        object.__setattr__(self, "warnings", _codes("warnings", self.warnings))
        actual_blocking = tuple(item.rule_code for item in results if item.state is EvaluationState.BLOCK)
        actual_unknown = tuple(item.rule_code for item in results if item.state is EvaluationState.UNKNOWN)
        if set(self.blocking_rule_codes) != set(actual_blocking):
            raise ValueError("blocking_rule_codes must exactly match BLOCK rule results")
        if set(self.unknown_rule_codes) != set(actual_unknown):
            raise ValueError("unknown_rule_codes must exactly match UNKNOWN rule results")
        object.__setattr__(self, "freshness_state", _enum(FreshnessState, "freshness_state", self.freshness_state))
        object.__setattr__(self, "calculation_version", _text("calculation_version", self.calculation_version))
        self._validate_authority_semantics()

    def _validate_authority_semantics(self) -> None:
        if self.overall_state is EvaluationState.PASS and not self.rule_results:
            raise ValueError("PASS evaluation requires at least one rule result")
        if self.overall_state is EvaluationState.PASS and (
            self.blocking_rule_codes or self.unknown_rule_codes
        ):
            raise ValueError("PASS evaluation cannot have blocking or unknown rules")
        if self.overall_state is EvaluationState.BLOCK and not self.blocking_rule_codes:
            raise ValueError("BLOCK evaluation requires blocking rules")
        if self.overall_state is EvaluationState.UNKNOWN and not self.unknown_rule_codes:
            raise ValueError("UNKNOWN evaluation requires unknown rules")
        if self.overall_state is EvaluationState.NOT_APPLICABLE and any(
            result.state is not EvaluationState.NOT_APPLICABLE for result in self.rule_results
        ):
            raise ValueError("NOT_APPLICABLE evaluation requires only NOT_APPLICABLE rule results")
        if self.operation is not RuleOperation.ENTRY:
            if self.entry_allowed is not None:
                raise ValueError("non-ENTRY evaluation must not declare entry_allowed")
            return
        if self.freshness_state is not FreshnessState.FRESH:
            if self.entry_allowed is not None:
                raise ValueError("stale or unknown ENTRY evaluation cannot declare entry_allowed")
            if self.overall_state is EvaluationState.PASS:
                raise ValueError("stale or unknown ENTRY evaluation cannot PASS")
        if self.overall_state is EvaluationState.PASS:
            if self.entry_allowed is not True:
                raise ValueError("PASS ENTRY evaluation requires entry_allowed=true")
        elif self.overall_state is EvaluationState.BLOCK:
            if self.entry_allowed is not False:
                raise ValueError("BLOCK ENTRY evaluation requires false and blocking rules")
        elif self.entry_allowed is not None:
            raise ValueError("UNKNOWN/NOT_APPLICABLE ENTRY evaluation requires entry_allowed=None")

    def to_dict(self) -> dict[str, Any]:
        return {name: _serialize(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PropRuleEvaluation":
        names = set(cls.__dataclass_fields__)
        _strict_mapping("PROP rule evaluation", data, required=names)
        values = dict(data)
        values["account_id"] = AccountId(values["account_id"])
        values["evaluated_at"] = _parse_dt("evaluated_at", values["evaluated_at"])
        values["rule_results"] = tuple(
            RuleResult.from_dict(item)
            for item in _serialized_list("rule_results", values["rule_results"])
        )
        for name in ("blocking_rule_codes", "unknown_rule_codes", "warnings"):
            values[name] = tuple(_serialized_list(name, values[name]))
        return cls(**values)
