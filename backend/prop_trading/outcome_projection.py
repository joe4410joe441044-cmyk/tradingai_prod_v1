"""Strict, authority-free display projection for Complete Evaluation Outcomes."""

from __future__ import annotations

from typing import Any, Mapping

from .complete_evaluation import CompleteEvaluationOutcome


PROP_OUTCOME_READ_ONLY_CONTEXT_SCHEMA_VERSION = (
    "tradingai-prop-outcome-read-only-context/v1"
)


def _validated_outcome(
    value: CompleteEvaluationOutcome | Mapping[str, Any],
) -> CompleteEvaluationOutcome:
    if isinstance(value, CompleteEvaluationOutcome):
        # Round-trip through the strict wire constructor. This rechecks nested digests,
        # evidence links, temporal invariants, and derived candidate status.
        return CompleteEvaluationOutcome.from_dict(value.to_dict())
    if isinstance(value, Mapping):
        return CompleteEvaluationOutcome.from_dict(value)
    raise TypeError("outcome must be CompleteEvaluationOutcome or a serialized mapping")


def project_outcome_read_only_context(
    value: CompleteEvaluationOutcome | Mapping[str, Any],
) -> dict[str, Any]:
    """Return the minimal shared fixture/BB projection after strict validation."""

    outcome = _validated_outcome(value)
    bundle = outcome.bundle
    evaluation = outcome.evaluation
    coverage = bundle.coverage
    snapshot = bundle.snapshot
    baseline = bundle.baseline
    observation = bundle.observation

    coverage_reasons = list(coverage.unresolved_requirements)
    coverage_items = []
    for item in coverage.items:
        coverage_reasons.extend(item.unresolved_reason_codes)
        coverage_items.append(
            {
                "ruleCode": item.rule_code,
                "requirementStatus": item.requirement_status.value,
                "role": item.role.value,
                "supportStatus": item.support_status.value,
                "unresolvedReasonCodes": list(item.unresolved_reason_codes),
                "evidenceRefs": list(item.evidence_refs),
            }
        )

    rule_results = [
        {
            "ruleCode": result.rule_code,
            "state": result.state.value,
            "unit": result.unit,
            "actual": None if result.actual is None else str(result.actual),
            "threshold": None if result.threshold is None else str(result.threshold),
            "headroom": None if result.headroom is None else str(result.headroom),
            "reasonCode": result.reason_code,
        }
        for result in evaluation.rule_results
    ]

    return {
        "schemaVersion": PROP_OUTCOME_READ_ONLY_CONTEXT_SCHEMA_VERSION,
        "sourceOutcomeSchemaVersion": outcome.schema_version,
        "synthetic": snapshot.verification_status.value == "SYNTHETIC",
        "purpose": bundle.purpose.value,
        "accountScope": {
            "accountId": str(bundle.account.account_id),
            "identityRevision": bundle.account.revision,
            "executionMode": bundle.account.execution_mode.value,
            "executionVenue": bundle.account.execution_venue.value,
            "program": bundle.account.prop_program.value,
            "planId": snapshot.plan_id,
            "phase": bundle.account.prop_phase.value,
            "currency": snapshot.rule_definition.currency,
        },
        "evaluatedAt": evaluation.evaluated_at.isoformat().replace("+00:00", "Z"),
        "knowledgeCutoffAt": bundle.knowledge_cutoff_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "references": {
            "bundleId": bundle.bundle_id,
            "snapshotId": snapshot.snapshot_id,
            "snapshotDigest": snapshot.content_digest,
            "baselineId": None if baseline is None else baseline.baseline_id,
            "baselineDigest": None if baseline is None else baseline.content_digest,
            "observationId": observation.observation_id,
            "observationDigest": outcome.evidence_link.observation_digest,
            "evidenceLinkId": outcome.evidence_link.link_id,
            "evidenceLinkDigest": outcome.evidence_link.content_digest,
            "outcomeDigest": outcome.content_digest,
        },
        "provenanceValidation": {
            "status": "STRICTLY_VALIDATED",
            "scope": "STRUCTURE_SEMANTICS_AND_REFERENCE_CONSISTENCY_ONLY",
            "authenticityGuaranteed": False,
            "realAccountEligibilityGuaranteed": False,
        },
        "coverage": {
            "schemaVersion": coverage.schema_version,
            "completeness": coverage.completeness.value,
            "operationallyComplete": coverage.operationally_complete,
            "unknownReasonCodes": sorted(set(coverage_reasons)),
            "items": coverage_items,
        },
        "calculation": {
            "schemaVersion": evaluation.schema_version,
            "calculationVersion": evaluation.calculation_version,
            "operation": evaluation.operation.value,
            "freshnessState": evaluation.freshness_state.value,
            "overallState": evaluation.overall_state.value,
            "entryAllowed": evaluation.entry_allowed,
            "candidateStatus": outcome.operational_candidate_status.value,
            "blockingRuleCodes": list(evaluation.blocking_rule_codes),
            "unknownRuleCodes": list(evaluation.unknown_rule_codes),
            "warnings": list(evaluation.warnings),
            "ruleResults": rule_results,
        },
        "authority": {
            "executionAuthorityGranted": False,
            "runtimeReady": False,
            "tradeReady": False,
            "reasonCode": "READ_ONLY_CONTEXT_NO_EXECUTION_AUTHORITY",
        },
    }
