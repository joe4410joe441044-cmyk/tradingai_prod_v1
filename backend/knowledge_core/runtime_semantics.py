"""Typed registry for important runtime terms.

Critical: this registry *describes* current runtime truth as implemented.  It
does not calculate or control runtime state.  Each record distinguishes field
meaning, producer, authority class, allowed values, unknown behavior and a
safety interpretation where the source/spec supports it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ._base import freeze_mapping, stable_json
from .authority import SourceCategory, TruthLevel
from .provenance import ProvenanceRecord

_RUNTIME = TruthLevel.CURRENT_SOURCE_RUNTIME
_SPEC = TruthLevel.CANONICAL_SPECIFICATION


def _src(path: str, symbol: str, notes: str = "") -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=_RUNTIME,
        source_category=SourceCategory.SOURCE_CODE,
        source_reference=path,
        source_path=path,
        symbol=symbol,
        notes=notes,
    )


@dataclass(frozen=True)
class RuntimeSemantic:
    """Description of one runtime term.

    ``field_id`` is the globally unique identifier (two concepts share the
    ``field_name`` ``executionEntryAllowed`` and are disambiguated here).
    ``authority_class`` is ``AUTHORITY_FLAG`` (operator-writable) or
    ``DERIVED_DESCRIPTOR`` (read-only, recomputed).  It records the runtime
    producer's authority; the Knowledge Core itself has none.
    """

    field_id: str
    field_name: str
    meaning: str
    producer: str
    authority_class: str
    allowed_values: tuple[str, ...]
    unknown_behavior: str
    safety_interpretation: str
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)


RUNTIME_SEMANTICS = (
    RuntimeSemantic(
        field_id="botState", field_name="botState",
        meaning="Lifecycle state of the bot manager envelope (not the execution loop).",
        producer="backend/bot_manager/bot_manager.py:10468 (BotManager.get_result())",
        authority_class="DERIVED_DESCRIPTOR",
        allowed_values=("STOPPED", "STARTING", "RUNNING", "STOPPING"),
        unknown_behavior="NOT_CONNECTED / UNKNOWN when no manager is connected.",
        safety_interpretation="Observational. No execution gating.",
        provenance=_src("backend/bot_manager/bot_manager.py", "lifecycle_state"),
    ),
    RuntimeSemantic(
        field_id="selectedMode", field_name="selectedMode",
        meaning="Mode selected at start request, normalized to uppercased PAPER/LIVE.",
        producer="backend/bot_manager/bot_manager.py:10109-10111 (config['mode'])",
        authority_class="AUTHORITY_FLAG",
        allowed_values=("PAPER", "LIVE"),
        unknown_behavior="None when mode is not a recognized PAPER/LIVE value.",
        safety_interpretation="Mode is fixed for the session; symbol/mode switch mid-run rejected.",
        provenance=_src("backend/bot_manager/bot_manager.py", "selected_mode"),
    ),
    RuntimeSemantic(
        field_id="dryRun", field_name="dryRun",
        meaning="Whether the executing engine simulates (paper) instead of sending real orders.",
        producer="backend/bot_manager/bot_manager.py:10105-10107 (config['dry_run'])",
        authority_class="AUTHORITY_FLAG",
        allowed_values=("True", "False"),
        unknown_behavior="Default True; invalid value treated strictly.",
        safety_interpretation="When True real orders must not be permitted.",
        provenance=_src("backend/bot_manager/bot_manager.py", "dry_run"),
    ),
    RuntimeSemantic(
        field_id="loopEnabled", field_name="loopEnabled",
        meaning="Whether the periodic decision loop is actually RUNNING.",
        producer="backend/bot_manager/bot_manager.py:10036 (loop_state == 'RUNNING')",
        authority_class="DERIVED_DESCRIPTOR",
        allowed_values=("True", "False"),
        unknown_behavior="False when loop_state is not RUNNING.",
        safety_interpretation="Read-only; loop is controlled by explicit start/stop endpoints.",
        provenance=_src("backend/bot_manager/bot_manager.py", "loop_enabled"),
    ),
    RuntimeSemantic(
        field_id="executionEnabled", field_name="executionEnabled",
        meaning="Operator-controlled auto-trade master switch.",
        producer="backend/runtime/governance_runtime.py:12 (governance_state['execution_enabled'])",
        authority_class="AUTHORITY_FLAG",
        allowed_values=("True", "False"),
        unknown_behavior="False when absent; EXECUTION_DISABLED when False.",
        safety_interpretation="Fail-closed: blocks EXECUTION_DISABLED when False.",
        provenance=_src("backend/runtime/governance_runtime.py", "execution_enabled"),
    ),
    RuntimeSemantic(
        field_id="realOrderAllowed", field_name="realOrderAllowed",
        meaning="Are real (live) orders currently permitted; fail-closed AND-projection of all gates.",
        producer="backend/bot_manager/bot_manager.py:10118-1430 / runtime_reader.py:74-94",
        authority_class="DERIVED_DESCRIPTOR",
        allowed_values=("True", "False"),
        unknown_behavior="False on any missing/uncertain gate.",
        safety_interpretation="NEVER directly set true; Supervisor forces False on conflict.",
        provenance=_src("backend/bot_manager/bot_manager.py", "real_order_allowed"),
    ),
    RuntimeSemantic(
        field_id="liveOrderEntryAllowed", field_name="liveOrderEntryAllowed",
        meaning="Config arming flag for literal LIVE order entry (one of the 3 order authorities).",
        producer="backend/bot_manager/bot_manager.py:545,3175 (config['liveOrderEntryAllowed'])",
        authority_class="AUTHORITY_FLAG",
        allowed_values=("True", "False"),
        unknown_behavior="False when not True (get is True).",
        safety_interpretation="Backend always disarms (False); no code path sets True.",
        provenance=_src("backend/bot_manager/bot_manager.py", "liveOrderEntryAllowed"),
    ),
    RuntimeSemantic(
        field_id="executionEntryAllowed.runtime", field_name="executionEntryAllowed",
        meaning="Authoritative per-decision MM execution-entry gate (ALLOW/BLOCK/RECOVERY_REQUIRED).",
        producer="backend/money_management/loss_http_api.py:1199-1354 / loss_execution_guard.py",
        authority_class="AUTHORITY_FLAG",
        allowed_values=("True", "False"),
        unknown_behavior="Fail-closed to BLOCK/UNKNOWN when the baseline is unknown/stale/incomplete.",
        safety_interpretation="Fail-closed; drives MoneyManagementExecutionEntryGate.",
        provenance=_src("backend/money_management/loss_http_api.py", "executionEntryAllowed"),
    ),
    RuntimeSemantic(
        field_id="executionEntryAllowed.config", field_name="executionEntryAllowed",
        meaning="Config arming flag (disarmed) in bot config; NOT the authoritative runtime decision source.",
        producer="backend/bot_manager/bot_manager.py:546,1801,3177 (config['executionEntryAllowed'])",
        authority_class="AUTHORITY_FLAG",
        allowed_values=("True", "False"),
        unknown_behavior="False when not True (get is True).",
        safety_interpretation="Disarmed; documented to stay False until session baseline complete.",
        provenance=_src("backend/bot_manager/bot_manager.py", "executionEntryAllowed"),
    ),
    RuntimeSemantic(
        field_id="emergencyLocked", field_name="emergencyLocked",
        meaning="Whether the emergency-stop lock is latched.",
        producer="backend/bot_manager/bot_manager.py:10043-10048 (governance_state['emergency_stop'])",
        authority_class="AUTHORITY_FLAG",
        allowed_values=("True", "False"),
        unknown_behavior="False when absent.",
        safety_interpretation="Fail-closed: if True, execution must halt.",
        provenance=_src("backend/runtime/governance_runtime.py", "emergency_stop"),
    ),
    RuntimeSemantic(
        field_id="emergencyState", field_name="emergencyState",
        meaning="Emergency stop transition state.",
        producer="backend/runtime/governance_runtime.py:41-49,446-466 (build_emergency_status)",
        authority_class="AUTHORITY_FLAG",
        allowed_values=("READY", "PROCESSING", "LOCKED", "ACTION_REQUIRED"),
        unknown_behavior="Advisory UNKNOWN tolerated by AI/reader; schema default 'UNLOCKED' is stale.",
        safety_interpretation="Any state other than READY requires operator attention.",
        provenance=_src("backend/runtime/governance_runtime.py", "build_emergency_status"),
    ),
    RuntimeSemantic(
        field_id="marketReady", field_name="marketReady",
        meaning="Whether a fresh accepted market snapshot / exchange book has been received since start.",
        producer="backend/bot_manager/bot_manager.py:10356 (BotManager.market_ready)",
        authority_class="DERIVED_DESCRIPTOR",
        allowed_values=("True", "False"),
        unknown_behavior="False initially and on stop.",
        safety_interpretation="Read-only descriptor; not a trading authority.",
        provenance=_src("backend/bot_manager/bot_manager.py", "market_ready"),
    ),
    RuntimeSemantic(
        field_id="marketStale", field_name="marketStale",
        meaning="Whether market data is stale (bot stopped or last update older than 5s).",
        producer="backend/bot_manager/bot_manager.py:9883-9886,10358",
        authority_class="DERIVED_DESCRIPTOR",
        allowed_values=("True", "False"),
        unknown_behavior="True when bot stopped or last update older than 5 seconds.",
        safety_interpretation="Read-only descriptor; informs health, not gate decision.",
        provenance=_src("backend/bot_manager/bot_manager.py", "market_stale"),
    ),
    RuntimeSemantic(
        field_id="paperBootstrapStatus", field_name="paperBootstrapStatus",
        meaning="Eligibility descriptor for restarting a stopped PAPER session from durable snapshot.",
        producer="backend/bot_manager/bot_manager.py:10122-10198,10774",
        authority_class="DERIVED_DESCRIPTOR",
        allowed_values=("UNAVAILABLE", "READY", "BLOCKED"),
        unknown_behavior="UNAVAILABLE when not applicable.",
        safety_interpretation="Read-only descriptor; accompanies paperBootstrapReasonCodes.",
        provenance=_src("backend/bot_manager/bot_manager.py", "paperBootstrapStatus"),
    ),
)


class RuntimeSemanticsRegistry:
    """Immutable runtime-term registry."""

    def __init__(self, records: tuple[RuntimeSemantic, ...] = RUNTIME_SEMANTICS) -> None:
        self._records = tuple(sorted(records, key=lambda r: r.field_id))
        self._by_id: dict[str, RuntimeSemantic] = {}
        for record in self._records:
            if record.field_id in self._by_id:
                raise ValueError(f"duplicate field_id: {record.field_id}")
            self._by_id[record.field_id] = record
        self._by_id = freeze_mapping(self._by_id)

    @property
    def entries(self) -> tuple[RuntimeSemantic, ...]:
        return self._records

    def get(self, field_id: str) -> RuntimeSemantic:
        return self._by_id[field_id]

    def by_field_name(self, field_name: str) -> tuple[RuntimeSemantic, ...]:
        return tuple(r for r in self._records if r.field_name == field_name)

    def stable_json(self) -> str:
        return stable_json(self._records)
