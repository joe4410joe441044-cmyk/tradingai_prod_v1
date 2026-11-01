"""Pure, synthetic-first PROP rule evaluation with no I/O or authority."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import (
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    localcontext,
)
from enum import Enum
import re
from typing import Any, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.accounts.models import AccountId, AccountIdentity, AccountType
from backend.prop_trading.contracts import (
    PROP_RULE_EVALUATION_SCHEMA_VERSION,
    Completeness,
    DataQuality,
    EvaluationState,
    FreshnessState,
    PropAccountObservation,
    PropRuleDefinition,
    PropRuleEvaluation,
    RuleOperation,
    RuleResult,
    VerificationStatus,
)


PROP_DAILY_BASELINE_SCHEMA_VERSION = "tradingai-prop-daily-baseline/v1"
PROP_RULE_ENGINE_CALCULATION_VERSION = "tradingai-prop-rule-engine/v2"
PROP_RULE_ENGINE_DECIMAL_PRECISION = 384
PROP_RULE_ENGINE_MAX_SIGNIFICANT_DIGITS = 64
PROP_RULE_ENGINE_MIN_ADJUSTED_EXPONENT = -128
PROP_RULE_ENGINE_MAX_ADJUSTED_EXPONENT = 128
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,127}$")
_CURRENCY_RE = re.compile(r"^[A-Z0-9]{3,12}$")


class RuleType(str, Enum):
    STATIC_MAXIMUM_LOSS = "STATIC_MAXIMUM_LOSS"
    DAILY_LOSS = "DAILY_LOSS"
    PROFIT_TARGET = "PROFIT_TARGET"


class ValueBasis(str, Enum):
    BALANCE = "BALANCE"
    EQUITY = "EQUITY"


class ThresholdBoundary(str, Enum):
    BREACH_BELOW = "BREACH_BELOW"
    BREACH_AT_OR_BELOW = "BREACH_AT_OR_BELOW"


class GainTreatment(str, Enum):
    INCREASES_HEADROOM = "INCREASES_HEADROOM"
    LOSS_USED_FLOOR_ZERO = "LOSS_USED_FLOOR_ZERO"


class RuleProfileStatus(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    VERIFIED_OFFICIAL = "VERIFIED_OFFICIAL"
    UNVERIFIED = "UNVERIFIED"


def _utc(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _finite_decimal(name: str, value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _enum(enum_type, name: str, value: Any):
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be {enum_type.__name__}")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unknown {name}") from exc


def _parse_decimal(name: str, value: Any) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a decimal string")
    try:
        return _finite_decimal(name, Decimal(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal string") from exc


def _parse_datetime(name: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an RFC3339 string")
    try:
        return _utc(name, datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"{name} must be an RFC3339 timestamp") from exc


def _parse_boundary(value: str) -> time:
    value = _text("day_boundary_local_time", value)
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("day_boundary_local_time must be an ISO local time") from exc
    if parsed.tzinfo is not None:
        raise ValueError("day_boundary_local_time must not include an offset")
    return parsed


def _zone(value: str) -> ZoneInfo:
    value = _text("timezone_name", value)
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone_name must be an IANA timezone") from exc


def trading_day_at(moment: datetime, timezone_name: str, boundary_local_time: str) -> date:
    """Return a trading day from explicit time inputs without reading a clock."""
    localized = _utc("moment", moment).astimezone(_zone(timezone_name))
    boundary = _parse_boundary(boundary_local_time)
    local_clock = localized.timetz().replace(tzinfo=None)
    return localized.date() if local_clock >= boundary else localized.date() - timedelta(days=1)


def _boundary_candidates(trading_day: date, timezone_name: str, boundary_local_time: str) -> Tuple[datetime, ...]:
    """Resolve a local reset without silently choosing a DST fold."""
    zone = _zone(timezone_name)
    naive = datetime.combine(trading_day, _parse_boundary(boundary_local_time))
    candidates = []
    for fold in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold)
        instant = local.astimezone(timezone.utc)
        round_trip = instant.astimezone(zone)
        if round_trip.replace(tzinfo=None) == naive and round_trip.fold == fold:
            candidates.append(instant)
    return tuple(dict.fromkeys(candidates))


def _decimal_input_reason(*values: Decimal) -> Optional[str]:
    for value in values:
        digits = len(value.as_tuple().digits)
        adjusted = value.adjusted() if value else 0
        if digits > PROP_RULE_ENGINE_MAX_SIGNIFICANT_DIGITS:
            return "DECIMAL_SIGNIFICANT_DIGITS_EXCEEDED"
        if not PROP_RULE_ENGINE_MIN_ADJUSTED_EXPONENT <= adjusted <= PROP_RULE_ENGINE_MAX_ADJUSTED_EXPONENT:
            return "DECIMAL_EXPONENT_OUT_OF_RANGE"
    return None


@contextmanager
def _calculation_context():
    """Use an exact, engine-owned context without mutating caller state."""
    with localcontext() as context:
        context.prec = PROP_RULE_ENGINE_DECIMAL_PRECISION
        context.Emin = -999999
        context.Emax = 999999
        context.clear_flags()
        for signal in (DivisionByZero, InvalidOperation, Overflow, Inexact, Rounded):
            context.traps[signal] = True
        yield


@dataclass(frozen=True)
class DailyBaseline:
    schema_version: str
    baseline_id: str
    account_id: AccountId
    rule_set_id: str
    rule_set_revision: int
    trading_day: date
    timezone_name: str
    day_boundary_local_time: str
    effective_at: datetime
    value_basis: ValueBasis
    reference_value: Decimal
    currency: str
    source: str
    verification_status: VerificationStatus

    def __post_init__(self) -> None:
        if self.schema_version != PROP_DAILY_BASELINE_SCHEMA_VERSION:
            raise ValueError("unsupported daily baseline schema")
        object.__setattr__(self, "baseline_id", _text("baseline_id", self.baseline_id))
        if not isinstance(self.account_id, AccountId):
            raise TypeError("account_id must be AccountId")
        object.__setattr__(self, "rule_set_id", _text("rule_set_id", self.rule_set_id))
        if isinstance(self.rule_set_revision, bool) or not isinstance(self.rule_set_revision, int) or self.rule_set_revision < 1:
            raise ValueError("rule_set_revision must be a positive integer")
        if not isinstance(self.trading_day, date) or isinstance(self.trading_day, datetime):
            raise TypeError("trading_day must be date")
        _zone(self.timezone_name)
        _parse_boundary(self.day_boundary_local_time)
        object.__setattr__(self, "effective_at", _utc("effective_at", self.effective_at))
        object.__setattr__(self, "value_basis", _enum(ValueBasis, "value_basis", self.value_basis))
        _finite_decimal("reference_value", self.reference_value)
        currency = _text("currency", self.currency).upper()
        if not _CURRENCY_RE.fullmatch(currency):
            raise ValueError("currency must be a 3-12 character uppercase asset code")
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "source", _text("source", self.source))
        object.__setattr__(self, "verification_status", _enum(VerificationStatus, "verification_status", self.verification_status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "baseline_id": self.baseline_id,
            "account_id": self.account_id.value,
            "rule_set_id": self.rule_set_id,
            "rule_set_revision": self.rule_set_revision,
            "trading_day": self.trading_day.isoformat(),
            "timezone_name": self.timezone_name,
            "day_boundary_local_time": self.day_boundary_local_time,
            "effective_at": self.effective_at.isoformat().replace("+00:00", "Z"),
            "value_basis": self.value_basis.value,
            "reference_value": format(self.reference_value, "f"),
            "currency": self.currency,
            "source": self.source,
            "verification_status": self.verification_status.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DailyBaseline":
        names = set(cls.__dataclass_fields__)
        if not isinstance(data, Mapping) or set(data) != names:
            raise ValueError("daily baseline fields must exactly match schema")
        try:
            trading_day = date.fromisoformat(data["trading_day"])
        except (TypeError, ValueError) as exc:
            raise ValueError("trading_day must be an ISO date") from exc
        return cls(
            schema_version=data["schema_version"],
            baseline_id=data["baseline_id"],
            account_id=AccountId(data["account_id"]),
            rule_set_id=data["rule_set_id"],
            rule_set_revision=data["rule_set_revision"],
            trading_day=trading_day,
            timezone_name=data["timezone_name"],
            day_boundary_local_time=data["day_boundary_local_time"],
            effective_at=_parse_datetime("effective_at", data["effective_at"]),
            value_basis=data["value_basis"],
            reference_value=_parse_decimal("reference_value", data["reference_value"]),
            currency=data["currency"],
            source=data["source"],
            verification_status=data["verification_status"],
        )


@dataclass(frozen=True)
class RuleEnginePolicy:
    profile_status: RuleProfileStatus
    required_rule_codes: Tuple[str, ...]
    entry_gate_rule_codes: Tuple[str, ...]
    observation_max_age: timedelta
    future_tolerance: timedelta
    maximum_loss_basis: ValueBasis
    daily_loss_basis: ValueBasis
    profit_target_basis: ValueBasis
    loss_boundary: ThresholdBoundary
    maximum_loss_gain_treatment: GainTreatment
    daily_loss_gain_treatment: GainTreatment

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_status", _enum(RuleProfileStatus, "profile_status", self.profile_status))
        codes = tuple(_text("required_rule_codes", value) for value in self.required_rule_codes)
        if len(set(codes)) != len(codes) or any(not _CODE_RE.fullmatch(code) for code in codes):
            raise ValueError("required_rule_codes must be unique safe codes")
        object.__setattr__(self, "required_rule_codes", codes)
        gates = tuple(_text("entry_gate_rule_codes", value) for value in self.entry_gate_rule_codes)
        if len(set(gates)) != len(gates) or any(not _CODE_RE.fullmatch(code) for code in gates):
            raise ValueError("entry_gate_rule_codes must be unique safe codes")
        if not set(gates).issubset(codes):
            raise ValueError("entry_gate_rule_codes must be a subset of required_rule_codes")
        if RuleType.PROFIT_TARGET.value in gates:
            raise ValueError("profit target cannot be an entry risk gate")
        object.__setattr__(self, "entry_gate_rule_codes", gates)
        if not isinstance(self.observation_max_age, timedelta) or self.observation_max_age <= timedelta(0):
            raise ValueError("observation_max_age must be a positive timedelta")
        if not isinstance(self.future_tolerance, timedelta) or self.future_tolerance < timedelta(0):
            raise ValueError("future_tolerance must be a nonnegative timedelta")
        for name, enum_type in (
            ("maximum_loss_basis", ValueBasis), ("daily_loss_basis", ValueBasis),
            ("profit_target_basis", ValueBasis), ("loss_boundary", ThresholdBoundary),
            ("maximum_loss_gain_treatment", GainTreatment), ("daily_loss_gain_treatment", GainTreatment),
        ):
            object.__setattr__(self, name, _enum(enum_type, name, getattr(self, name)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_status": self.profile_status.value,
            "required_rule_codes": list(self.required_rule_codes),
            "entry_gate_rule_codes": list(self.entry_gate_rule_codes),
            "observation_max_age_seconds": format(Decimal(str(self.observation_max_age.total_seconds())), "f"),
            "future_tolerance_seconds": format(Decimal(str(self.future_tolerance.total_seconds())), "f"),
            "maximum_loss_basis": self.maximum_loss_basis.value,
            "daily_loss_basis": self.daily_loss_basis.value,
            "profit_target_basis": self.profit_target_basis.value,
            "loss_boundary": self.loss_boundary.value,
            "maximum_loss_gain_treatment": self.maximum_loss_gain_treatment.value,
            "daily_loss_gain_treatment": self.daily_loss_gain_treatment.value,
        }


class PropRuleEngine:
    """Evaluate supported rules against explicit immutable inputs."""

    def evaluate(
        self, *, evaluation_id: str, account: AccountIdentity,
        definition: PropRuleDefinition, observation: PropAccountObservation,
        daily_baseline: Optional[DailyBaseline], evaluated_at: datetime,
        policy: RuleEnginePolicy, operation: RuleOperation = RuleOperation.ENTRY,
    ) -> PropRuleEvaluation:
        evaluation_id = _text("evaluation_id", evaluation_id)
        if not isinstance(account, AccountIdentity):
            raise TypeError("account must be AccountIdentity")
        if not isinstance(definition, PropRuleDefinition):
            raise TypeError("definition must be PropRuleDefinition")
        if not isinstance(observation, PropAccountObservation):
            raise TypeError("observation must be PropAccountObservation")
        if daily_baseline is not None and not isinstance(daily_baseline, DailyBaseline):
            raise TypeError("daily_baseline must be DailyBaseline or None")
        if not isinstance(policy, RuleEnginePolicy):
            raise TypeError("policy must be RuleEnginePolicy")
        operation = _enum(RuleOperation, "operation", operation)
        evaluated_at = _utc("evaluated_at", evaluated_at)
        reason = self._scope_reason(account, definition, observation, evaluated_at, policy)
        if reason is not None:
            results = tuple(self._unknown(code, reason) for code in policy.required_rule_codes)
        else:
            results = tuple(
                self._evaluate_rule(code, definition, observation, daily_baseline, evaluated_at, policy)
                for code in policy.required_rule_codes
            )
        if operation is RuleOperation.ENTRY:
            if not policy.entry_gate_rule_codes:
                results += (self._unknown("ENTRY_RISK_GATE_SET", "ENTRY_RISK_GATE_SET_MISSING"),)
            elif any(
                item.state not in {EvaluationState.PASS, EvaluationState.BLOCK, EvaluationState.UNKNOWN}
                for item in results if item.rule_code in policy.entry_gate_rule_codes
            ):
                results += (self._unknown("ENTRY_RISK_GATE_SET", "ENTRY_RISK_GATE_NOT_PASSING"),)
        return self._evaluation(evaluation_id, account, definition, observation, evaluated_at, operation, results)

    @staticmethod
    def _scope_reason(account, definition, observation, evaluated_at, policy) -> Optional[str]:
        if policy.profile_status is RuleProfileStatus.UNVERIFIED:
            return "PROFILE_UNVERIFIED"
        if policy.profile_status is RuleProfileStatus.SYNTHETIC and not definition.program_product.startswith("SYNTHETIC"):
            return "SYNTHETIC_PROFILE_REQUIRED"
        if policy.profile_status is RuleProfileStatus.VERIFIED_OFFICIAL:
            return "ACCOUNT_RULES_SNAPSHOT_REQUIRED"
        if definition.completeness is not Completeness.COMPLETE:
            return "RULE_DEFINITION_INCOMPLETE"
        if account.account_type is not AccountType.PROP:
            return "ACCOUNT_NOT_PROP"
        if account.account_id != observation.account_id:
            return "ACCOUNT_SCOPE_MISMATCH"
        if account.revision != observation.identity_revision:
            return "IDENTITY_REVISION_MISMATCH"
        if account.prop_program != definition.prop_program or account.prop_phase != definition.phase:
            return "PROFILE_ACCOUNT_PHASE_MISMATCH"
        if definition.currency != observation.currency:
            return "CURRENCY_MISMATCH"
        if evaluated_at < definition.effective_from or (definition.effective_to is not None and evaluated_at >= definition.effective_to):
            return "RULE_DEFINITION_NOT_EFFECTIVE"
        if definition.source_observed_at > evaluated_at:
            return "RULE_SOURCE_FROM_FUTURE"
        if observation.quality is DataQuality.INVALID:
            return "OBSERVATION_INVALID"
        if observation.freshness is not FreshnessState.FRESH:
            return "OBSERVATION_NOT_FRESH"
        if observation.observed_at > evaluated_at + policy.future_tolerance:
            return "OBSERVATION_FROM_FUTURE"
        if observation.received_at > evaluated_at + policy.future_tolerance:
            return "OBSERVATION_RECEIVED_FROM_FUTURE"
        if observation.received_at < observation.observed_at:
            return "OBSERVATION_RECEIPT_PRECEDES_SOURCE"
        if evaluated_at - observation.observed_at > policy.observation_max_age:
            return "OBSERVATION_STALE"
        return None

    def _evaluate_rule(self, code, definition, observation, baseline, evaluated_at, policy):
        if code == RuleType.STATIC_MAXIMUM_LOSS.value:
            return self._maximum_loss(definition, observation, policy)
        if code == RuleType.DAILY_LOSS.value:
            return self._daily_loss(definition, observation, baseline, evaluated_at, policy)
        if code == RuleType.PROFIT_TARGET.value:
            return self._profit_target(definition, observation, policy)
        return self._unknown(code, "UNSUPPORTED_REQUIRED_RULE")

    @staticmethod
    def _value(observation, basis):
        return observation.balance if basis is ValueBasis.BALANCE else observation.equity

    @staticmethod
    def _equity_semantics_known(definition, basis):
        if basis is not ValueBasis.EQUITY:
            return True
        return bool(definition.equity_components) and all(
            component.state.value != "UNKNOWN" for component in definition.equity_components
        )

    @staticmethod
    def _limit(initial, percentage):
        return None if percentage is None else initial * percentage / Decimal("100")

    @staticmethod
    def _breached(value, floor, boundary):
        return value < floor if boundary is ThresholdBoundary.BREACH_BELOW else value <= floor

    @staticmethod
    def _loss_metrics(reference, current, limit, treatment):
        raw = reference - current
        used = max(raw, Decimal("0")) if treatment is GainTreatment.LOSS_USED_FLOOR_ZERO else raw
        return used, limit - used

    def _maximum_loss(self, definition, observation, policy):
        code = RuleType.STATIC_MAXIMUM_LOSS.value
        if definition.loss_model.value != "STATIC":
            return self._unknown(code, "STATIC_LOSS_MODEL_REQUIRED")
        percentage = definition.maximum_loss_limit_pct
        current = self._value(observation, policy.maximum_loss_basis)
        if not self._equity_semantics_known(definition, policy.maximum_loss_basis):
            return self._unknown(code, "EQUITY_COMPONENTS_UNKNOWN")
        if percentage is None or "maximum_loss_limit_pct" in definition.unknown_fields:
            return self._unknown(code, "MAXIMUM_LOSS_PARAMETER_MISSING")
        if current is None:
            return self._unknown(code, f"{policy.maximum_loss_basis.value}_MISSING")
        reason = _decimal_input_reason(definition.initial_balance, percentage, current)
        if reason is not None:
            return self._unknown(code, reason)
        try:
            with _calculation_context():
                limit = self._limit(definition.initial_balance, percentage)
                floor = definition.initial_balance - limit
                used, headroom = self._loss_metrics(definition.initial_balance, current, limit, policy.maximum_loss_gain_treatment)
        except DecimalException:
            return self._unknown(code, "DECIMAL_CALCULATION_ERROR")
        if self._breached(current, floor, policy.loss_boundary):
            return RuleResult(code, EvaluationState.BLOCK, definition.currency, used, limit, headroom, "MAXIMUM_LOSS_BREACH")
        return RuleResult(code, EvaluationState.PASS, definition.currency, used, limit, headroom, None)

    def _daily_loss(self, definition, observation, baseline, evaluated_at, policy):
        code = RuleType.DAILY_LOSS.value
        percentage = definition.daily_loss_limit_pct
        current = self._value(observation, policy.daily_loss_basis)
        if not self._equity_semantics_known(definition, policy.daily_loss_basis):
            return self._unknown(code, "EQUITY_COMPONENTS_UNKNOWN")
        if percentage is None or "daily_loss_limit_pct" in definition.unknown_fields:
            return self._unknown(code, "DAILY_LOSS_PARAMETER_MISSING")
        if current is None:
            return self._unknown(code, f"{policy.daily_loss_basis.value}_MISSING")
        reason = self._baseline_reason(definition, observation, baseline, evaluated_at, policy)
        if reason is not None:
            return self._unknown(code, reason)
        reason = _decimal_input_reason(definition.initial_balance, percentage, baseline.reference_value, current)
        if reason is not None:
            return self._unknown(code, reason)
        try:
            with _calculation_context():
                limit = self._limit(definition.initial_balance, percentage)
                floor = baseline.reference_value - limit
                used, headroom = self._loss_metrics(baseline.reference_value, current, limit, policy.daily_loss_gain_treatment)
        except DecimalException:
            return self._unknown(code, "DECIMAL_CALCULATION_ERROR")
        if self._breached(current, floor, policy.loss_boundary):
            return RuleResult(code, EvaluationState.BLOCK, definition.currency, used, limit, headroom, "DAILY_LOSS_BREACH")
        return RuleResult(code, EvaluationState.PASS, definition.currency, used, limit, headroom, None)

    @staticmethod
    def _baseline_reason(definition, observation, baseline, evaluated_at, policy):
        if baseline is None:
            return "DAILY_BASELINE_MISSING"
        if baseline.account_id != observation.account_id:
            return "BASELINE_ACCOUNT_MISMATCH"
        if baseline.rule_set_id != definition.rule_set_id or baseline.rule_set_revision != definition.rule_set_revision:
            return "BASELINE_RULE_VERSION_MISMATCH"
        if baseline.currency != definition.currency:
            return "BASELINE_CURRENCY_MISMATCH"
        if baseline.value_basis is not policy.daily_loss_basis:
            return "BASELINE_VALUE_BASIS_MISMATCH"
        if baseline.timezone_name != definition.day_boundary_timezone or baseline.day_boundary_local_time != definition.day_boundary_local_time:
            return "BASELINE_TIME_BOUNDARY_MISMATCH"
        if baseline.verification_status is not VerificationStatus.VERIFIED:
            return "BASELINE_UNVERIFIED"
        if baseline.effective_at > evaluated_at:
            return "BASELINE_FROM_FUTURE"
        candidates = _boundary_candidates(
            baseline.trading_day, baseline.timezone_name, baseline.day_boundary_local_time
        )
        if not candidates:
            return "BASELINE_BOUNDARY_NONEXISTENT"
        if len(candidates) > 1:
            return "BASELINE_BOUNDARY_AMBIGUOUS"
        if baseline.effective_at != candidates[0]:
            return "BASELINE_NOT_AT_DAY_BOUNDARY"
        expected = trading_day_at(evaluated_at, definition.day_boundary_timezone, definition.day_boundary_local_time)
        if baseline.trading_day != expected:
            return "BASELINE_TRADING_DAY_MISMATCH"
        if trading_day_at(baseline.effective_at, baseline.timezone_name, baseline.day_boundary_local_time) != baseline.trading_day:
            return "BASELINE_EFFECTIVE_DAY_MISMATCH"
        return None

    def _profit_target(self, definition, observation, policy):
        code = RuleType.PROFIT_TARGET.value
        percentage = definition.profit_target_pct
        current = self._value(observation, policy.profit_target_basis)
        if not self._equity_semantics_known(definition, policy.profit_target_basis):
            return self._unknown(code, "EQUITY_COMPONENTS_UNKNOWN")
        if percentage is None or "profit_target_pct" in definition.unknown_fields:
            return self._unknown(code, "PROFIT_TARGET_PARAMETER_MISSING")
        if current is None:
            return self._unknown(code, f"{policy.profit_target_basis.value}_MISSING")
        reason = _decimal_input_reason(definition.initial_balance, percentage, current)
        if reason is not None:
            return self._unknown(code, reason)
        try:
            with _calculation_context():
                target = self._limit(definition.initial_balance, percentage)
                progress = current - definition.initial_balance
                remaining = target - progress
        except DecimalException:
            return self._unknown(code, "DECIMAL_CALCULATION_ERROR")
        if progress >= target:
            return RuleResult(code, EvaluationState.PASS, definition.currency, progress, target, remaining, "TARGET_REACHED")
        return RuleResult(code, EvaluationState.NOT_APPLICABLE, definition.currency, progress, target, remaining, "TARGET_NOT_REACHED")

    @staticmethod
    def _unknown(code, reason):
        return RuleResult(code, EvaluationState.UNKNOWN, "UNKNOWN", None, None, None, reason)

    @staticmethod
    def _evaluation(evaluation_id, account, definition, observation, evaluated_at, operation, results):
        blocking = tuple(item.rule_code for item in results if item.state is EvaluationState.BLOCK)
        unknown = tuple(item.rule_code for item in results if item.state is EvaluationState.UNKNOWN)
        if blocking:
            overall = EvaluationState.BLOCK
        elif unknown:
            overall = EvaluationState.UNKNOWN
        elif not results or all(item.state is EvaluationState.NOT_APPLICABLE for item in results):
            overall = EvaluationState.NOT_APPLICABLE
        else:
            overall = EvaluationState.PASS
        entry_allowed = None
        if operation is RuleOperation.ENTRY:
            entry_allowed = True if overall is EvaluationState.PASS else False if overall is EvaluationState.BLOCK else None
        return PropRuleEvaluation(
            schema_version=PROP_RULE_EVALUATION_SCHEMA_VERSION,
            evaluation_id=evaluation_id, account_id=account.account_id,
            rule_set_id=definition.rule_set_id, rule_set_revision=definition.rule_set_revision,
            observation_id=observation.observation_id, evaluated_at=evaluated_at,
            operation=operation, overall_state=overall, entry_allowed=entry_allowed,
            rule_results=results, blocking_rule_codes=blocking, unknown_rule_codes=unknown,
            warnings=("RULE_COMPATIBILITY_ONLY_NO_EXECUTION_AUTHORITY",),
            freshness_state=observation.freshness,
            calculation_version=PROP_RULE_ENGINE_CALCULATION_VERSION,
        )
