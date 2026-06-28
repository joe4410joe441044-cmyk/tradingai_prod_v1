# backend/runtime/packetIntegrity.py

import time
import copy
from typing import Dict, Any, Optional


# =========================================================
# CONFIG
# =========================================================

STALE_THRESHOLD_MS = 3000

INTEGRITY_WEIGHTS = {
    "schema": 0.30,
    "sequence": 0.20,
    "stale": 0.20,
    "duplicate": 0.15,
    "book": 0.15,
}


# =========================================================
# RUNTIME STATE
# =========================================================

_last_sequence = None
_last_timestamp = None

_last_book_signature = None

_runtime_stats = {
    "processed": 0,
    "accepted": 0,
    "rejected": 0,
    "duplicates": 0,
    "stale": 0,
    "malformed": 0,
    "sequence_errors": 0,
}


# =========================================================
# HELPERS
# =========================================================

def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _current_timestamp_ms():
    return int(time.time() * 1000)


def _book_signature(packet: Dict[str, Any]):

    bids = packet.get("bids", [])
    asks = packet.get("asks", [])

    top_bid = bids[0] if bids else [0, 0]
    top_ask = asks[0] if asks else [0, 0]

    return (
        str(top_bid),
        str(top_ask),
    )


# =========================================================
# SCHEMA VALIDATION
# =========================================================

def validate_packet_schema(packet: Dict[str, Any]):

    required_fields = [
        "symbol",
        "timestamp",
        "sequence",
        "bids",
        "asks",
    ]

    for field in required_fields:

        if field not in packet:
            return False, f"missing_field:{field}"

        if packet[field] is None:
            return False, f"null_field:{field}"

    if not isinstance(packet["symbol"], str):
        return False, "invalid_symbol"

    if not isinstance(packet["timestamp"], (int, float)):
        return False, "invalid_timestamp"

    if not isinstance(packet["sequence"], int):
        return False, "invalid_sequence"

    if not isinstance(packet["bids"], list):
        return False, "invalid_bids"

    if not isinstance(packet["asks"], list):
        return False, "invalid_asks"

    if len(packet["bids"]) == 0:
        return False, "empty_bids"

    if len(packet["asks"]) == 0:
        return False, "empty_asks"

    top_bid = packet["bids"][0]
    top_ask = packet["asks"][0]

    if not isinstance(top_bid, (list, tuple)):
        return False, "invalid_bid_structure"

    if not isinstance(top_ask, (list, tuple)):
        return False, "invalid_ask_structure"

    if len(top_bid) < 2:
        return False, "invalid_bid_length"

    if len(top_ask) < 2:
        return False, "invalid_ask_length"

    return True, None


# =========================================================
# SEQUENCE VALIDATION
# =========================================================

def validate_sequence_integrity(packet: Dict[str, Any]):

    global _last_sequence

    sequence = packet["sequence"]

    if _last_sequence is None:

        _last_sequence = sequence
        return True, None

    if sequence < _last_sequence:

        return False, "sequence_rollback"

    if sequence == _last_sequence:

        return False, "duplicate_sequence"

    gap = sequence - _last_sequence

    if gap > 100:

        _last_sequence = sequence
        return False, f"sequence_gap:{gap}"

    _last_sequence = sequence

    return True, None


# =========================================================
# DUPLICATE DETECTION
# =========================================================

def detect_duplicate_packet(packet: Dict[str, Any]):

    global _last_timestamp
    global _last_book_signature

    timestamp = packet["timestamp"]

    current_signature = _book_signature(packet)

    if _last_timestamp == timestamp:

        return True, "duplicate_timestamp"

    if _last_book_signature == current_signature:

        return True, "duplicate_book"

    _last_timestamp = timestamp
    _last_book_signature = current_signature

    return False, None


# =========================================================
# STALE DETECTION
# =========================================================

def detect_stale_packet(packet: Dict[str, Any]):

    packet_timestamp = int(packet["timestamp"])

    now = _current_timestamp_ms()

    drift = now - packet_timestamp

    if drift > STALE_THRESHOLD_MS:

        return True, f"stale_packet:{drift}ms"

    return False, None


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_packet(packet: Dict[str, Any]):

    bids = copy.deepcopy(packet["bids"])
    asks = copy.deepcopy(packet["asks"])

    best_bid_price = _safe_float(bids[0][0])
    best_bid_volume = _safe_float(bids[0][1])

    best_ask_price = _safe_float(asks[0][0])
    best_ask_volume = _safe_float(asks[0][1])

    spread = best_ask_price - best_bid_price

    mid_price = (
        (best_bid_price + best_ask_price) / 2
    )

    normalized = {
        "symbol": packet["symbol"],

        "timestamp": int(packet["timestamp"]),

        "sequence": int(packet["sequence"]),

        "best_bid": best_bid_price,
        "best_ask": best_ask_price,

        "spread": spread,

        "bid_volume": best_bid_volume,
        "ask_volume": best_ask_volume,

        "mid_price": mid_price,

        "raw_bid_levels": bids,
        "raw_ask_levels": asks,
    }

    return normalized


