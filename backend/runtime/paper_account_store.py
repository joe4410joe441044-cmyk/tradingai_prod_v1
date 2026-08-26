from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
import tempfile
import time


MIN_CAPITAL = Decimal("0.01")
MAX_CAPITAL = Decimal("1000000000.00")


@dataclass(frozen=True)
class PaperAccountObservation:
    account_scope: str
    equity: Decimal
    balance: Decimal
    available_balance: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    position: object
    positions: tuple
    position_state: str
    pending_order: bool
    observed_at: datetime
    freshness: str
    source: str


def normalize_capital(value):
    try:
        capital = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("INVALID_PAPER_CAPITAL")
    if not capital.is_finite() or capital < MIN_CAPITAL or capital > MAX_CAPITAL:
        raise ValueError("INVALID_PAPER_CAPITAL")
    if capital.as_tuple().exponent < -2:
        raise ValueError("INVALID_PAPER_CAPITAL_PRECISION")
    return capital.quantize(Decimal("0.01"))


class PaperAccountStore:
    SCHEMA_VERSION = 1

    def __init__(self, state_path, history_path=None, account_scope="primary"):
        if not isinstance(account_scope, str) or not account_scope.strip():
            raise ValueError("PAPER_ACCOUNT_SCOPE_INVALID")
        self.state_path = state_path
        self.account_scope = account_scope.strip()
        self.history_path = history_path or os.path.join(
            os.path.dirname(state_path),
            "paper_account_history.jsonl",
        )

    def default_state(self):
        now = time.time()
        return self.build_state(Decimal("1000.00"), "PAPER_SIMULATION", now)

    def unavailable_state(self, reason):
        return {
            "schemaVersion": self.SCHEMA_VERSION,
            "capital": None,
            "balance": None,
            "equity": None,
            "availableBalance": None,
            "realizedPnl": None,
            "unrealizedPnl": None,
            "totalPnl": None,
            "position": None,
            "positions": [],
            "positionState": "UNKNOWN",
            "pendingOrder": False,
            "updatedAt": None,
            "source": "PAPER_ACCOUNT_DURABLE_STATE",
            "restoreReason": reason,
        }

    def build_state(self, capital, source, updated_at=None):
        amount = normalize_capital(capital)
        timestamp = float(updated_at if updated_at is not None else time.time())
        return {
            "schemaVersion": self.SCHEMA_VERSION,
            "capital": format(amount, ".2f"),
            "balance": format(amount, ".2f"),
            "equity": format(amount, ".2f"),
            "availableBalance": format(amount, ".2f"),
            "realizedPnl": "0.00",
            "unrealizedPnl": "0.00",
            "totalPnl": "0.00",
            "position": None,
            "positions": [],
            "positionState": "FLAT",
            "pendingOrder": False,
            "updatedAt": timestamp,
            "source": source,
        }

    def load(self):
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except FileNotFoundError:
            return self.default_state()
        except (OSError, json.JSONDecodeError):
            return self.unavailable_state("PAPER_ACCOUNT_STATE_CORRUPT")

        try:
            if state.get("schemaVersion") != self.SCHEMA_VERSION:
                raise ValueError("schema")
            capital = normalize_capital(state.get("capital"))
            if state.get("position") is not None or state.get("positions") != []:
                raise ValueError("position")
            if state.get("pendingOrder") is not False:
                raise ValueError("pending")
            restored = self.build_state(
                capital, str(state.get("source") or "PAPER_SIMULATION"),
                state.get("updatedAt"),
            )
            for key in (
                "balance", "equity", "availableBalance", "realizedPnl",
                "unrealizedPnl", "totalPnl",
            ):
                value = Decimal(str(state[key]))
                if not value.is_finite():
                    raise ValueError(key)
                restored[key] = format(value, ".2f")
            return restored
        except (KeyError, ValueError, TypeError, InvalidOperation):
            return self.unavailable_state("PAPER_ACCOUNT_STATE_CORRUPT")

    def save(self, state):
        directory = os.path.dirname(self.state_path)
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            dir=directory,
            prefix=".paper-account-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=True, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.state_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def append_event(self, event):
        os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
        with open(self.history_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def observe(self, state, *, account_scope, observed_at, maximum_age):
        """Return one typed maintenance observation without changing state."""

        if account_scope != self.account_scope:
            raise ValueError("PAPER_ACCOUNT_SCOPE_MISMATCH")
        if (
            not isinstance(observed_at, datetime)
            or observed_at.tzinfo is None
            or observed_at.utcoffset() is None
        ):
            raise TypeError("PAPER_ACCOUNT_OBSERVED_AT_INVALID")
        if not isinstance(maximum_age, (int, float)) or maximum_age <= 0:
            raise ValueError("PAPER_ACCOUNT_MAXIMUM_AGE_INVALID")
        if not isinstance(state, dict) or state.get("restoreReason"):
            raise ValueError("PAPER_ACCOUNT_UNAVAILABLE")

        def decimal_field(name, *, nonnegative=False):
            raw = state.get(name)
            if raw is None or isinstance(raw, bool):
                raise ValueError(f"PAPER_ACCOUNT_{name.upper()}_MISSING")
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(f"PAPER_ACCOUNT_{name.upper()}_INVALID") from exc
            if not value.is_finite() or (nonnegative and value < 0):
                raise ValueError(f"PAPER_ACCOUNT_{name.upper()}_INVALID")
            return value

        timestamp = state.get("updatedAt")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise ValueError("PAPER_ACCOUNT_OBSERVED_TIME_INVALID")
        if not math.isfinite(timestamp) or timestamp <= 0:
            raise ValueError("PAPER_ACCOUNT_OBSERVED_TIME_INVALID")
        at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        now = observed_at.astimezone(timezone.utc)
        age = (now - at).total_seconds()
        if age < 0:
            raise ValueError("PAPER_ACCOUNT_OBSERVED_TIME_INCONSISTENT")
        freshness = "FRESH" if age <= maximum_age else "STALE"

        balance = decimal_field("balance", nonnegative=True)
        equity = decimal_field("equity", nonnegative=True)
        available = decimal_field("availableBalance", nonnegative=True)
        realized = decimal_field("realizedPnl")
        unrealized = decimal_field("unrealizedPnl")
        total = decimal_field("totalPnl")
        if available > balance or total != realized + unrealized:
            raise ValueError("PAPER_ACCOUNT_VALUES_INCONSISTENT")
        pending = state.get("pendingOrder")
        if type(pending) is not bool:
            raise ValueError("PAPER_ACCOUNT_PENDING_STATE_INVALID")
        position_state = state.get("positionState")
        position = state.get("position")
        positions = state.get("positions")
        if not isinstance(positions, list):
            raise ValueError("PAPER_ACCOUNT_POSITION_STATE_INVALID")
        if position_state == "FLAT":
            if position is not None or positions:
                raise ValueError("PAPER_ACCOUNT_POSITION_STATE_INCONSISTENT")
        elif position_state == "OPEN":
            if position is None and not positions:
                raise ValueError("PAPER_ACCOUNT_POSITION_STATE_INCONSISTENT")
        else:
            raise ValueError("PAPER_ACCOUNT_POSITION_STATE_INVALID")
        source = state.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("PAPER_ACCOUNT_SOURCE_INVALID")
        return PaperAccountObservation(
            self.account_scope, equity, balance, available, realized,
            unrealized, total, position, tuple(positions), position_state,
            pending, at, freshness, source,
        )

    @staticmethod
    def as_runtime_snapshot(state):
        reason = state.get("restoreReason")
        if reason:
            return {
                "balance": None,
                "equity": None,
                "availableBalance": None,
                "pnl": None,
                "position": None,
                "positions": [],
                "realizedPnl": None,
                "unrealizedPnl": None,
                "last_update": state.get("updatedAt"),
                "available": False,
                "source": state.get("source"),
                "reason": reason,
                "paperCapital": None,
            }
        return {
            "balance": float(state["balance"]),
            "equity": float(state["equity"]),
            "availableBalance": float(state["availableBalance"]),
            "pnl": float(state["totalPnl"]),
            "position": None,
            "positions": [],
            "realizedPnl": float(state["realizedPnl"]),
            "unrealizedPnl": float(state["unrealizedPnl"]),
            "last_update": state["updatedAt"],
            "available": True,
            "source": state["source"],
            "paperCapital": float(state["capital"]),
        }
