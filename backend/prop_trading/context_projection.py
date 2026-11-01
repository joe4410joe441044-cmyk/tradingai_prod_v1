"""CC-owned, read-only PROP context output for a future BB integration.

The projection is not wired into the canonical BB context chain.  It is built
only from already supplied immutable values and can never grant execution
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple
import re

from backend.accounts.models import AccountIdentity, AccountType, ensure_account_match
from .contracts import (
    DataQuality,
    PropAccountObservation,
    PropRuleDefinition,
    PropRuleEvaluation,
)


_SAFE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,127}$")
PROP_ACCOUNT_CONTEXT_SCHEMA_VERSION = "tradingai-prop-account-context/v2"
_EVIDENCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _code(name: str, value: object) -> str:
    normalized = _text(name, value)
    if not _SAFE_CODE_RE.fullmatch(normalized):
        raise ValueError(f"{name} must be a safe typed code")
    return normalized


@dataclass(frozen=True)
class AuthorityObservation:
    """Observed authority only; its presence is never an execution grant."""

    entry_authority_observed: bool
    reason_codes: Tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        if type(self.entry_authority_observed) is not bool:
            raise TypeError("entry_authority_observed must be bool")
        reasons = tuple(_code("reason_code", value) for value in self.reason_codes)
        if len(set(reasons)) != len(reasons):
            raise ValueError("reason_codes must not contain duplicates")
        if not self.entry_authority_observed and not reasons:
            raise ValueError("false authority observation requires reason_codes")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "source", _code("source", self.source))


@dataclass(frozen=True)
class PropAccountContext:
    identity: AccountIdentity
    observation: PropAccountObservation
    evaluation: PropRuleEvaluation
    authority: AuthorityObservation
    rule_definition: Optional[PropRuleDefinition] = None
    evidence_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identity, AccountIdentity):
            raise TypeError("identity must be AccountIdentity")
        if self.identity.account_type is not AccountType.PROP:
            raise ValueError("PROP context requires a PROP account identity")
        if not isinstance(self.observation, PropAccountObservation):
            raise TypeError("observation must be PropAccountObservation")
        if not isinstance(self.evaluation, PropRuleEvaluation):
            raise TypeError("evaluation must be PropRuleEvaluation")
        if not isinstance(self.authority, AuthorityObservation):
            raise TypeError("authority must be AuthorityObservation")
        ensure_account_match(self.identity.account_id, self.observation.account_id, label="context observation")
        ensure_account_match(self.identity.account_id, self.evaluation.account_id, label="context evaluation")
        if self.identity.revision != self.observation.identity_revision:
            raise ValueError("context identity revision mismatch")
        if self.observation.observation_id != self.evaluation.observation_id:
            raise ValueError("context observation reference mismatch")
        if self.observation.freshness is not self.evaluation.freshness_state:
            raise ValueError("context freshness mismatch")
        if self.rule_definition is not None:
            if not isinstance(self.rule_definition, PropRuleDefinition):
                raise TypeError("rule_definition must be PropRuleDefinition or None")
            if self.rule_definition.rule_set_id != self.evaluation.rule_set_id:
                raise ValueError("context rule_set_id mismatch")
            if self.rule_definition.rule_set_revision != self.evaluation.rule_set_revision:
                raise ValueError("context rule_set_revision mismatch")
            if self.rule_definition.prop_program is not self.identity.prop_program:
                raise ValueError("context PROP program mismatch")
            if self.rule_definition.phase is not self.identity.prop_phase:
                raise ValueError("context PROP phase mismatch")
        refs = tuple(self.evidence_refs)
        if any(not isinstance(value, str) or not _EVIDENCE_REF_RE.fullmatch(value) for value in refs):
            raise ValueError("evidence_refs must contain opaque safe references")
        if len(set(refs)) != len(refs):
            raise ValueError("evidence_refs must not contain duplicates")
        object.__setattr__(self, "evidence_refs", refs)

    @property
    def availability(self) -> str:
        if self.observation.quality is DataQuality.INVALID:
            return "UNAVAILABLE"
        # v2 fails closed until an account-bound Rules Snapshot and evaluation
        # evidence link are deliberately integrated in a later task.
        return "PARTIAL"

    def to_dict(self) -> dict[str, Any]:
        observation = self.observation.to_dict()
        evaluation = self.evaluation.to_dict()
        rule = self.rule_definition.to_dict() if self.rule_definition is not None else None
        return {
            "schemaVersion": PROP_ACCOUNT_CONTEXT_SCHEMA_VERSION,
            "availability": self.availability,
            "rulesSnapshotStatus": "RULES_SNAPSHOT_REQUIRED",
            "observedAt": observation["observed_at"],
            "account": {
                "accountId": self.identity.account_id.value,
                "accountType": self.identity.account_type.value,
                "executionMode": self.identity.execution_mode.value,
                "executionVenue": self.identity.execution_venue.value,
                "propProgram": self.identity.prop_program.value,
                "phase": self.identity.prop_phase.value,
                "identityRevision": self.identity.revision,
            },
            "observation": {
                "observationId": observation["observation_id"],
                "freshness": observation["freshness"],
                "quality": observation["quality"],
                "currency": observation["currency"],
                "balance": observation["balance"],
                "equity": observation["equity"],
                "availableBalance": observation["available_balance"],
                "realizedPnl": observation["realized_pnl"],
                "unrealizedPnl": observation["unrealized_pnl"],
                "dayStartEquity": observation["day_start_equity"],
                "openPositionCount": observation["open_position_count"],
                "openOrderCount": observation["open_order_count"],
                "missingFields": observation["missing_fields"],
            },
            "rule": None if rule is None else {
                "ruleSetId": rule["rule_set_id"],
                "ruleSetRevision": rule["rule_set_revision"],
                "programProduct": rule["program_product"],
                "verificationStatus": rule["verification_status"],
                "completeness": rule["completeness"],
                "unknownFields": rule["unknown_fields"],
                "sourceObservedAt": rule["source_observed_at"],
            },
            "ruleEvaluation": {
                "evaluationId": evaluation["evaluation_id"],
                "ruleSetId": evaluation["rule_set_id"],
                "ruleSetRevision": evaluation["rule_set_revision"],
                "evaluationTrust": "UNVERIFIED",
                "overallState": evaluation["overall_state"],
                "entryAllowed": evaluation["entry_allowed"],
                "blockingRuleCodes": evaluation["blocking_rule_codes"],
                "unknownRuleCodes": evaluation["unknown_rule_codes"],
                "evaluatedAt": evaluation["evaluated_at"],
                "freshness": evaluation["freshness_state"],
            },
            "authority": {
                "entryAuthorityObserved": self.authority.entry_authority_observed,
                "reasonCodes": list(self.authority.reason_codes),
                "source": self.authority.source,
                "grantsExecutionAuthority": False,
            },
            "evidenceRefs": list(self.evidence_refs),
            "unavailable": ["credentials", "rawVenuePayload", "executionControl"],
            "readOnly": True,
            "integrationStatus": "CC_CONTRACT_NOT_BB_INTEGRATED",
        }


def build_prop_account_context(
    *,
    identity: AccountIdentity,
    observation: PropAccountObservation,
    evaluation: PropRuleEvaluation,
    authority: AuthorityObservation,
    rule_definition: Optional[PropRuleDefinition] = None,
    evidence_refs: Tuple[str, ...] = (),
) -> PropAccountContext:
    """Build a validated context without accessing runtime, adapters, or files."""

    return PropAccountContext(
        identity=identity,
        observation=observation,
        evaluation=evaluation,
        authority=authority,
        rule_definition=rule_definition,
        evidence_refs=evidence_refs,
    )
