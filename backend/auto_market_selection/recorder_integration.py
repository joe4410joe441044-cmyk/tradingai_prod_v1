"""AMS-3A event projection for the existing Market Recorder authority.

This module deliberately owns no storage and performs no AMS calculation.  It
projects completed AMS contracts into a stable envelope and hands that envelope
to an injected Recorder event sink.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping, Optional

from .candidate_ranking import RankingCycleResult
from .market_scanner import ScannerCycleResult
from .safe_switch import SwitchResult
from .selection_audit import SelectionAuditEvent
from .selection_proposal import SelectionProposal


AMS_SCAN = "AMS_SCAN"
AMS_RANKING = "AMS_RANKING"
AMS_SELECTION_AUDIT = "AMS_SELECTION_AUDIT"
AMS_SELECTION_PROPOSAL = "AMS_SELECTION_PROPOSAL"
AMS_SYMBOL_SWITCH = "AMS_SYMBOL_SWITCH"
AMS_RECORDER_PAYLOAD_VERSION = "1"

_SENSITIVE_KEYS = {
    "apikey", "api_key", "secret", "passphrase", "token", "credential",
    "credentials", "credentialpath", "credential_path",
}


def _json_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError("timezone-aware datetime required")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("AMS recorder payload must be JSON compatible")


def _assert_no_credentials(value):
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            compact = normalized.replace("_", "")
            if normalized in _SENSITIVE_KEYS or compact in _SENSITIVE_KEYS:
                raise ValueError("credentials are forbidden in AMS recorder events")
            _assert_no_credentials(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _assert_no_credentials(item)


def _event_id(event_type, source_id):
    canonical = json.dumps(
        {"eventType": event_type, "sourceContractId": source_id},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return "ams-rec-" + sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _envelope(*, event_type, source_id, timestamp, active_symbol, runtime_id,
              scanner_cycle_id=None, ranking_cycle_id=None, audit_event_id=None,
              selection_proposal_id=None, switch_transaction_id=None, payload):
    body = _json_value(payload)
    _assert_no_credentials(body)
    return {
        "eventId": _event_id(event_type, source_id),
        "eventType": event_type,
        "timestamp": _json_value(timestamp),
        "activeSymbol": active_symbol,
        "runtimeId": runtime_id,
        "scannerCycleId": scanner_cycle_id,
        "rankingCycleId": ranking_cycle_id,
        "auditEventId": audit_event_id,
        "selectionProposalId": selection_proposal_id,
        "switchTransactionId": switch_transaction_id,
        "payloadVersion": AMS_RECORDER_PAYLOAD_VERSION,
        "payload": body,
    }


def scanner_event(result, *, active_symbol=None, runtime_id=None):
    if not isinstance(result, ScannerCycleResult):
        raise TypeError("ScannerCycleResult required")
    return _envelope(
        event_type=AMS_SCAN, source_id=result.scanner_cycle_id,
        timestamp=result.evaluated_at, active_symbol=active_symbol,
        runtime_id=runtime_id, scanner_cycle_id=result.scanner_cycle_id,
        payload=result.to_dict(),
    )


def ranking_event(result, *, active_symbol=None, runtime_id=None):
    if not isinstance(result, RankingCycleResult):
        raise TypeError("RankingCycleResult required")
    return _envelope(
        event_type=AMS_RANKING, source_id=result.ranking_cycle_id,
        timestamp=result.evaluated_at, active_symbol=active_symbol,
        runtime_id=runtime_id, scanner_cycle_id=result.scanner_cycle_id,
        ranking_cycle_id=result.ranking_cycle_id, payload=result.to_dict(),
    )


def selection_audit_event(result, *, active_symbol=None, runtime_id=None):
    if not isinstance(result, SelectionAuditEvent):
        raise TypeError("SelectionAuditEvent required")
    return _envelope(
        event_type=AMS_SELECTION_AUDIT, source_id=result.event_id,
        timestamp=result.evaluated_at, active_symbol=active_symbol,
        runtime_id=runtime_id, scanner_cycle_id=result.scanner_cycle_id,
        ranking_cycle_id=result.ranking_cycle_id, audit_event_id=result.event_id,
        payload=result.to_dict(),
    )


def selection_proposal_event(result, *, runtime_id=None):
    if not isinstance(result, SelectionProposal):
        raise TypeError("SelectionProposal required")
    return _envelope(
        event_type=AMS_SELECTION_PROPOSAL,
        source_id=result.selection_proposal_id, timestamp=result.proposed_at,
        active_symbol=result.current_active_symbol, runtime_id=runtime_id,
        scanner_cycle_id=result.scanner_cycle_id,
        ranking_cycle_id=result.ranking_cycle_id,
        audit_event_id=result.audit_event_id,
        selection_proposal_id=result.selection_proposal_id,
        payload=result.to_dict(),
    )


def symbol_switch_event(result, *, active_symbol=None, runtime_id=None):
    if not isinstance(result, SwitchResult):
        raise TypeError("SwitchResult required")
    authoritative_symbol = active_symbol
    if authoritative_symbol is None:
        authoritative_symbol = result.committed_symbol or result.previous_symbol
    return _envelope(
        event_type=AMS_SYMBOL_SWITCH, source_id=result.switch_transaction_id,
        timestamp=result.completed_at, active_symbol=authoritative_symbol,
        runtime_id=runtime_id, scanner_cycle_id=result.scanner_cycle_id,
        ranking_cycle_id=result.ranking_cycle_id,
        audit_event_id=result.audit_event_id,
        selection_proposal_id=result.selection_proposal_id,
        switch_transaction_id=result.switch_transaction_id,
        payload=result.to_dict(),
    )


@dataclass(frozen=True)
class RecorderWriteResult:
    event_id: str
    recorded: bool
    error_code: Optional[str] = None


class AMSRecorderIntegration:
    """Best-effort adapter to an existing sink exposing ``record_event``.

    Recorder failure is observational: it cannot alter AMS contracts, active
    symbol authority, governance, or execution.
    """

    def __init__(self, event_sink):
        writer = getattr(event_sink, "record_event", None)
        if not callable(writer):
            raise TypeError("Market Recorder event sink required")
        self._writer = writer

    def record(self, event):
        event = _json_value(event)
        _assert_no_credentials(event)
        event_id = event.get("eventId") if isinstance(event, dict) else None
        if not event_id:
            raise ValueError("AMS recorder eventId required")
        try:
            result = self._writer(event)
            if result is False:
                return RecorderWriteResult(event_id, False, "RECORDER_REJECTED")
            return RecorderWriteResult(event_id, True)
        except Exception:
            return RecorderWriteResult(event_id, False, "RECORDER_WRITE_FAILED")

    def record_scanner(self, result, *, active_symbol=None, runtime_id=None):
        return self.record(scanner_event(result, active_symbol=active_symbol, runtime_id=runtime_id))

    def record_ranking(self, result, *, active_symbol=None, runtime_id=None):
        return self.record(ranking_event(result, active_symbol=active_symbol, runtime_id=runtime_id))

    def record_selection_audit(self, result, *, active_symbol=None, runtime_id=None):
        return self.record(selection_audit_event(result, active_symbol=active_symbol, runtime_id=runtime_id))

    def record_selection_proposal(self, result, *, runtime_id=None):
        return self.record(selection_proposal_event(result, runtime_id=runtime_id))

    def record_symbol_switch(self, result, *, active_symbol=None, runtime_id=None):
        return self.record(symbol_switch_event(result, active_symbol=active_symbol, runtime_id=runtime_id))
