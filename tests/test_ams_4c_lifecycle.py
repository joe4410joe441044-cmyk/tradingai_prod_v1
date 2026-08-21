from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import threading

import pytest

from backend.auto_market_selection import (
    AutoSelectionLifecycleState, PaperAutoSelectionLifecycle,
)
from backend.bot_manager.bot_manager import BotManager


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)
READY = {"dependenciesAvailable": True, "mmAvailable": True, "emergencySafe": True}


class ResultStatus(str, Enum):
    COMPLETED = "COMPLETED_SWITCHED"
    FAILED = "FAILED"


@dataclass
class Result:
    status: ResultStatus = ResultStatus.COMPLETED
    reason_codes: tuple = ()

    def to_dict(self):
        return {
            "e2eCycleId": "ams-4b-result", "status": self.status.value,
            "completedAt": "2026-08-09T03:00:00Z",
            "reasonCodes": list(self.reason_codes),
        }


class Manager:
    def __init__(self, config=None):
        self.config = config or {
            "mode": "paper", "dry_run": True, "realOrderAllowed": False,
        }
        self.activeSymbol = "ETHUSDT"
        self.auto_market_selection_observation = {
            "autoSelectionCycle": {"topCandidateSymbol": "BTCUSDT"},
            "switchResult": {"state": "COMPLETED"},
        }
        self.position = {"side": "BUY"}
        self.pending = {"id": "pending-1"}


class E2E:
    def __init__(self, result=None):
        self.result = result or Result()
        self.calls = []
        self.clock = lambda: NOW

    def run(self, *, started_at=None):
        self.calls.append(started_at)
        return self.result


def lifecycle(*, config=None, readiness=None, result=None):
    manager = Manager(config=config)
    e2e = E2E(result=result)
    service = PaperAutoSelectionLifecycle(
        manager, e2e, readiness_provider=lambda: readiness or READY,
    )
    return service, manager, e2e


def test_restart_defaults_stopped_and_start_only_makes_runtime_ready():
    service, manager, e2e = lifecycle()
    assert service.get_status()["amsRuntimeState"] == "STOPPED"
    active = manager.activeSymbol
    status = service.start()
    assert status["amsMode"] == "AUTO_PAPER"
    assert status["amsRuntimeState"] == "READY"
    assert manager.activeSymbol == active and e2e.calls == []


@pytest.mark.parametrize("config,reason", [
    ({"mode": "live", "dry_run": True, "realOrderAllowed": False},
     "AUTO_RUNTIME_LIVE_BLOCKED"),
    ({"mode": "paper", "dry_run": False, "realOrderAllowed": False},
     "AUTO_RUNTIME_DRY_RUN_REQUIRED"),
    ({"mode": "paper", "dry_run": True, "realOrderAllowed": True},
     "AUTO_RUNTIME_REAL_ORDER_FORBIDDEN"),
])
def test_unsafe_configuration_blocks_start(config, reason):
    service, manager, e2e = lifecycle(config=config)
    status = service.start()
    assert status["amsRuntimeState"] == "BLOCKED"
    assert status["reasonCodes"] == [reason]
    assert manager.activeSymbol == "ETHUSDT" and e2e.calls == []





def test_missing_dry_run_uses_bot_manager_safe_default():
    service, _, _ = lifecycle(config={
        "unrelated": True, "realOrderAllowed": False,
    })
    assert service.start()["amsRuntimeState"] == "READY"


def test_missing_mode_uses_bot_manager_paper_default():
    service, _, _ = lifecycle(config={
        "dry_run": True, "realOrderAllowed": False,
    })
    assert service.start()["amsRuntimeState"] == "READY"


def test_authoritative_mode_wins_over_stale_trade_mode_alias():
    service, _, _ = lifecycle(config={
        "mode": "paper", "tradeMode": "live", "dry_run": True,
        "realOrderAllowed": False,
    })
    assert service.start()["amsRuntimeState"] == "READY"


def test_mm_emergency_and_dependency_readiness_block_start():
    for key, reason in (
        ("dependenciesAvailable", "AUTO_RUNTIME_DEPENDENCIES_UNAVAILABLE"),
        ("mmAvailable", "AUTO_RUNTIME_MM_UNAVAILABLE"),
        ("emergencySafe", "AUTO_RUNTIME_EMERGENCY_UNSAFE"),
    ):
        readiness = {**READY, key: False}
        service, _, _ = lifecycle(readiness=readiness)
        assert service.start()["reasonCodes"] == [reason]


def test_single_cycle_uses_existing_e2e_and_publishes_last_status():
    service, _, e2e = lifecycle()
    service.start()
    response = service.run_one_cycle(started_at=NOW)
    assert response["accepted"] is True
    assert e2e.calls == [NOW]
    status = response["runtime"]
    assert status["amsRuntimeState"] == "READY"
    assert status["lastCycleId"] == "ams-4b-result"
    assert status["lastCycleStatus"] == "COMPLETED_SWITCHED"
    assert status["topCandidate"] == "BTCUSDT"
    assert status["switchState"] == "COMPLETED"


