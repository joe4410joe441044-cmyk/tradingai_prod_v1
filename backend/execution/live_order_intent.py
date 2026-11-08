# -*- coding: utf-8 -*-
"""Durable live-order intents and exchange-evidence protection states.

The store is written before any order POST. A timestamp is not an order id.
Liquidation prices are not computed here.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import uuid
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP

INTENT_RECORDED = "INTENT_RECORDED"
UNKNOWN_COMMIT = "UNKNOWN_COMMIT"
ACCEPTED = "ACCEPTED"
FILLED = "FILLED"
REJECTED = "REJECTED"
NOT_FOUND_INCONCLUSIVE = "NOT_FOUND_INCONCLUSIVE"
PROTECTION_PENDING = "PROTECTION_PENDING"
PROTECTION_CONFIRMED = "PROTECTION_CONFIRMED"
PROTECTION_UNKNOWN = "PROTECTION_UNKNOWN"
UNPROTECTED = "UNPROTECTED"
EXIT_PENDING = "EXIT_PENDING"
RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
FLAT_CONFIRMED = "FLAT_CONFIRMED"

PURPOSE_ENTRY = "ENTRY"
PURPOSE_EXIT = "EXIT"
PURPOSE_PROTECTION = "PROTECTION"

_ENTRY_BLOCKING = {
    UNKNOWN_COMMIT,
    ACCEPTED,
    FILLED,
    NOT_FOUND_INCONCLUSIVE,
    PROTECTION_PENDING,
    PROTECTION_CONFIRMED,
    PROTECTION_UNKNOWN,
    UNPROTECTED,
    EXIT_PENDING,
    RECONCILIATION_REQUIRED,
}

_CLIENT_OID_PREFIX = "ta"

_PROTECTED_PATHS_ENV = "TRADINGAI_LIVE_ORDER_INTENT_PROTECTED_PATHS"
STORE_PATH_PROTECTED = "STORE_PATH_PROTECTED"


def _canonical_store_path(path):
    if path is None:
        return None
    try:
        text = os.fspath(path)
    except TypeError:
        return None
    if not text:
        return None
    return os.path.realpath(os.path.abspath(os.path.expanduser(text)))


def store_paths_conflict(first, second):
    """True when two paths resolve to the same durable store.

    Relative paths, symlinks (including symlinked parent directories) and hard
    links that share an inode are treated as the same store. A string compare
    alone is not sufficient.
    """

    first_path = _canonical_store_path(first)
    second_path = _canonical_store_path(second)
    if first_path is None or second_path is None:
        return False
    if first_path == second_path:
        return True
    try:
        if os.path.exists(first_path) and os.path.exists(second_path):
            return os.path.samefile(first_path, second_path)
    except OSError:
        return False
    return False


def _protected_store_paths():
    raw = os.environ.get(_PROTECTED_PATHS_ENV)
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        decoded = raw.split(os.pathsep)
    if isinstance(decoded, str):
        decoded = [decoded]
    if not isinstance(decoded, (list, tuple)):
        return []
    return [item for item in decoded if isinstance(item, str) and item]


def protected_store_conflict(path):
    """Return ``STORE_PATH_PROTECTED`` when ``path`` aliases a protected store.

    The protected list is opt-in and only ever denies a path. It never widens
    or bypasses a production safety boundary. The production runtime does not
    set it, so the normal production store is still accepted.
    """

    canonical = _canonical_store_path(path)
    if canonical is None:
        return None
    for protected in _protected_store_paths():
        if store_paths_conflict(path, protected):
            return STORE_PATH_PROTECTED
        protected_path = _canonical_store_path(protected)
        if protected_path and os.path.isdir(protected_path):
            try:
                if os.path.commonpath([canonical, protected_path]) == protected_path:
                    return STORE_PATH_PROTECTED
            except ValueError:
                continue
    return None


DURABLE_READINESS_CHECKS = (
    ("durableOrderIntentStoreReady", "LIVE_ORDER_INTENT_STORE_UNAVAILABLE", "storeReady"),
    ("orderRecoveryComplete", "LIVE_ORDER_RECOVERY_INCOMPLETE", "recoveryComplete"),
    ("unknownCommitClear", "LIVE_ORDER_UNKNOWN_COMMIT", "unknownCommitClear"),
    ("unprotectedClear", "LIVE_POSITION_UNPROTECTED", "unprotectedClear"),
    ("protectionPendingClear", "LIVE_PROTECTION_PENDING", "protectionPendingClear"),
    ("protectionKnown", "LIVE_PROTECTION_UNKNOWN", "protectionKnown"),
    ("exitReconciliationClear", "LIVE_EXIT_RECONCILIATION_REQUIRED", "exitReconciliationClear"),
    ("exchangeStateFresh", "LIVE_EXCHANGE_STATE_UNKNOWN", "exchangeStateFresh"),
)


def apply_durable_readiness(checks, block_reasons, gates):
    """Fold durable-order facts into the existing readiness checks.

    A missing gate map means this runtime is not on the formal LIVE path.
    Present gates that are not exactly true add a block reason. There is no
    separate ready flag.
    """

    if not isinstance(gates, dict):
        return
    for check_name, reason, gate_name in DURABLE_READINESS_CHECKS:
        ok = gates.get(gate_name) is True
        checks[check_name] = ok
        if not ok:
            block_reasons.append(reason)


def liquidation_risk_boundary():
    """F-03 stays unresolved. No liquidation price is derived."""

    return {
        "LIQUIDATION_2X": "UNKNOWN",
        "LIQUIDATION_3X": "UNKNOWN",
        "ready": False,
        "reason": "LIQUIDATION_FEE_RATE_UNAVAILABLE",
    }


def client_oid_for(intent_id):
    """KuCoin futures clientOid: caller-defined, maximum length 40.

    The id is a hash of the logical intent. It contains no account secret.
    """

    digest = hashlib.sha256(str(intent_id).encode("utf-8")).hexdigest()[:32]
    oid = _CLIENT_OID_PREFIX + digest
    if len(oid) > 40 or not oid.isalnum():
        raise ValueError("CLIENT_OID_CONTRACT_VIOLATION")
    return oid


def format_stop_price(value):
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not price.is_finite() or price <= 0:
        return None
    return format(price, "f")


def quantize_stop_price(value, tick_size, close_side):
    """Return a tick-conformant stop price, never less protective.

    The close side decides the safe rounding direction: a long is sold when
    mark falls, so its stop is rounded UP (closer to entry); a short is bought
    when mark rises, so its stop is rounded DOWN (closer to entry). Invalid
    inputs return ``None`` so the caller fails closed.
    """

    price_text = format_stop_price(value)
    tick_text = format_stop_price(tick_size)
    if price_text is None or tick_text is None:
        return None
    side = str(close_side or "").strip().lower()
    if side == "sell":
        rounding = ROUND_UP
    elif side == "buy":
        rounding = ROUND_DOWN
    else:
        return None
    try:
        price = Decimal(price_text)
        tick = Decimal(tick_text)
        quantized = (price / tick).to_integral_value(rounding=rounding) * tick
    except (InvalidOperation, ValueError):
        return None
    if not quantized.is_finite() or quantized <= 0:
        return None
    return format(quantized, "f")


def protective_stop_sides(position_side):
    """Reduce-only stop direction for a filled futures position.

    A long is sold when mark trades down through the stop. A short is bought
    when mark trades up through the stop. KuCoin stop values are ``down`` and
    ``up`` on the same Add Order contract, with ``stopPriceType=MP``.
    """

    side = str(position_side or "").strip().lower()
    if side in {"buy", "long"}:
        return "sell", "down"
    if side in {"sell", "short"}:
        return "buy", "up"
    return None, None


class IntentStoreError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class IntentStore:
    def __init__(self, path, *, max_not_found=3):
        self.path = path
        self.max_not_found = max_not_found
        self._lock = threading.RLock()
        self._intents = {}
        self.load_error = None
        conflict = protected_store_conflict(path)
        if conflict:
            self.load_error = conflict
            return
        self._load()

    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError:
            self.load_error = "STORE_CORRUPT"
            self._intents = {}
            return
        except OSError:
            self.load_error = "STORE_READ_FAILED"
            self._intents = {}
            return
        intents = payload.get("intents") if isinstance(payload, dict) else None
        if not isinstance(intents, dict):
            self.load_error = "STORE_CORRUPT"
            self._intents = {}
            return
        self._intents = intents

    def _process_lock(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        handle = open(self.path + ".lock", "a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise IntentStoreError("STORE_BUSY")
        except OSError:
            handle.close()
            raise IntentStoreError("STORE_WRITE_FAILED")
        return handle

    def _flush(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = self.path + ".tmp"
        payload = {"version": 1, "intents": self._intents}
        handle = open(temporary, "w", encoding="utf-8")
        try:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(temporary, self.path)

    def records(self):
        with self._lock:
            return [dict(record) for record in self._intents.values()]

    def get(self, intent_id):
        with self._lock:
            record = self._intents.get(intent_id)
            return None if record is None else dict(record)

    def begin(
        self,
        *,
        purpose,
        symbol,
        side,
        size,
        intent_id=None,
        parent_id=None,
        stop_price=None,
    ):
        symbol = str(symbol or "").strip()
        side = str(side or "").strip().lower()
        size_text = str(size)
        with self._lock:
            if self.load_error:
                return {"ok": False, "reason": self.load_error}
            try:
                process_lock = self._process_lock()
            except IntentStoreError as exc:
                return {"ok": False, "reason": exc.reason}
            try:
                return self._begin_locked(
                    purpose=purpose,
                    symbol=symbol,
                    side=side,
                    size_text=size_text,
                    intent_id=intent_id,
                    parent_id=parent_id,
                    stop_price=stop_price,
                )
            finally:
                fcntl.flock(process_lock.fileno(), fcntl.LOCK_UN)
                process_lock.close()

    def _begin_locked(
        self,
        *,
        purpose,
        symbol,
        side,
        size_text,
        intent_id,
        parent_id,
        stop_price,
    ):
        if intent_id and intent_id in self._intents:
            current = dict(self._intents[intent_id])
            same = (
                current.get("purpose") == purpose
                and current.get("symbol") == symbol
                and current.get("side") == side
                and str(current.get("size")) == size_text
                and current.get("parentId") == parent_id
            )
            if not same:
                current["ok"] = False
                current["reason"] = "ACCOUNT_SYMBOL_MISMATCH"
                return current
            current["ok"] = True
            current["created"] = False
            return current
        if purpose == PURPOSE_PROTECTION and parent_id:
            for record in self._intents.values():
                if (
                    record.get("purpose") == PURPOSE_PROTECTION
                    and record.get("parentId") == parent_id
                    and record.get("state") in {
                        PROTECTION_PENDING,
                        PROTECTION_CONFIRMED,
                        PROTECTION_UNKNOWN,
                        UNKNOWN_COMMIT,
                    }
                ):
                    existing = dict(record)
                    existing["ok"] = True
                    existing["created"] = False
                    existing["duplicate"] = True
                    return existing
        new_id = intent_id or str(uuid.uuid4())
        record = {
            "intentId": new_id,
            "clientOid": client_oid_for(new_id),
            "purpose": purpose,
            "symbol": symbol,
            "side": side,
            "size": size_text,
            "parentId": parent_id,
            "stopPrice": stop_price,
            "state": INTENT_RECORDED,
            "notFoundCount": 0,
            "orderId": None,
            "ok": True,
            "created": True,
            "duplicate": False,
        }
        self._intents[new_id] = {
            key: value for key, value in record.items() if key not in {"ok", "created", "duplicate"}
        }
        try:
            self._flush()
        except OSError:
            self._intents.pop(new_id, None)
            failed = dict(record)
            failed["ok"] = False
            failed["reason"] = "STORE_WRITE_FAILED"
            return failed
        return record

    def mark(self, intent_id, state, **fields):
        with self._lock:
            if self.load_error:
                return None
            current = self._intents.get(intent_id)
            if current is None:
                return None
            try:
                process_lock = self._process_lock()
            except IntentStoreError:
                return None
            previous = dict(current)
            try:
                current["state"] = state
                for key, value in fields.items():
                    current[key] = value
                self._flush()
                return dict(current)
            except OSError:
                current.clear()
                current.update(previous)
                return None
            finally:
                fcntl.flock(process_lock.fileno(), fcntl.LOCK_UN)
                process_lock.close()

    def note_not_found(self, intent_id):
        with self._lock:
            current = self._intents.get(intent_id)
            if current is None or self.load_error:
                return None
            count = int(current.get("notFoundCount") or 0) + 1
            state = (
                PROTECTION_UNKNOWN
                if current.get("purpose") == PURPOSE_PROTECTION
                else UNKNOWN_COMMIT
            )
            reason = "NOT_FOUND_INCONCLUSIVE"
            if count >= self.max_not_found:
                state = RECONCILIATION_REQUIRED
                reason = "PERSISTENT_UNKNOWN"
            return self.mark(
                intent_id,
                state,
                notFoundCount=count,
                reason=reason,
            )

    def entry_blocked(self, symbol, except_id=None):
        symbol = str(symbol or "").strip()
        with self._lock:
            for record in self._intents.values():
                if record.get("symbol") != symbol:
                    continue
                if except_id and record.get("intentId") == except_id:
                    continue
                if record.get("state") in _ENTRY_BLOCKING or record.get("state") == INTENT_RECORDED:
                    return dict(record)
            return None

    def unresolved(self, purpose, symbol):
        symbol = str(symbol or "").strip()
        with self._lock:
            for record in self._intents.values():
                if record.get("purpose") != purpose or record.get("symbol") != symbol:
                    continue
                if record.get("state") in {
                    INTENT_RECORDED,
                    UNKNOWN_COMMIT,
                    NOT_FOUND_INCONCLUSIVE,
                    EXIT_PENDING,
                    RECONCILIATION_REQUIRED,
                    ACCEPTED,
                }:
                    return dict(record)
            return None