# =========================================================
# INTEGRITY SCORE
# =========================================================

def compute_packet_integrity(
    schema_valid=True,
    sequence_valid=True,
    stale=False,
    duplicate=False,
    valid_book=True,
):

    score = 1.0

    if not schema_valid:
        score -= INTEGRITY_WEIGHTS["schema"]

    if not sequence_valid:
        score -= INTEGRITY_WEIGHTS["sequence"]

    if stale:
        score -= INTEGRITY_WEIGHTS["stale"]

    if duplicate:
        score -= INTEGRITY_WEIGHTS["duplicate"]

    if not valid_book:
        score -= INTEGRITY_WEIGHTS["book"]

    score = max(0.0, min(1.0, score))

    return round(score, 4)


# =========================================================
# MAIN PIPELINE
# =========================================================

def process_packet_integrity(packet: Dict[str, Any]):

    global _runtime_stats

    _runtime_stats["processed"] += 1

    # =====================================================
    # SCHEMA
    # =====================================================

    schema_valid, schema_reason = validate_packet_schema(packet)

    if not schema_valid:

        _runtime_stats["rejected"] += 1
        _runtime_stats["malformed"] += 1

        integrity_score = compute_packet_integrity(
            schema_valid=False
        )

        return {
            "valid": False,
            "normalized": None,
            "integrityScore": integrity_score,
            "degraded": True,
            "reason": schema_reason,
        }

    # =====================================================
    # SEQUENCE
    # =====================================================

    sequence_valid, sequence_reason = validate_sequence_integrity(packet)

    if not sequence_valid:

        _runtime_stats["sequence_errors"] += 1

        integrity_score = compute_packet_integrity(
            sequence_valid=False
        )

        return {
            "valid": False,
            "normalized": None,
            "integrityScore": integrity_score,
            "degraded": True,
            "reason": sequence_reason,
        }

    # =====================================================
    # DUPLICATE
    # =====================================================

    duplicate, duplicate_reason = detect_duplicate_packet(packet)

    if duplicate:

        _runtime_stats["duplicates"] += 1

        integrity_score = compute_packet_integrity(
            duplicate=True
        )

        return {
            "valid": False,
            "normalized": None,
            "integrityScore": integrity_score,
            "degraded": False,
            "reason": duplicate_reason,
        }

    # =====================================================
    # STALE
    # =====================================================

    stale, stale_reason = detect_stale_packet(packet)

    if stale:

        _runtime_stats["stale"] += 1

        integrity_score = compute_packet_integrity(
            stale=True
        )

        return {
            "valid": False,
            "normalized": None,
            "integrityScore": integrity_score,
            "degraded": True,
            "reason": stale_reason,
        }

    # =====================================================
    # NORMALIZATION
    # =====================================================

    normalized = normalize_packet(packet)

    # =====================================================
    # BOOK VALIDATION
    # =====================================================

    valid_book = True

    if normalized["best_ask"] <= normalized["best_bid"]:
        valid_book = False

    if normalized["spread"] <= 0:
        valid_book = False

    integrity_score = compute_packet_integrity(
        valid_book=valid_book
    )

    if not valid_book:

        return {
            "valid": False,
            "normalized": None,
            "integrityScore": integrity_score,
            "degraded": True,
            "reason": "invalid_spread",
        }

    # =====================================================
    # ACCEPT
    # =====================================================

    _runtime_stats["accepted"] += 1

    return {
        "valid": True,
        "normalized": normalized,
        "integrityScore": integrity_score,
        "degraded": False,
        "reason": None,
    }


# =========================================================
# TELEMETRY
# =========================================================

def get_packet_integrity_telemetry():

    processed = _runtime_stats["processed"]

    acceptance_rate = 0.0

    if processed > 0:

        acceptance_rate = (
            _runtime_stats["accepted"] / processed
        )

    return {
        "packetIntegrity": {
            "processed": processed,
            "accepted": _runtime_stats["accepted"],
            "rejected": _runtime_stats["rejected"],
            "duplicates": _runtime_stats["duplicates"],
            "stale": _runtime_stats["stale"],
            "malformed": _runtime_stats["malformed"],
            "sequenceErrors": _runtime_stats["sequence_errors"],
            "acceptanceRate": round(acceptance_rate, 4),
        }
    }