def test_failure_is_visible_and_no_automatic_retry_occurs():
    failed = Result(ResultStatus.FAILED, ("GOVERNANCE_CONTEXT_MISMATCH",))
    service, manager, e2e = lifecycle(result=failed)
    service.start()
    response = service.run_one_cycle(started_at=NOW)
    assert response["runtime"]["amsRuntimeState"] == "FAILED"
    assert response["runtime"]["reasonCodes"] == ["GOVERNANCE_CONTEXT_MISMATCH"]
    assert len(e2e.calls) == 1 and manager.activeSymbol == "ETHUSDT"
    assert service.run_one_cycle()["accepted"] is False


def test_stop_idle_changes_only_auto_reselection_state():
    service, manager, _ = lifecycle()
    service.start()
    active, position, pending = manager.activeSymbol, manager.position, manager.pending
    status = service.stop()
    assert status["amsRuntimeState"] == "STOPPED" and status["amsMode"] == "MANUAL"
    assert (manager.activeSymbol, manager.position, manager.pending) == (active, position, pending)


def test_stop_during_cycle_does_not_interrupt_current_transaction():
    entered, release = threading.Event(), threading.Event()

    class BlockingE2E(E2E):
        def run(self, *, started_at=None):
            entered.set()
            release.wait(2)
            self.calls.append(started_at)
            return self.result

    manager = Manager(); e2e = BlockingE2E()
    service = PaperAutoSelectionLifecycle(manager, e2e, readiness_provider=lambda: READY)
    service.start()
    responses = []
    thread = threading.Thread(target=lambda: responses.append(service.run_one_cycle(started_at=NOW)))
    thread.start(); assert entered.wait(1)
    assert service.get_status()["amsRuntimeState"] == "RUNNING_CYCLE"
    concurrent = service.run_one_cycle(started_at=NOW)
    assert concurrent["reasonCodes"] == ["AUTO_SELECTION_ALREADY_IN_PROGRESS"]
    stopped = service.stop()
    assert stopped["amsRuntimeState"] == "RUNNING_CYCLE"
    release.set(); thread.join(2)
    assert responses[0]["runtime"]["amsRuntimeState"] == "STOPPED"
    assert len(e2e.calls) == 1


def test_bot_manager_production_management_boundary_defaults_safe():
    manager = BotManager.__new__(BotManager)
    manager._active_symbol = "ETHUSDT"
    manager.auto_market_selection_lifecycle = None
    default = manager.get_auto_market_selection_runtime_status()
    assert default["amsMode"] == "MANUAL" and default["amsRuntimeState"] == "STOPPED"

    service, _, _ = lifecycle()
    manager.attach_auto_market_selection_lifecycle(service)
    assert manager.start_auto_market_selection_runtime()["amsRuntimeState"] == "READY"
    assert manager.run_auto_market_selection_cycle(started_at=NOW)["accepted"] is True
    assert manager.stop_auto_market_selection_runtime()["amsRuntimeState"] == "STOPPED"


def test_lifecycle_source_has_no_scheduler_symbol_trade_or_bypass_mutation():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] /
              "backend/auto_market_selection/lifecycle.py").read_text()
    assert all(term not in source for term in (
        "sleep(", "interval", "cooldown", ".activeSymbol =", "._active_symbol =",
        "create_order", "submit_order", "governance_bypass", "execution_bypass",
    ))


def test_status_projects_initial_proposal_commit_lock_and_counts():
    service, manager, _ = lifecycle()
    manager.activeSymbol = "BTCUSDT"
    manager.auto_market_selection_observation = {
        "autoSelectionCycle": {
            "autoSelectionCycleId": "ams-cycle-1",
            "topCandidateSymbol": "BTCUSDT",
            "evaluatedAt": "2026-08-09T03:00:00Z",
        },
        "scannerResult": {
            "universeCount": 10, "evaluatedCount": 9,
            "eligibleCount": 3, "rejectedCount": 6,
        },
        "rankingResult": {
            "topCandidate": {"symbol": "BTCUSDT", "rankingScore": "0.91"},
        },
        "selectionProposal": {
            "currentActiveSymbol": None, "proposedSymbol": "BTCUSDT",
        },
        "switchResult": {
            "previousSymbol": None, "proposedSymbol": "BTCUSDT",
            "committedSymbol": "BTCUSDT", "state": "COMPLETED",
            "success": True, "committedAt": "2026-08-09T03:00:01Z",
            "completedAt": "2026-08-09T03:00:02Z",
        },
    }
    service.start()
    status = service.get_status()
    assert status["selectionMode"] == "INITIAL_SELECTION"
    assert status["selectionCycleId"] == "ams-cycle-1"
    assert (status["universeCount"], status["evaluatedCount"],
            status["eligibleCount"], status["rejectedCount"]) == (10, 9, 3, 6)
    assert status["proposedSymbol"] == status["requestedSymbol"] == "BTCUSDT"
    assert status["previousSymbol"] is None
    assert status["committedSymbol"] == status["lockedSymbol"] == "BTCUSDT"
    assert status["lockOnState"] == "LOCKED"
    assert status["lockedAt"] == "2026-08-09T03:00:01Z"
