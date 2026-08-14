from datetime import datetime, timedelta, timezone

import pytest

from backend.auto_market_selection import LongRunPaperValidationHarness


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)
SCENARIOS = (
    "STABLE_SAME_SYMBOL", "SAFE_SYMBOL_CHANGE", "REPEATED_SAFE_CHANGE",
    "OPEN_POSITION", "PENDING_ORDER", "MM_LOCK", "EMERGENCY_UNSAFE",
    "STALE_UNIVERSE", "STALE_TICKER", "STALE_MM", "OLD_CALLBACK",
    "OLD_STRATEGY", "OLD_AI", "FEED_FAILURE", "SNAPSHOT_INVALID",
    "SNAPSHOT_STALE", "CLEANUP_FAILURE", "DOWNSTREAM_SYNC_FAILURE",
)
BLOCKED = {
    "OPEN_POSITION", "PENDING_ORDER", "MM_LOCK", "EMERGENCY_UNSAFE",
    "STALE_UNIVERSE", "STALE_TICKER", "STALE_MM", "OLD_STRATEGY", "OLD_AI",
}
FAILED = {
    "FEED_FAILURE", "SNAPSHOT_INVALID", "SNAPSHOT_STALE",
    "CLEANUP_FAILURE", "DOWNSTREAM_SYNC_FAILURE",
}


class DeterministicLifecycle:
    """Fixture lifecycle modeling externally controlled scenario changes."""

    def __init__(self):
        self.state = "STOPPED"
        self.scenario = None
        self.active = "A"
        self.runtime_id = "runtime-A-0"
        self.generation = 0
        self.observation = {}
        self.config = {"mode": "paper", "dry_run": True,
                       "realOrderAllowed": False}
        self.real_exchange_calls = 0
        self.old_callback_rejections = 0
        self.old_decision_rejections = 0

    def start(self):
        self.state = "READY"
        return self.get_status()

    def get_status(self):
        return {"amsRuntimeState": self.state}

    def run_one_cycle(self, *, started_at=None):
        scenario = self.scenario
        initial = self.active
        top = initial
        status = "COMPLETED_NO_SWITCH"
        reasons = []
        switch_id = None
        if scenario in {"SAFE_SYMBOL_CHANGE", "REPEATED_SAFE_CHANGE"}:
            top = "B" if initial == "A" else "A"
            self.generation += 1
            self.active = top
            self.runtime_id = f"runtime-{top}-{self.generation}"
            switch_id = f"ams-2b-{self.generation}"
            status = "COMPLETED_SWITCHED"
        elif scenario in BLOCKED:
            top = "B" if initial == "A" else "A"
            status = "COMPLETED_BLOCKED"
            reasons = [scenario]
            if scenario == "OLD_STRATEGY" or scenario == "OLD_AI":
                self.old_decision_rejections += 1
        elif scenario in FAILED:
            top = "B" if initial == "A" else "A"
            status = "FAILED"
            reasons = [scenario]
            self.state = "FAILED"
        elif scenario == "OLD_CALLBACK":
            self.old_callback_rejections += 1
        index = self.generation + len(reasons)
        cycle_id = f"ams-4a-{started_at.isoformat()}"
        self.observation = {
            "scannerCycleId": f"ams-1a-{started_at.isoformat()}",
            "rankingCycleId": f"ams-1c-{started_at.isoformat()}",
            "selectionProposalId": f"ams-2a-{started_at.isoformat()}",
            "switchTransactionId": switch_id,
            "topCandidateSymbol": top,
        }
        if self.state != "FAILED":
            self.state = "READY"
        return {
            "accepted": True, "reasonCodes": reasons,
            "result": {
                "e2eCycleId": f"ams-4b-{started_at.isoformat()}",
                "autoSelectionCycleId": cycle_id,
                "initialActiveSymbol": initial,
                "topCandidateSymbol": top,
                "finalActiveSymbol": self.active,
                "status": status,
            },
        }


def driver_for(lifecycle):
    def driver(index):
        name = SCENARIOS[index % len(SCENARIOS)]
        lifecycle.scenario = name
        return {"name": name, "startedAt": NOW + timedelta(seconds=index)}
    return driver


def observer_for(lifecycle, *, violate_at=None):
    def observer(index, scenario, phase):
        invariants = {
            "symbolAuthorityConsistent": index != violate_at,
            "decisionContextsConsistent": True,
            "singlePositionSafe": True,
            "pendingOrderSafe": True,
            "noOldDecisionExecution": True,
            "noRealExchangeCall": lifecycle.real_exchange_calls == 0,
            "paperSafetyUnchanged": lifecycle.config == {
                "mode": "paper", "dry_run": True, "realOrderAllowed": False,
            },
            "governancePreserved": True,
        }
        return {
            "activeSymbol": lifecycle.active,
            "runtimeId": lifecycle.runtime_id,
            "cycle": lifecycle.observation,
            **invariants,
        }
    return observer


def test_100_cycle_mixed_validation_preserves_all_critical_invariants():
    lifecycle = DeterministicLifecycle()
    harness = LongRunPaperValidationHarness(
        lifecycle, scenario_driver=driver_for(lifecycle),
        invariant_observer=observer_for(lifecycle),
    )
    result = harness.run(cycles=100)
    assert result.passed and len(result.records) == 100
    assert result.completed + result.failed == 100
    assert result.blocked > 0 and result.failed > 0
    assert result.switches > 1 and result.no_switch > 1
    assert result.oscillation_observed is True
    assert result.critical_violations == ()
    assert lifecycle.real_exchange_calls == 0
    assert lifecycle.old_callback_rejections > 0
    assert lifecycle.old_decision_rejections > 0
    assert lifecycle.config == {"mode": "paper", "dry_run": True,
                                "realOrderAllowed": False}
    assert all(record.duration_seconds >= 0 for record in result.records)
    assert all(record.auto_selection_cycle_id for record in result.records)
    assert all(record.scanner_cycle_id and record.ranking_cycle_id
               and record.selection_proposal_id for record in result.records)


def test_validation_can_extend_to_500_cycles_without_state_or_lock_drift():
    lifecycle = DeterministicLifecycle()
    result = LongRunPaperValidationHarness(
        lifecycle, scenario_driver=driver_for(lifecycle),
        invariant_observer=observer_for(lifecycle),
    ).run(cycles=500)
    assert result.passed and len(result.records) == 500
    assert lifecycle.state in {"READY", "FAILED"}
    assert lifecycle.real_exchange_calls == 0


def test_minimum_run_size_is_enforced_and_authority_split_fails_validation():
    lifecycle = DeterministicLifecycle()
    harness = LongRunPaperValidationHarness(
        lifecycle, scenario_driver=driver_for(lifecycle),
        invariant_observer=observer_for(lifecycle, violate_at=42),
    )
    with pytest.raises(ValueError):
        harness.run(cycles=99)
    result = harness.run(cycles=100)
    assert not result.passed
    assert result.critical_violations == (
        "cycle:42:symbolAuthorityConsistent",
    )


def test_harness_contains_no_production_interval_retry_or_recovery_policy():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] /
              "backend/auto_market_selection/long_run_validation.py").read_text()
    assert all(term not in source for term in (
        "sleep(", "cooldown", "minimum_hold", "retry_forever",
        "fallback BTC", "rollback", "realOrderAllowed =",
    ))
