"""Canonical serialization for MM-3B loss persistence."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from typing import Any

from .loss_persistence_models import PersistedLossState

MAX_FILE_SIZE = 256 * 1024
ENVELOPE_VERSION = "money-management-loss-envelope/v1"
INTEGRITY_ALGORITHM = "SHA256"

_DECIMAL_KEYS = {"starting_equity","net_realized_pnl","net_loss","loss_percent","cash_flow_amount","high_water_mark","current_equity","drawdown_amount","drawdown_percent","net_cash_flow_amount","net_loss","loss_percent"}

def _canon(value, key=None):
    if isinstance(value, dict):
        return {k: _canon(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_canon(v, key) for v in value]
    if key in _DECIMAL_KEYS and isinstance(value, str):
        d = Decimal(value)
        if d == 0:
            return "0"
        return format(d.normalize(), "f")
    if isinstance(value, str) and key in {"captured_at","period_start","period_end","last_updated_at","last_cash_flow_at","evaluated_at"}:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            return value
    return value

def build_canonical_loss_state_json(state: PersistedLossState) -> bytes:
    if not isinstance(state, PersistedLossState):
        raise TypeError("PersistedLossState required")
    payload = _canon(state.to_dict())
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")

def serialize_loss_state_canonical(state: PersistedLossState) -> bytes:
    return build_canonical_loss_state_json(state)

def build_integrity_digest(payload: bytes) -> str:
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    return sha256(payload).hexdigest()

def serialize_loss_persistence_envelope(state: PersistedLossState) -> bytes:
    payload_bytes = build_canonical_loss_state_json(state)
    envelope = {
        "envelope_version": ENVELOPE_VERSION,
        "integrity_algorithm": INTEGRITY_ALGORITHM,
        "integrity_digest": build_integrity_digest(payload_bytes),
        "payload": json.loads(payload_bytes.decode("utf-8")),
    }
    return json.dumps(envelope, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
