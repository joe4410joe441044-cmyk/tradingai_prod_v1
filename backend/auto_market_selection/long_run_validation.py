"""Deterministic multi-cycle validation harness for Paper AMS.

This is test/validation orchestration, not a production scheduling policy.
"""

from dataclasses import dataclass
from time import perf_counter
from typing import Mapping, Tuple


CRITICAL_INVARIANTS = (
    "symbolAuthorityConsistent",
    "decisionContextsConsistent",
    "singlePositionSafe",
    "pendingOrderSafe",
    "noOldDecisionExecution",
    "noRealExchangeCall",
    "paperSafetyUnchanged",
    "governancePreserved",
)


@dataclass(frozen=True)
class LongRunCycleRecord:
    index: int
    scenario: str
    accepted: bool
    status: str
    duration_seconds: float
    auto_selection_cycle_id: object
    scanner_cycle_id: object
    ranking_cycle_id: object
    selection_proposal_id: object
    switch_transaction_id: object
    initial_active_symbol: object
    top_candidate: object
    final_active_symbol: object
    runtime_id_before: object
    runtime_id_after: object
    reason_codes: Tuple[str, ...]
    invariant_violations: Tuple[str, ...]

    def to_dict(self):
        return {
            "index": self.index, "scenario": self.scenario,
            "accepted": self.accepted, "status": self.status,
            "durationSeconds": self.duration_seconds,
            "autoSelectionCycleId": self.auto_selection_cycle_id,
            "scannerCycleId": self.scanner_cycle_id,
            "rankingCycleId": self.ranking_cycle_id,
            "selectionProposalId": self.selection_proposal_id,
            "switchTransactionId": self.switch_transaction_id,
            "initialActiveSymbol": self.initial_active_symbol,
            "topCandidate": self.top_candidate,
            "finalActiveSymbol": self.final_active_symbol,
            "runtimeIdBefore": self.runtime_id_before,
            "runtimeIdAfter": self.runtime_id_after,
            "reasonCodes": list(self.reason_codes),
            "invariantViolations": list(self.invariant_violations),
        }


@dataclass(frozen=True)
class LongRunValidationResult:
    requested_cycles: int
    records: Tuple[LongRunCycleRecord, ...]
    completed: int
    blocked: int
    failed: int
    switches: int
    no_switch: int
    critical_violations: Tuple[str, ...]
    oscillation_observed: bool
    total_duration_seconds: float

    @property
    def passed(self):
        return (len(self.records) == self.requested_cycles
                and not self.critical_violations)

    def to_dict(self):
        return {
            "requestedCycles": self.requested_cycles,
            "total": len(self.records), "completed": self.completed,
            "blocked": self.blocked, "failed": self.failed,
            "switches": self.switches, "noSwitch": self.no_switch,
            "criticalViolations": list(self.critical_violations),
            "oscillationObserved": self.oscillation_observed,
            "totalDurationSeconds": self.total_duration_seconds,
            "passed": self.passed,
            "records": [record.to_dict() for record in self.records],
        }


class LongRunPaperValidationHarness:
    """Explicitly trigger N lifecycle cycles and observe invariants."""

    def __init__(self, lifecycle, *, scenario_driver, invariant_observer,
                 timer=None):
        if not callable(getattr(lifecycle, "start", None)) or not callable(
                getattr(lifecycle, "run_one_cycle", None)):
            raise TypeError("AMS-4C lifecycle required")
        if not callable(scenario_driver) or not callable(invariant_observer):
            raise TypeError("validation scenario and invariant boundaries required")
        self.lifecycle = lifecycle
        self.scenario_driver = scenario_driver
        self.invariant_observer = invariant_observer
        self.timer = timer or perf_counter

    def run(self, *, cycles=100):
        if type(cycles) is not int or cycles < 100:
            raise ValueError("minimum 100 validation cycles required")
        started = self.timer()
        records = []
        critical = []
        transitions = []
        for index in range(cycles):
            scenario = self.scenario_driver(index)
            if not isinstance(scenario, Mapping) or not scenario.get("name"):
                raise TypeError("validation scenario contract required")
            status = self.lifecycle.get_status()
            if status.get("amsRuntimeState") != "READY":
                self.lifecycle.start()
            before = self.invariant_observer(index, scenario, "before")
            cycle_started = self.timer()
            response = self.lifecycle.run_one_cycle(started_at=scenario.get("startedAt"))
            duration = self.timer() - cycle_started
            after = self.invariant_observer(index, scenario, "after")
            record = self._record(index, scenario, response, before, after, duration)
            records.append(record)
            transitions.append((record.initial_active_symbol, record.final_active_symbol))
            for violation in record.invariant_violations:
                critical.append(f"cycle:{index}:{violation}")
        completed = sum(record.status.startswith("COMPLETED") for record in records)
        blocked = sum(record.status == "COMPLETED_BLOCKED" for record in records)
        failed = sum(record.status == "FAILED" or not record.accepted for record in records)
        switches = sum(
            record.initial_active_symbol != record.final_active_symbol
            for record in records if record.initial_active_symbol and record.final_active_symbol
        )
        oscillation = self._oscillation(transitions)
        return LongRunValidationResult(
            cycles, tuple(records), completed, blocked, failed, switches,
            len(records) - switches, tuple(critical), oscillation,
            self.timer() - started,
        )

    @staticmethod
    def _record(index, scenario, response, before, after, duration):
        response = response if isinstance(response, Mapping) else {}
        result = response.get("result")
        result = result if isinstance(result, Mapping) else {}
        observation = after if isinstance(after, Mapping) else {}
        cycle = observation.get("cycle")
        cycle = cycle if isinstance(cycle, Mapping) else {}
        violations = tuple(
            name for name in CRITICAL_INVARIANTS
            if observation.get(name) is not True
        )
        return LongRunCycleRecord(
            index, str(scenario["name"]), response.get("accepted") is True,
            str(result.get("status") or "REJECTED"), duration,
            result.get("autoSelectionCycleId"), cycle.get("scannerCycleId"),
            cycle.get("rankingCycleId"), cycle.get("selectionProposalId"),
            cycle.get("switchTransactionId"),
            result.get("initialActiveSymbol", before.get("activeSymbol") if isinstance(before, Mapping) else None),
            result.get("topCandidateSymbol", cycle.get("topCandidateSymbol")),
            result.get("finalActiveSymbol", observation.get("activeSymbol")),
            before.get("runtimeId") if isinstance(before, Mapping) else None,
            observation.get("runtimeId"), tuple(response.get("reasonCodes") or ()),
            violations,
        )

    @staticmethod
    def _oscillation(transitions):
        changed = [(old, new) for old, new in transitions if old and new and old != new]
        return any(
            changed[index - 1] == (new, old)
            for index, (old, new) in enumerate(changed) if index
        )
