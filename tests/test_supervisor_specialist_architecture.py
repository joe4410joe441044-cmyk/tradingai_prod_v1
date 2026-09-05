"""Focused D-6 tests: deterministic Supervisor Specialist architecture.

Each test builds authoritative read-only evidence (a ``ReadOnlySupervisorSnapshot``
and optionally D-5 ``UnifiedTradingTrace`` objects) and verifies the deterministic
specialist pipeline without any provider, operational action, or mutation.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from backend.runtime.trading_trace import make_event, new_trace_id
from backend.runtime.unified_trace import (
    StaticTraceEvidenceSource,
    UnifiedTraceAssembler,
)
from backend.supervisor.contracts import (
    CapitalSource,
    DomainSnapshot,
    Freshness,
    MoneyManagementSnapshot,
    ReadOnlySupervisorSnapshot,
    SnapshotWarning,
)
from backend.supervisor.failure_codes import SupervisorFailureCode
from backend.supervisor.runtime_snapshot_adapter import (
    RuntimeAuthorityReaders,
    RuntimeSnapshotAdapter,
)

from backend.supervisor.specialists import (
    SpecialistSeverity,
    SpecialistStatus,
    aggregate_specialists,
    build_bounded_llm_context,
    evaluate_execution,
    evaluate_money_management,
    evaluate_strategy,
    evaluate_system_health,
    worst_severity,
    worst_status,
)


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)


def _domain(
    *,
    freshness: Freshness = Freshness.FRESH,
    evaluated_at: datetime | None = NOW,
    source: str = "AUTHORITATIVE",
    **kwargs: Any,
) -> DomainSnapshot:
    return DomainSnapshot(
        freshness=freshness, evaluatedAt=evaluated_at, source=source, **kwargs
    )


def make_snapshot(
    *,
    bot_status: str = "RUNNING",
    loop_enabled: bool = True,
    loop_state: str = "RUNNING",
    auto_trade_enabled: bool = False,
    market_ready: bool = True,
    market_stale: bool = False,
    decision_status: str = "HOLD",
    decision_freshness: Freshness = Freshness.FRESH,
    backend_status: str = "ok",
    runtime_healthy: bool = True,
    health_freshness: Freshness = Freshness.FRESH,
    exec_freshness: Freshness = Freshness.FRESH,
    exec_state: str = "SYNCHRONIZED",
    pending_order: str = "NONE",
    mm_freshness: Freshness = Freshness.FRESH,
    mm_ruin_guard: str = "NORMAL",
    mm_entry_allowed: bool = True,
    mm_authority_fresh: bool = True,
    overall_freshness: Freshness = Freshness.FRESH,
    warnings: tuple[SnapshotWarning, ...] = (),
) -> ReadOnlySupervisorSnapshot:
    return ReadOnlySupervisorSnapshot(
        capturedAt=NOW,
        overallFreshness=overall_freshness,
        bot=_domain(status=bot_status),
        loop=_domain(enabled=loop_enabled, state=loop_state),
        trade=_domain(
            selectedMode="PAPER", dryRun=True, autoTradeEnabled=auto_trade_enabled,
            realOrderAllowed=False,
        ),
        governance=_domain(mode="PAPER", executionEnabled=True, riskProfile="SAFE"),
        emergency=_domain(locked=False, state="READY"),
        execution=_domain(
            authoritativeRuntimeState=exec_state, synchronizationState="HEALTHY",
            pendingOrderState=pending_order, realOrderAllowed=False,
            freshness=exec_freshness,
        ),
        market=_domain(
            activeSymbol="BTC-USDT", marketReady=market_ready, marketStale=market_stale,
            selectionMode="AUTO",
        ),
        decision=_domain(
            status=decision_status, freshness=decision_freshness
        ),
        health=_domain(
            backendStatus=backend_status, runtimeHealthy=runtime_healthy,
            freshness=health_freshness,
        ),
        moneyManagement=MoneyManagementSnapshot(
            capitalAuthority="MONEY_MANAGEMENT", capitalSource=CapitalSource.PAPER,
            equity=Decimal("1000.1"), availableCapital=Decimal("900.1"),
            riskBudget=Decimal("10.1"), remainingExposure=Decimal("75.1"),
            remainingPositionCapacity=Decimal("1"), ruinGuardStatus=mm_ruin_guard,
            executionEntryAllowed=mm_entry_allowed, policyVersion="v1",
            evaluatedAt=NOW, authorityFresh=mm_authority_fresh, freshness=mm_freshness,
        ),
        warnings=warnings,
    )


def _adapter_snapshot(payloads: dict[str, Any]) -> ReadOnlySupervisorSnapshot:
    readers = RuntimeAuthorityReaders(
        bot=lambda _app, _at: payloads["bot"],
        governance=lambda _app, _at: payloads["governance"],
        moneyManagement=lambda _app, _at: payloads["moneyManagement"],
        health=lambda _app, _at: payloads["health"],
    )
    return RuntimeSnapshotAdapter(readers=readers, clock=lambda: NOW).build(None)


def make_trace(stage_status: list[tuple[str, str, Any]]) -> Any:
    """Build a D-5 unified trace from (stage, status, metadata) tuples."""
    trace_id = new_trace_id()
    events = []
    for item in stage_status:
        stage, status = item[0], item[1]
        meta = item[2] if len(item) > 2 else None
        reason = item[3] if len(item) > 3 else None
        events.append(
            make_event(
                trace_id=trace_id, mode="PAPER", stage=stage, status=status,
                symbol="BTCUSDT", decision_id="d1", reason_code=reason, metadata=meta,
            ).to_dict()
        )
    return UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(trace_id)


# --------------------------------------------------------------------------- #
# Shared Specialist contract
# --------------------------------------------------------------------------- #


def test_shared_contract_deterministic_and_typed():
    snapshot = make_snapshot()
    first = evaluate_money_management(snapshot, NOW)
    second = evaluate_money_management(snapshot, NOW)
    assert first.stable_json() == second.stable_json()
    assert first.authority == "READ_ONLY_ANALYSIS"
    assert first.operationalAuthority == "NONE"
    assert first.mutationAuthority == "NONE"


def test_shared_contract_input_not_mutated():
    from copy import deepcopy

    snapshot = make_snapshot()
    before = deepcopy(snapshot.model_dump(mode="python"))
    trace = make_trace([("STRATEGY", "BUY"), ("RESULT", "EXECUTED")])
    evaluate_system_health(snapshot, NOW)
    evaluate_execution(snapshot, (trace,), NOW)
    evaluate_money_management(snapshot, NOW)
    evaluate_strategy(snapshot, (trace,), NOW)
    assert snapshot.model_dump(mode="python") == before


def test_shared_contract_reason_codes_preserved():
    trace = make_trace([
        ("STRATEGY", "HOLD", None, "STRATEGY_HOLD"),
        ("RESULT", "SUPPRESSED", None, "STRATEGY_HOLD"),
    ])
    snapshot = make_snapshot(decision_status="HOLD")
    finding = evaluate_strategy(snapshot, (trace,), NOW)
    assert finding.reasonCodes == ("STRATEGY_HOLD",)
    assert any(code == "STRATEGY_HOLD" for code in finding.reasonCodes)


def test_shared_contract_provenance_preserved():
    trace = make_trace(
        [("STRATEGY", "BUY"), ("EXECUTION", "PAPER_FILLED", {"orderId": "o1", "fillId": "f1"}), ("RESULT", "EXECUTED")]
    )
    snapshot = make_snapshot()
    finding = evaluate_execution(snapshot, (trace,), NOW)
    assert finding.sourceReferences
    for ref in finding.sourceReferences:
        assert ref.sourceSubsystem
        assert ref.sourceIdentifier is not None
    assert any(ref.sourceSubsystem == "EXECUTION" for ref in finding.sourceReferences)


def test_shared_contract_missing_evidence_not_healthy():
    snapshot = make_snapshot(health_freshness=Freshness.MISSING, runtime_healthy=None)
    finding = evaluate_system_health(snapshot, NOW)
    assert finding.status not in {SpecialistStatus.HEALTHY}


def test_shared_contract_provider_neutral_core():
    snapshot = make_snapshot()
    trace = make_trace([("STRATEGY", "BUY"), ("RESULT", "EXECUTED")])
    results = (
        evaluate_system_health(snapshot, NOW),
        evaluate_execution(snapshot, (trace,), NOW),
        evaluate_money_management(snapshot, NOW),
        evaluate_strategy(snapshot, (trace,), NOW),
    )
    assessment = aggregate_specialists(results, NOW)
    assert assessment.authority == "READ_ONLY_ANALYSIS"
    assert all(item.authority == "READ_ONLY_ANALYSIS" for item in results)


# --------------------------------------------------------------------------- #
# System Health Specialist
# --------------------------------------------------------------------------- #


def test_system_health_healthy_evidence():
    finding = evaluate_system_health(make_snapshot(), NOW)
    assert finding.status is SpecialistStatus.HEALTHY


def test_system_health_stale_evidence():
    finding = evaluate_system_health(make_snapshot(overall_freshness=Freshness.STALE), NOW)
    assert finding.status is SpecialistStatus.WARNING
    assert any(obs.code == "OVERALL_EVIDENCE_STALE" for obs in finding.findings)


def test_system_health_missing_evidence():
    finding = evaluate_system_health(
        make_snapshot(health_freshness=Freshness.MISSING, runtime_healthy=None), NOW
    )
    assert finding.status in {SpecialistStatus.UNAVAILABLE, SpecialistStatus.UNKNOWN}
    assert finding.status is not SpecialistStatus.HEALTHY


def test_system_health_inconsistent_runtime_state():
    finding = evaluate_system_health(
        make_snapshot(auto_trade_enabled=True, loop_enabled=False, loop_state="STOPPED"), NOW
    )
    assert finding.status is SpecialistStatus.CRITICAL
    assert any(obs.code == "AUTO_TRADE_ENABLED_WHILE_LOOP_STOPPED" for obs in finding.findings)


# --------------------------------------------------------------------------- #
# Execution Specialist
# --------------------------------------------------------------------------- #


def test_execution_complete_trace_healthy():
    trace = make_trace([
        ("STRATEGY", "BUY"),
        ("EXECUTION", "PAPER_FILLED", {"orderId": "o1", "fillId": "f1"}),
        ("POSITION", "OPEN", {"positionId": "p1", "orderId": "o1"}),
        ("RESULT", "EXECUTED"),
    ])
    finding = evaluate_execution(make_snapshot(), (trace,), NOW)
    assert finding.status is SpecialistStatus.HEALTHY
    assert any(obs.code == "EXECUTION_TRACE_COMPLETE" for obs in finding.findings)


def test_execution_partial_trace_warning():
    trace = make_trace([("STRATEGY", "BUY"), ("GOVERNANCE", "ALLOW")])
    finding = evaluate_execution(make_snapshot(), (trace,), NOW)
    assert any(obs.code == "EXECUTION_TRACE_PARTIAL" for obs in finding.findings)
    assert finding.status in {SpecialistStatus.WARNING}


def test_execution_ambiguous_trace():
    trace = make_trace(
        [("STRATEGY", "BUY"), ("STRATEGY", "SELL"), ("EXECUTION", "PAPER_FILLED", {"orderId": "o1"})]
    )
    finding = evaluate_execution(make_snapshot(), (trace,), NOW)
    assert any(obs.code == "EXECUTION_TRACE_AMBIGUOUS" for obs in finding.findings)
    assert finding.status is SpecialistStatus.UNKNOWN


def test_execution_rejected_failed_critical():
    trace = make_trace([("STRATEGY", "SELL"), ("EXECUTION", "REJECTED", None, "EXCHANGE_REJECTED")])
    finding = evaluate_execution(make_snapshot(), (trace,), NOW)
    assert any(obs.code == "EXECUTION_REJECTED" for obs in finding.findings)
    assert finding.status is SpecialistStatus.CRITICAL
    assert finding.severity is SpecialistSeverity.CRITICAL


def test_execution_failure_is_not_a_no_trade():
    trace = make_trace([("STRATEGY", "SELL"), ("EXECUTION", "FAILED", None, "EXCHANGE_ERROR")])
    finding = evaluate_execution(make_snapshot(), (trace,), NOW)
    assert any(obs.code == "EXECUTION_FAILED" for obs in finding.findings)
    assert not any(obs.code == "EXECUTION_TRACE_COMPLETE" for obs in finding.findings)


def test_execution_missing_evidence_unavailable():
    snapshot = make_snapshot(exec_freshness=Freshness.MISSING, exec_state=None)
    finding = evaluate_execution(snapshot, (), NOW)
    assert finding.status is SpecialistStatus.UNAVAILABLE
    assert any(obs.code == "EXECUTION_TRACE_UNAVAILABLE" for obs in finding.findings)


# --------------------------------------------------------------------------- #
# Money Management Specialist
# --------------------------------------------------------------------------- #


def test_mm_normal():
    finding = evaluate_money_management(make_snapshot(), NOW)
    assert finding.status is SpecialistStatus.HEALTHY
    assert any(obs.code == "MM_NORMAL" for obs in finding.findings)


def test_mm_locked_critical():
    finding = evaluate_money_management(make_snapshot(mm_ruin_guard="LOCKED"), NOW)
    assert finding.status is SpecialistStatus.CRITICAL
    assert any(obs.code == "MM_LOCKED" for obs in finding.findings)


def test_mm_entry_blocked_warning():
    finding = evaluate_money_management(make_snapshot(mm_entry_allowed=False), NOW)
    assert any(obs.code == "MM_ENTRY_BLOCKED" for obs in finding.findings)
    assert finding.status in {SpecialistStatus.WARNING}


def test_mm_unavailable():
    snapshot = make_snapshot(mm_freshness=Freshness.MISSING, mm_ruin_guard=None)
    finding = evaluate_money_management(snapshot, NOW)
    assert finding.status in {SpecialistStatus.UNAVAILABLE, SpecialistStatus.UNKNOWN}
    assert finding.status is not SpecialistStatus.HEALTHY


def test_mm_existing_authority_preserved_non_mutating():
    snapshot = make_snapshot()
    before = snapshot.moneyManagement
    finding = evaluate_money_management(snapshot, NOW)
    assert finding.mutationAuthority == "NONE"
    assert finding.operationalAuthority == "NONE"
    assert snapshot.moneyManagement is before
    assert snapshot.moneyManagement.executionEntryAllowed is True


# --------------------------------------------------------------------------- #
# Strategy Specialist
# --------------------------------------------------------------------------- #


def test_strategy_decision_present():
    trace = make_trace([("STRATEGY", "BUY"), ("EXECUTION", "PAPER_FILLED", {"orderId": "o1"}), ("RESULT", "EXECUTED")])
    finding = evaluate_strategy(make_snapshot(), (trace,), NOW)
    assert any(obs.code == "STRATEGY_DECISION_PRESENT" for obs in finding.findings)


def test_strategy_legit_no_trade():
    trace = make_trace([("STRATEGY", "HOLD"), ("RESULT", "SUPPRESSED")])
    finding = evaluate_strategy(make_snapshot(), (trace,), NOW)
    assert any(obs.code == "STRATEGY_NO_TRADE" for obs in finding.findings)


def test_strategy_suppression():
    trace = make_trace([("STRATEGY", "HOLD", None, "LIQUIDITY_INSTABILITY"), ("RESULT", "SUPPRESSED")])
    finding = evaluate_strategy(make_snapshot(), (trace,), NOW)
    assert any(obs.code == "STRATEGY_SUPPRESSED" for obs in finding.findings)


def test_strategy_missing_decision_evidence():
    snapshot = make_snapshot(decision_status=None, decision_freshness=Freshness.MISSING)
    finding = evaluate_strategy(snapshot, (), NOW)
    assert any(obs.code == "DECISION_EVIDENCE_MISSING" for obs in finding.findings)
    assert finding.status in {SpecialistStatus.UNAVAILABLE, SpecialistStatus.UNKNOWN}
    assert finding.status is not SpecialistStatus.HEALTHY


def test_strategy_rejection_after_strategy_distinction():
    trace = make_trace(
        [("STRATEGY", "BUY"), ("MONEY_MANAGEMENT", "BLOCKED", None, "MAXIMUM_DRAWDOWN"),
         ("RESULT", "BLOCKED")]
    )
    finding = evaluate_strategy(make_snapshot(), (trace,), NOW)
    assert any(obs.code == "ENTRY_REJECTED_AFTER_STRATEGY" for obs in finding.findings)
    assert not any(obs.code == "STRATEGY_NO_TRADE" for obs in finding.findings)


# --------------------------------------------------------------------------- #
# Master Supervisor integration
# --------------------------------------------------------------------------- #


def _all_specialists(snapshot, traces):
    return (
        evaluate_system_health(snapshot, NOW),
        evaluate_execution(snapshot, traces, NOW),
        evaluate_money_management(snapshot, NOW),
        evaluate_strategy(snapshot, traces, NOW),
    )


def test_master_aggregates_all_specialists():
    trace = make_trace([("STRATEGY", "BUY"), ("RESULT", "EXECUTED")])
    snapshot = make_snapshot()
    assessment = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    assert {item.specialistId for item in assessment.specialists} == {
        "SYSTEM_HEALTH", "EXECUTION", "MONEY_MANAGEMENT", "STRATEGY",
    }
    assert assessment.schemaVersion == 1


def test_master_deterministic_aggregation():
    trace = make_trace([("STRATEGY", "BUY"), ("RESULT", "EXECUTED")])
    snapshot = make_snapshot()
    first = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    second = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    assert first.stable_json() == second.stable_json()


def test_master_critical_propagates():
    trace = make_trace([("STRATEGY", "SELL"), ("EXECUTION", "FAILED", None, "EXCHANGE_ERROR")])
    snapshot = make_snapshot()
    assessment = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    assert assessment.highestSeverity is SpecialistSeverity.CRITICAL
    assert assessment.overallStatus is SpecialistStatus.CRITICAL


def test_master_unknown_does_not_become_healthy():
    # Money Management authority missing -> UNKNOWN/UNVAILABLE, never healthy.
    snapshot = make_snapshot(mm_freshness=Freshness.MISSING, mm_ruin_guard=None)
    trace = make_trace([("STRATEGY", "BUY"), ("RESULT", "EXECUTED")])
    assessment = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    assert assessment.overallStatus in {SpecialistStatus.UNKNOWN, SpecialistStatus.UNAVAILABLE}
    assert assessment.overallStatus is not SpecialistStatus.HEALTHY


def test_master_cross_domain_contradiction():
    # MM blocks entry yet execution shows an order/fill -> contradiction.
    snapshot = make_snapshot(mm_entry_allowed=False)
    trace = make_trace([
        ("STRATEGY", "BUY"),
        ("MONEY_MANAGEMENT", "BLOCKED", None, "MAXIMUM_DRAWDOWN"),
        ("EXECUTION", "PAPER_FILLED", {"orderId": "o1", "fillId": "f1"}),
        ("RESULT", "EXECUTED"),
    ])
    assessment = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    assert any(item.code == "MM_BLOCKED_BUT_EXECUTION_PRESENT" for item in assessment.crossDomainFindings)


def test_master_cross_domain_ambiguity_preserved_without_guessing():
    # Strategy intent present but no execution evidence at all -> explicit finding.
    trace = make_trace([("STRATEGY", "BUY")])
    snapshot = make_snapshot()
    assessment = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    assert any(item.code == "STRATEGY_INTENT_WITHOUT_EXECUTION" for item in assessment.crossDomainFindings)


def test_master_unavailable_preserved_in_aggregate():
    snapshot = make_snapshot(health_freshness=Freshness.MISSING, runtime_healthy=None)
    trace = make_trace([("STRATEGY", "BUY"), ("RESULT", "EXECUTED")])
    assessment = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    assert assessment.overallStatus in {SpecialistStatus.UNKNOWN, SpecialistStatus.UNAVAILABLE}


def test_master_bounded_llm_context_truncation_explicit():
    snapshot = make_snapshot()
    trace = make_trace([("STRATEGY", "BUY"), ("RESULT", "EXECUTED")])
    assessment = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    context = build_bounded_llm_context(assessment)
    assert context.schemaVersion == 1
    assert context.truncated is False
    assert all(not item.findingTruncated for item in context.specialists)
    # No raw evidence / secret-bearing fields leak.
    for serializer in (context.stable_json(), assessment.stable_json()):
        assert "apiKey" not in serializer
        assert "credential" not in serializer
        assert "SECRET" not in serializer


def test_master_no_operational_or_execution_authority():
    trace = make_trace([("STRATEGY", "BUY"), ("RESULT", "EXECUTED")])
    snapshot = make_snapshot()
    assessment = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    assert assessment.authority == "READ_ONLY_ANALYSIS"
    assert assessment.operationalAuthority == "NONE"
    assert assessment.mutationAuthority == "NONE"


def test_master_reason_codes_preserved_across_specialists():
    trace = make_trace(
        [("STRATEGY", "HOLD", None, "STRATEGY_HOLD"), ("RESULT", "SUPPRESSED", None, "STRATEGY_HOLD")]
    )
    snapshot = make_snapshot(decision_status="HOLD")
    assessment = aggregate_specialists(_all_specialists(snapshot, (trace,)), NOW)
    assert "STRATEGY_HOLD" in assessment.reasonCodes


# --------------------------------------------------------------------------- #
# Severity / Status precedence contract (D-6 deterministic ladder)
# --------------------------------------------------------------------------- #
# These tests lock the public helper contract implemented by D-6
# (``backend.supervisor.specialists.severity``).  They do NOT re-implement the
# ordering; they assert the observable fail-closed precedence:
#   Severity: CRITICAL > UNKNOWN > WARNING > INFO
#   Status:   CRITICAL > UNAVAILABLE > UNKNOWN > WARNING > HEALTHY


def test_severity_precedence_critical_over_unknown():
    assert (
        worst_severity((SpecialistSeverity.CRITICAL, SpecialistSeverity.UNKNOWN))
        is SpecialistSeverity.CRITICAL
    )


def test_severity_precedence_unknown_over_warning():
    assert (
        worst_severity((SpecialistSeverity.UNKNOWN, SpecialistSeverity.WARNING))
        is SpecialistSeverity.UNKNOWN
    )


def test_severity_precedence_warning_over_info():
    assert (
        worst_severity((SpecialistSeverity.WARNING, SpecialistSeverity.INFO))
        is SpecialistSeverity.WARNING
    )


def test_severity_precedence_info_with_info_is_info():
    assert (
        worst_severity((SpecialistSeverity.INFO, SpecialistSeverity.INFO))
        is SpecialistSeverity.INFO
    )


def test_status_precedence_critical_over_unavailable():
    assert (
        worst_status((SpecialistStatus.CRITICAL, SpecialistStatus.UNAVAILABLE))
        is SpecialistStatus.CRITICAL
    )


def test_status_precedence_unavailable_over_unknown():
    assert (
        worst_status((SpecialistStatus.UNAVAILABLE, SpecialistStatus.UNKNOWN))
        is SpecialistStatus.UNAVAILABLE
    )


def test_status_precedence_unknown_over_warning():
    assert (
        worst_status((SpecialistStatus.UNKNOWN, SpecialistStatus.WARNING))
        is SpecialistStatus.UNKNOWN
    )


def test_status_precedence_warning_over_healthy():
    assert (
        worst_status((SpecialistStatus.WARNING, SpecialistStatus.HEALTHY))
        is SpecialistStatus.WARNING
    )


def test_status_precedence_healthy_with_healthy_is_healthy():
    assert (
        worst_status((SpecialistStatus.HEALTHY, SpecialistStatus.HEALTHY))
        is SpecialistStatus.HEALTHY
    )

