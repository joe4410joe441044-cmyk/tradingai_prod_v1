"""KuCoin GET-only cash-flow authority at the Futures capital boundary."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat


SCHEMA_VERSION = "money-management-cash-flow-checkpoint/v2"
LEGACY_SCHEMA_VERSION = "money-management-cash-flow-checkpoint/v1"
SOURCE = "KUCOIN_FUTURES_LEDGER"
TARGET_FILENAME = "cash_flow_checkpoint.json"
MAX_PROCESSED_IDS = 4096


class ExternalCashFlowType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"


@dataclass(frozen=True)
class ExternalCashFlowEvent:
    event_id: str
    event_type: ExternalCashFlowType
    currency: str
    amount: Decimal
    occurred_at: datetime
    source: str
    exchange_event_id: str

    def __post_init__(self):
        if not self.event_id or self.event_id != self.exchange_event_id:
            raise ValueError("stable exchange event identity required")
        if self.currency != "USDT":
            raise ValueError("UNSUPPORTED_CASH_FLOW_CURRENCY")
        if isinstance(self.amount, bool) or not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise TypeError("finite Decimal amount required")
        if self.amount == 0 or (self.event_type is ExternalCashFlowType.TRANSFER_IN and self.amount < 0) or (self.event_type is ExternalCashFlowType.TRANSFER_OUT and self.amount > 0):
            raise ValueError("signed non-zero cash-flow amount required")
        if not isinstance(self.occurred_at, datetime) or self.occurred_at.tzinfo is None:
            raise TypeError("timezone-aware occurred_at required")
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(timezone.utc))


@dataclass(frozen=True)
class CashFlowCheckpoint:
    last_successful_sync_at: datetime | None = None
    processed_event_ids: tuple[str, ...] = ()
    source: str = SOURCE
    schema_version: str = SCHEMA_VERSION
    revision: int = 0

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION or self.source != SOURCE:
            raise ValueError("cash-flow checkpoint authority invalid")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("cash-flow checkpoint revision invalid")
        if len(self.processed_event_ids) > MAX_PROCESSED_IDS or len(set(self.processed_event_ids)) != len(self.processed_event_ids):
            raise ValueError("processed event IDs invalid")
        if self.last_successful_sync_at is not None:
            if self.last_successful_sync_at.tzinfo is None:
                raise TypeError("sync timestamp must be timezone-aware")
            object.__setattr__(self, "last_successful_sync_at", self.last_successful_sync_at.astimezone(timezone.utc))


def _decimal(value):
    if value is None or isinstance(value, bool):
        raise ValueError("invalid amount")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid amount") from None
    if not result.is_finite() or result <= 0:
        raise ValueError("invalid amount")
    return result


def _time(value):
    if isinstance(value, bool):
        raise ValueError("invalid timestamp")
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid timestamp") from None


def classify_deposit(item):
    """Validate wallet deposit observation; it is not an MM boundary event."""
    required = {"id", "currency", "status", "amount", "fee", "createdAt"}
    if not isinstance(item, dict) or not required.issubset(item):
        raise ValueError("malformed deposit")
    if not str(item["id"]):
        raise ValueError("missing event ID")
    _decimal(item["amount"]); Decimal(str(item["fee"])); _time(item["createdAt"])
    status = item["status"]
    if status not in {"SUCCESS", "PROCESSING", "FAILURE"}:
        raise ValueError("unknown event status")
    return "EXTERNAL_DEPOSIT_OBSERVATION" if status == "SUCCESS" else "IGNORED_NOT_FINAL"


def classify_withdrawal(item):
    """Validate UTA withdrawal observation with its stable official id."""
    required = {"id", "currency", "status", "amount", "fee", "createdAt"}
    if not isinstance(item, dict) or not required.issubset(item):
        raise ValueError("malformed withdrawal")
    if not str(item["id"]):
        raise ValueError("missing event ID")
    _decimal(item["amount"]); Decimal(str(item["fee"])); _time(item["createdAt"])
    status = item["status"]
    if status not in {"SUCCESS", "PROCESSING", "FAILURE"}:
        raise ValueError("unknown event status")
    return "EXTERNAL_WITHDRAWAL_OBSERVATION" if status == "SUCCESS" else "IGNORED_NOT_FINAL"


def map_futures_ledger_item(item):
    """Map only completed Futures transfers; P/L, funding and fees stay trading."""
    required = {"offset", "currency", "type", "amount", "time", "status"}
    if not isinstance(item, dict) or not required.issubset(item):
        raise ValueError("malformed Futures ledger item")
    event_id = str(item["offset"])
    if not event_id:
        raise ValueError("missing event ID")
    status = item["status"]
    if status not in {"Completed", "Pending"}:
        raise ValueError("unknown event status")
    kind = str(item["type"]).lower()
    if kind not in {"transferin", "transferout"}:
        return None
    if status != "Completed":
        return None
    currency = item["currency"]
    if currency != "USDT":
        raise ValueError("UNSUPPORTED_CASH_FLOW_CURRENCY")
    amount = _decimal(item["amount"])
    event_type = ExternalCashFlowType.TRANSFER_IN if kind == "transferin" else ExternalCashFlowType.TRANSFER_OUT
    signed = amount if event_type is ExternalCashFlowType.TRANSFER_IN else -amount
    return ExternalCashFlowEvent(event_id, event_type, currency, signed,
                                 _time(item["time"]), SOURCE, event_id)


def eligible_events(items, *, baseline_at, processed_event_ids=()):
    if not isinstance(baseline_at, datetime) or baseline_at.tzinfo is None:
        raise TypeError("persisted baseline timestamp required")
    seen = set(processed_event_ids)
    result = []
    for item in items:
        event = map_futures_ledger_item(item)
        if event is None or event.occurred_at < baseline_at.astimezone(timezone.utc) or event.event_id in seen:
            continue
        seen.add(event.event_id); result.append(event)
    return tuple(sorted(result, key=lambda event: (event.occurred_at, event.event_id)))


def advance_checkpoint(checkpoint, events, *, synced_at):
    ids = list(checkpoint.processed_event_ids)
    ids.extend(event.event_id for event in events if event.event_id not in ids)
    new_ids = tuple(event.event_id for event in events
                    if event.event_id not in checkpoint.processed_event_ids)
    return CashFlowCheckpoint(synced_at, tuple(ids[-MAX_PROCESSED_IDS:]),
                              revision=checkpoint.revision + len(new_ids))


def net_external_cash_flow(events):
    """Input for cash_flow_adjustment.reconcile_equity_change."""
    if any(not isinstance(event, ExternalCashFlowEvent) for event in events):
        raise TypeError("typed external cash-flow events required")
    return sum((event.amount for event in events), Decimal("0"))


def validate_paginated_items(page, *, expected_page):
    required = {"currentPage", "pageSize", "totalNum", "totalPage", "items"}
    if not isinstance(page, dict) or set(page) != required:
        raise ValueError("pagination contract invalid")
    if page["currentPage"] != expected_page or not isinstance(page["items"], list):
        raise ValueError("pagination inconsistency")
    if any(type(page[key]) is not int or page[key] < 0 for key in ("pageSize", "totalNum", "totalPage")):
        raise ValueError("pagination contract invalid")
    if page["totalPage"] and expected_page > page["totalPage"]:
        raise ValueError("pagination inconsistency")
    return tuple(page["items"])


def validate_futures_ledger_page(page):
    if not isinstance(page, dict) or set(page) != {"dataList", "hasMore"}:
        raise ValueError("Futures ledger pagination contract invalid")
    if not isinstance(page["dataList"], list) or type(page["hasMore"]) is not bool:
        raise ValueError("Futures ledger pagination contract invalid")
    offsets = []
    for item in page["dataList"]:
        if not isinstance(item, dict) or isinstance(item.get("offset"), bool):
            raise ValueError("Futures ledger pagination contract invalid")
        try: offsets.append(int(item["offset"]))
        except (TypeError, ValueError):
            raise ValueError("Futures ledger pagination contract invalid") from None
    if page["hasMore"] and not offsets:
        raise ValueError("Futures ledger pagination inconsistency")
    return tuple(page["dataList"]), (min(offsets) if page["hasMore"] else None)


def baseline_from_persisted_loss_state(state):
    """The approved MM baseline is the persisted capture boundary, never a constant."""
    at = getattr(state, "captured_at", None)
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("authoritative persisted baseline unavailable")
    return at.astimezone(timezone.utc)


def _payload(checkpoint):
    return {"schemaVersion": checkpoint.schema_version, "source": checkpoint.source,
            "lastSuccessfulSyncAt": checkpoint.last_successful_sync_at.isoformat().replace("+00:00", "Z") if checkpoint.last_successful_sync_at else None,
            "processedEventIds": list(checkpoint.processed_event_ids),
            "revision": checkpoint.revision}


def save_cash_flow_checkpoint(checkpoint, base_directory):
    base = Path(base_directory)
    if not base.is_absolute() or not base.is_dir() or base.is_symlink():
        raise OSError("unsafe checkpoint directory")
    payload = _payload(checkpoint)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    envelope = json.dumps({"integrityAlgorithm": "SHA256", "integrityDigest": hashlib.sha256(canonical).hexdigest(), "payload": payload}, sort_keys=True, separators=(",", ":")).encode()
    target, temporary = base / TARGET_FILENAME, base / (TARGET_FILENAME + ".tmp")
    if target.exists() and (target.is_symlink() or target.stat().st_mode & 0o077):
        raise OSError("unsafe checkpoint file")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, envelope); os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, target)
    directory_fd = os.open(base, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try: os.fsync(directory_fd)
    finally: os.close(directory_fd)


def load_cash_flow_checkpoint(base_directory):
    target = Path(base_directory) / TARGET_FILENAME
    if not target.exists():
        return CashFlowCheckpoint()
    if target.is_symlink() or not stat.S_ISREG(target.stat().st_mode) or target.stat().st_mode & 0o077:
        raise OSError("unsafe checkpoint file")
    envelope = json.loads(target.read_text("utf-8"))
    if set(envelope) != {"integrityAlgorithm", "integrityDigest", "payload"} or envelope["integrityAlgorithm"] != "SHA256":
        raise ValueError("checkpoint envelope invalid")
    payload = envelope["payload"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if not hmac.compare_digest(envelope["integrityDigest"], hashlib.sha256(canonical).hexdigest()):
        raise ValueError("checkpoint integrity invalid")
    legacy = payload.get("schemaVersion") == LEGACY_SCHEMA_VERSION
    expected = {"schemaVersion", "source", "lastSuccessfulSyncAt", "processedEventIds"}
    if set(payload) != (expected if legacy else expected | {"revision"}):
        raise ValueError("checkpoint payload invalid")
    at = payload["lastSuccessfulSyncAt"]
    parsed = datetime.fromisoformat(at.replace("Z", "+00:00")) if at else None
    return CashFlowCheckpoint(parsed, tuple(payload["processedEventIds"]),
                              payload["source"], SCHEMA_VERSION,
                              payload.get("revision", len(payload["processedEventIds"])))
