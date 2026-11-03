"""CC-4A isolated, in-memory synthetic PROP account workflow.

This module has no persistence, runtime, credential, exchange, or network I/O.
It only builds existing immutable contracts and invokes the existing pure
complete-evaluation wrapper and read-only projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
import re
from threading import RLock
from typing import Any, Callable, Mapping

from backend.accounts.models import (
    ACCOUNT_IDENTITY_SCHEMA_VERSION,
    AccountId,
    AccountIdentity,
    AccountLifecycleState,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
    PropPhase,
    PropProgram,
)
from backend.prop_trading import (
    ACTIVE_RULES_SELECTION_SCHEMA_VERSION,
    COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION,
    DAILY_BASELINE_SOURCE_SCHEMA_VERSION,
    PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
    PROP_RULE_DEFINITION_SCHEMA_VERSION,
    PROP_RULE_ENGINE_CALCULATION_VERSION,
    PROP_RULE_ENGINE_MAX_ADJUSTED_EXPONENT,
    PROP_RULE_ENGINE_MAX_SIGNIFICANT_DIGITS,
    PROP_RULE_ENGINE_MIN_ADJUSTED_EXPONENT,
    REQUIRED_RULE_COVERAGE_SCHEMA_VERSION,
    ActiveRulesSelection,
    BaselineSourceKind,
    BreachPolicy,
    CompleteEvaluationBundle,
    CompleteEvaluationPurpose,
    Completeness,
    DailyBaselineSource,
    DataQuality,
    EquityComponent,
    EquityComponentState,
    EvaluatorSupportStatus,
    FreshnessState,
    GainTreatment,
    LossModel,
    PropAccountObservation,
    PropRuleDefinition,
    RequiredRuleCoverage,
    RuleCoverageItem,
    RuleCoverageRole,
    RuleEnginePolicy,
    RuleOperation,
    RuleProfileStatus,
    RuleRequirementStatus,
    RuleType,
    SelectionConfirmationStatus,
    SelectionPurpose,
    SelectionSourceKind,
    SnapshotVerificationStatus,
    ThresholdBoundary,
    TradingRulesSnapshot,
    ValueBasis,
    evaluate_complete_bundle,
)
from backend.prop_trading.contracts import SourceKind, VerificationStatus
from backend.prop_trading.outcome_projection import project_outcome_read_only_context


UTC = timezone.utc
_LABEL_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,80}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_CURRENCY_RE = re.compile(r"^[A-Z0-9]{3,12}$")
_PHASES = frozenset({"FREE_TRIAL", "CHALLENGE", "VERIFICATION", "FUNDED", "UNKNOWN"})


class OfflineWorkflowError(ValueError):
    """Safe client-facing validation or session error."""

    def __init__(self, code: str, message: str, *, fields: Mapping[str, str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = dict(fields or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "fields": self.fields}


def _exact(data: Any, names: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping) or set(data) != names:
        raise OfflineWorkflowError("INVALID_INPUT", f"{label} fields do not match the synthetic schema")
    return data


def _request_id(value: Any) -> str:
    if not isinstance(value, str) or not _REQUEST_ID_RE.fullmatch(value):
        raise OfflineWorkflowError("INVALID_REQUEST_ID", "requestId must be a safe opaque identifier")
    return value


def _label(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not _LABEL_RE.fullmatch(value.strip())
        or "/" in value
        or "\\" in value
        or "://" in value
    ):
        raise OfflineWorkflowError("INVALID_ACCOUNT", "label must be 1-80 printable characters", fields={"label": "INVALID"})
    return value.strip()


def _currency(value: Any) -> str:
    if not isinstance(value, str) or value != value.upper() or not _CURRENCY_RE.fullmatch(value):
        raise OfflineWorkflowError("INVALID_ACCOUNT", "currency must be an uppercase asset code", fields={"currency": "INVALID"})
    return value


def _phase(value: Any) -> PropPhase:
    if not isinstance(value, str) or value not in _PHASES:
        raise OfflineWorkflowError("INVALID_ACCOUNT", "phase is unsupported", fields={"phase": "INVALID"})
    return PropPhase(value)


def _decimal(name: str, value: Any, *, positive: bool = False, nullable: bool = False) -> Decimal | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or value.strip() != value:
        raise OfflineWorkflowError("INVALID_INPUT", f"{name} must be a decimal string", fields={name: "INVALID_DECIMAL"})
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise OfflineWorkflowError("INVALID_INPUT", f"{name} must be a decimal string", fields={name: "INVALID_DECIMAL"}) from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise OfflineWorkflowError("INVALID_INPUT", f"{name} is outside the allowed range", fields={name: "INVALID_DECIMAL"})
    digits = len(parsed.as_tuple().digits)
    adjusted = parsed.adjusted() if parsed else 0
    if digits > PROP_RULE_ENGINE_MAX_SIGNIFICANT_DIGITS:
        raise OfflineWorkflowError(
            "INVALID_INPUT",
            f"{name} exceeds the Decimal precision contract",
            fields={name: "DECIMAL_SIGNIFICANT_DIGITS_EXCEEDED"},
        )
    if not PROP_RULE_ENGINE_MIN_ADJUSTED_EXPONENT <= adjusted <= PROP_RULE_ENGINE_MAX_ADJUSTED_EXPONENT:
        raise OfflineWorkflowError(
            "INVALID_INPUT",
            f"{name} exceeds the Decimal exponent contract",
            fields={name: "DECIMAL_EXPONENT_OUT_OF_RANGE"},
        )
    return parsed


def _percentage(name: str, value: Any) -> Decimal:
    parsed = _decimal(name, value, positive=True)
    if parsed > Decimal("100"):
        raise OfflineWorkflowError("INVALID_INPUT", f"{name} must not exceed 100 percent", fields={name: "INVALID_PERCENTAGE"})
    return parsed


def _timestamp(name: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise OfflineWorkflowError("INVALID_INPUT", f"{name} must be RFC3339", fields={name: "INVALID_TIMESTAMP"})
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfflineWorkflowError("INVALID_INPUT", f"{name} must be RFC3339", fields={name: "INVALID_TIMESTAMP"}) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OfflineWorkflowError("INVALID_INPUT", f"{name} must include an offset", fields={name: "INVALID_TIMESTAMP"})
    return parsed.astimezone(UTC)


def _trading_day(value: Any) -> date:
    if not isinstance(value, str):
        raise OfflineWorkflowError("INVALID_INPUT", "tradingDay must be an ISO date", fields={"tradingDay": "INVALID_DATE"})
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise OfflineWorkflowError("INVALID_INPUT", "tradingDay must be an ISO date", fields={"tradingDay": "INVALID_DATE"}) from exc


@dataclass(frozen=True)
class OfflineAccount:
    label: str
    currency: str
    identity: AccountIdentity

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "currency": self.currency,
            "identity": self.identity.to_dict(),
            "synthetic": True,
            "persisted": False,
        }


def _session_locked(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return locked


class OfflinePropSession:
    """Process-local account registry for the isolated preview only."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._accounts: dict[str, OfflineAccount] = {}
        self._sequence = 0
        self._lock = RLock()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("offline workflow clock must be timezone-aware")
        return value.astimezone(UTC)

    def _next_ref(self) -> str:
        self._sequence += 1
        return f"cc-4a-{self._sequence}"

    @_session_locked
    def create_account(self, request: Any) -> dict[str, Any]:
        data = _exact(request, {"requestId", "label", "phase", "currency"}, "account request")
        request_id = _request_id(data["requestId"])
        now = self._now()
        identity = AccountIdentity(
            schema_version=ACCOUNT_IDENTITY_SCHEMA_VERSION,
            account_id=AccountId.new(),
            account_type=AccountType.PROP,
            execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
            execution_venue=ExecutionVenue.BYBIT_DEMO,
            lifecycle_state=AccountLifecycleState.REGISTERED,
            revision=1,
            created_at=now,
            updated_at=now,
            prop_program=PropProgram.HYROTRADER,
            prop_phase=_phase(data["phase"]),
        )
        account = OfflineAccount(_label(data["label"]), _currency(data["currency"]), identity)
        self._accounts[identity.account_id.value] = account
        return {"requestId": request_id, "account": account.to_dict()}

    @_session_locked
    def revise_account(self, request: Any) -> dict[str, Any]:
        data = _exact(request, {"requestId", "accountId", "identityRevision", "label", "phase", "currency"}, "revision request")
        request_id = _request_id(data["requestId"])
        current = self._resolve(data["accountId"], data["identityRevision"])
        now = self._now()
        identity = AccountIdentity(
            schema_version=ACCOUNT_IDENTITY_SCHEMA_VERSION,
            account_id=current.identity.account_id,
            account_type=AccountType.PROP,
            execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
            execution_venue=ExecutionVenue.BYBIT_DEMO,
            lifecycle_state=AccountLifecycleState.REGISTERED,
            revision=current.identity.revision + 1,
            created_at=current.identity.created_at,
            updated_at=max(now, current.identity.updated_at),
            prop_program=PropProgram.HYROTRADER,
            prop_phase=_phase(data["phase"]),
        )
        revised = OfflineAccount(_label(data["label"]), _currency(data["currency"]), identity)
        self._accounts[identity.account_id.value] = revised
        return {"requestId": request_id, "account": revised.to_dict()}

    def _resolve(self, account_id: Any, revision: Any) -> OfflineAccount:
        try:
            parsed = AccountId(account_id)
        except (TypeError, ValueError) as exc:
            raise OfflineWorkflowError("ACCOUNT_NOT_FOUND", "synthetic account scope is unavailable") from exc
        account = self._accounts.get(parsed.value)
        if account is None:
            raise OfflineWorkflowError("ACCOUNT_NOT_FOUND", "synthetic account scope is unavailable")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision != account.identity.revision:
            raise OfflineWorkflowError("ACCOUNT_REVISION_MISMATCH", "synthetic account revision is stale")
        return account

    @_session_locked
    def evaluate(self, request: Any) -> dict[str, Any]:
        data = _exact(
            request,
            {"requestId", "accountId", "identityRevision", "rules", "baseline", "observation", "evaluation"},
            "evaluation request",
        )
        request_id = _request_id(data["requestId"])
        account = self._resolve(data["accountId"], data["identityRevision"])
        try:
            outcome = self._evaluate(account, data, self._next_ref())
        except OfflineWorkflowError:
            raise
        except (TypeError, ValueError) as exc:
            raise OfflineWorkflowError("PRE_EVALUATION_VALIDATION_FAILED", "入力scopeまたは時刻整合性の検証に失敗しました") from exc
        return {
            "requestId": request_id,
            "accountId": account.identity.account_id.value,
            "identityRevision": account.identity.revision,
            "outcome": outcome,
            "authority": {"executionAuthorityGranted": False, "runtimeReady": False, "tradeReady": False},
        }

    def _evaluate(self, account: OfflineAccount, data: Mapping[str, Any], ref: str) -> dict[str, Any]:
        rules = _exact(data["rules"], {"initialBalance", "maximumLossPct", "dailyLossPct", "profitTargetPct"}, "rules")
        baseline_input = _exact(data["baseline"], {"referenceValue", "tradingDay", "timezone", "dayBoundaryLocalTime"}, "baseline")
        observation_input = _exact(data["observation"], {"balance", "equity", "realizedPnl", "unrealizedPnl", "observedAt", "receivedAt"}, "observation")
        evaluation_input = _exact(data["evaluation"], {"evaluatedAt"}, "evaluation")
        if baseline_input["timezone"] != "UTC" or baseline_input["dayBoundaryLocalTime"] != "00:00:00":
            raise OfflineWorkflowError("INVALID_INPUT", "initial offline workflow supports explicit UTC 00:00:00 only", fields={"timezone": "UTC_REQUIRED"})

        evaluated_at = _timestamp("evaluatedAt", evaluation_input["evaluatedAt"])
        observed_at = _timestamp("observedAt", observation_input["observedAt"])
        received_at = _timestamp("receivedAt", observation_input["receivedAt"])
        trading_day = _trading_day(baseline_input["tradingDay"])
        boundary = datetime.combine(trading_day, time(0), UTC)
        if evaluated_at.date() != trading_day:
            raise OfflineWorkflowError("INVALID_INPUT", "tradingDay must match evaluatedAt in UTC", fields={"tradingDay": "SCOPE_MISMATCH"})
        if received_at < observed_at:
            raise OfflineWorkflowError("INVALID_INPUT", "receivedAt must not precede observedAt", fields={"receivedAt": "TEMPORAL_ORDER"})

        initial_balance = _decimal("initialBalance", rules["initialBalance"], positive=True)
        maximum_loss = _percentage("maximumLossPct", rules["maximumLossPct"])
        daily_loss = _percentage("dailyLossPct", rules["dailyLossPct"])
        profit_target = _percentage("profitTargetPct", rules["profitTargetPct"])
        baseline_value = _decimal("referenceValue", baseline_input["referenceValue"], positive=True)
        balance = _decimal("balance", observation_input["balance"], nullable=True)
        equity = _decimal("equity", observation_input["equity"], nullable=True)
        realized = _decimal("realizedPnl", observation_input["realizedPnl"], nullable=True)
        unrealized = _decimal("unrealizedPnl", observation_input["unrealizedPnl"], nullable=True)
        currency = account.currency
        identity = account.identity

        definition = PropRuleDefinition(
            schema_version=PROP_RULE_DEFINITION_SCHEMA_VERSION,
            rule_set_id=f"rules-{ref}", rule_set_revision=1,
            prop_program=PropProgram.HYROTRADER,
            program_product="SYNTHETIC-NOT-OFFICIAL", phase=identity.prop_phase,
            effective_from=evaluated_at - timedelta(days=30), initial_balance=initial_balance,
            currency=currency, loss_model=LossModel.STATIC,
            day_boundary_timezone="UTC", day_boundary_local_time="00:00:00",
            equity_components=(
                EquityComponent("UNREALIZED_PNL", EquityComponentState.INCLUDED),
                EquityComponent("FEES", EquityComponentState.INCLUDED),
                EquityComponent("FUNDING", EquityComponentState.INCLUDED),
            ),
            breach_policy=BreachPolicy(0, "SYNTHETIC_BLOCK", ()),
            source_kind=SourceKind.DOCUMENT,
            source_reference=f"synthetic://cc-4a/{ref}/rules-not-official",
            source_observed_at=evaluated_at - timedelta(days=1),
            verification_status=VerificationStatus.VERIFIED,
            completeness=Completeness.COMPLETE,
            profit_target_pct=profit_target,
            daily_loss_limit_pct=daily_loss,
            maximum_loss_limit_pct=maximum_loss,
            unknown_fields=(),
        )
        snapshot = TradingRulesSnapshot(
            schema_version="tradingai-prop-rules-snapshot/v1",
            snapshot_id=f"snapshot-{ref}", account_id=identity.account_id,
            identity_revision=identity.revision,
            execution_mode=identity.execution_mode, execution_venue=identity.execution_venue,
            prop_program=identity.prop_program, plan_id="SYNTHETIC-NOT-OFFICIAL",
            phase=identity.prop_phase, applicable_from=evaluated_at - timedelta(hours=1),
            applicable_to=None, rule_definition=definition,
            verification_status=SnapshotVerificationStatus.SYNTHETIC,
            verified_at=None, verifier_ref=None,
            source_evidence_refs=(f"synthetic://cc-4a/{ref}/rules",),
            unresolved_requirements=(), supersedes_snapshot_id=None,
        )
        optional_values = {
            "balance": balance, "equity": equity, "available_balance": balance,
            "realized_pnl": realized, "unrealized_pnl": unrealized,
            "fees": Decimal("0"), "funding": Decimal("0"),
            "day_start_equity": baseline_value, "day_realized_pnl": realized,
            "day_profit": realized, "total_margin_used": Decimal("0"),
            "total_notional": Decimal("0"), "open_position_count": 0,
            "open_order_count": 0, "trading_days_count": 1,
        }
        missing = tuple(name for name, value in optional_values.items() if value is None)
        observation = PropAccountObservation(
            schema_version=PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
            observation_id=f"observation-{ref}", account_id=identity.account_id,
            identity_revision=identity.revision, observed_at=observed_at,
            received_at=received_at, source="SYNTHETIC_OFFLINE_INPUT",
            source_revision="cc-4a-v1", freshness=FreshnessState.FRESH,
            quality=DataQuality.PARTIAL if missing else DataQuality.COMPLETE,
            currency=currency, missing_fields=missing, warnings=(), **optional_values,
        )
        baseline = DailyBaselineSource(
            schema_version=DAILY_BASELINE_SOURCE_SCHEMA_VERSION,
            baseline_id=f"baseline-{ref}", revision=1, supersedes_baseline_id=None,
            account_id=identity.account_id, identity_revision=identity.revision,
            execution_mode=identity.execution_mode, execution_venue=identity.execution_venue,
            rules_snapshot_id=snapshot.snapshot_id, rules_snapshot_digest=snapshot.content_digest,
            rule_set_id=definition.rule_set_id, rule_set_revision=definition.rule_set_revision,
            trading_day=trading_day, timezone_name="UTC", day_boundary_local_time="00:00:00",
            boundary_fold=None, effective_at=boundary, observed_at=boundary,
            captured_at=evaluated_at, value_basis=ValueBasis.EQUITY,
            reference_value=baseline_value, currency=currency,
            source_kind=BaselineSourceKind.SYNTHETIC_FIXTURE,
            evidence_ref=f"synthetic://cc-4a/{ref}/baseline",
            verification_status=SnapshotVerificationStatus.SYNTHETIC,
            completeness=Completeness.COMPLETE, unresolved_requirements=(),
        )
        policy = RuleEnginePolicy(
            profile_status=RuleProfileStatus.SYNTHETIC,
            required_rule_codes=tuple(item.value for item in RuleType),
            entry_gate_rule_codes=(RuleType.STATIC_MAXIMUM_LOSS.value, RuleType.DAILY_LOSS.value),
            observation_max_age=timedelta(minutes=10), future_tolerance=timedelta(seconds=2),
            maximum_loss_basis=ValueBasis.EQUITY, daily_loss_basis=ValueBasis.EQUITY,
            profit_target_basis=ValueBasis.BALANCE,
            loss_boundary=ThresholdBoundary.BREACH_BELOW,
            maximum_loss_gain_treatment=GainTreatment.INCREASES_HEADROOM,
            daily_loss_gain_treatment=GainTreatment.INCREASES_HEADROOM,
        )
        items = tuple(
            RuleCoverageItem(
                code.value, RuleRequirementStatus.CONFIRMED_REQUIRED,
                RuleCoverageRole.PROGRESS_ONLY if code is RuleType.PROFIT_TARGET else RuleCoverageRole.ENTRY_RISK_GATE,
                EvaluatorSupportStatus.SUPPORTED,
                (f"synthetic://cc-4a/{ref}/{code.value.lower()}",), (),
            ) for code in RuleType
        )
        coverage = RequiredRuleCoverage(
            schema_version=REQUIRED_RULE_COVERAGE_SCHEMA_VERSION,
            coverage_id=f"coverage-{ref}", account_id=identity.account_id,
            identity_revision=identity.revision, snapshot_id=snapshot.snapshot_id,
            snapshot_digest=snapshot.content_digest, plan_id=snapshot.plan_id,
            phase=identity.prop_phase, evaluator_version=PROP_RULE_ENGINE_CALCULATION_VERSION,
            assessed_at=evaluated_at - timedelta(minutes=2),
            verification_status=SnapshotVerificationStatus.SYNTHETIC,
            completeness=Completeness.COMPLETE,
            evidence_refs=(f"synthetic://cc-4a/{ref}/coverage",),
            unresolved_requirements=(), items=items,
        )
        selection = ActiveRulesSelection(
            schema_version=ACTIVE_RULES_SELECTION_SCHEMA_VERSION,
            selection_id=f"selection-{ref}", selection_revision=1,
            supersedes_selection_id=None, account_id=identity.account_id,
            identity_revision=identity.revision, execution_mode=identity.execution_mode,
            execution_venue=identity.execution_venue, prop_program=identity.prop_program,
            plan_id=snapshot.plan_id, phase=identity.prop_phase,
            purpose=SelectionPurpose.READ_ONLY_MONITORING,
            snapshot_id=snapshot.snapshot_id, snapshot_digest=snapshot.content_digest,
            rule_set_id=definition.rule_set_id, rule_set_revision=definition.rule_set_revision,
            effective_from=evaluated_at, effective_to=None,
            selected_at=evaluated_at - timedelta(minutes=1), invalidated_at=None,
            source_kind=SelectionSourceKind.SYNTHETIC_FIXTURE,
            confirmation_status=SelectionConfirmationStatus.CONFIRMED_FOR_EVALUATION,
            selector_ref=f"synthetic://cc-4a/{ref}/selector",
            evidence_refs=(f"synthetic://cc-4a/{ref}/selection",),
            unresolved_requirements=(),
        )
        bundle = CompleteEvaluationBundle(
            schema_version=COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION,
            bundle_id=f"bundle-{ref}", purpose=CompleteEvaluationPurpose.READ_ONLY_CURRENT,
            account=identity, selection=selection, snapshot=snapshot, baseline=baseline,
            observation=observation, policy=policy, coverage=coverage,
            operation=RuleOperation.READ_ONLY, evaluated_at=evaluated_at,
            knowledge_cutoff_at=evaluated_at,
            evaluator_version=PROP_RULE_ENGINE_CALCULATION_VERSION,
        )
        outcome = evaluate_complete_bundle(
            bundle=bundle, evaluation_id=f"evaluation-{ref}", link_id=f"link-{ref}"
        )
        return project_outcome_read_only_context(outcome)
