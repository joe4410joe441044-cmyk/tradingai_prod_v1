# -*- coding: utf-8 -*-

from .base import BaseClient
from backend.money_management.order_sizing import floor_contracts, number, SizingRejected

import requests
from requests.adapters import HTTPAdapter
import socket
import urllib3.util.connection as _urllib3_conn
import time
import tempfile
import uuid
import base64
import hmac
import hashlib
import json
import math
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlencode

from dotenv import load_dotenv
from backend.utils.log_buffer import logger, runtime_debug
from backend.market.kucoin_futures_public import to_kucoin_futures_symbol
from backend.runtime.runtime_state_contract import (
    PERMISSION_READ_ONLY,
    evaluate_trading_permission_authority,
    project_permission_contract,
)
from backend.execution.live_order_intent import (
    ACCEPTED,
    EXIT_PENDING,
    FILLED,
    FLAT_CONFIRMED,
    INTENT_RECORDED,
    IntentStore,
    NOT_FOUND_INCONCLUSIVE,
    PROTECTION_CONFIRMED,
    PROTECTION_PENDING,
    PROTECTION_UNKNOWN,
    PURPOSE_ENTRY,
    PURPOSE_EXIT,
    PURPOSE_PROTECTION,
    RECONCILIATION_REQUIRED,
    REJECTED,
    UNKNOWN_COMMIT,
    UNPROTECTED,
    format_stop_price,
    liquidation_risk_boundary,
    protective_stop_sides,
    quantize_stop_price,
)


DAILY_PNL_CACHE_TTL_SECONDS = 60
DAILY_PNL_MAX_PAGES = 100
DAILY_PNL_PAGE_SIZE = 50


# =====================================
# MARGIN MODE AUTHORITY
# =====================================
# The canonical TradingAI LIVE order contract requests ISOLATED margin.  The
# requested mode is an explicit single authority so the payload contract and
# the fail-closed preflight cannot drift apart.  The exchange's authoritative
# current symbol margin mode is read (GET only) from the KuCoin v2
# ``getMarginMode`` endpoint.  The flat v1 position placeholder marginMode
# must never be used as authority for the ENTRY comparison.
#
# For an existing position close the position itself is the authority: the
# reduceOnly close must use the actual position's margin mode (v1 position
# ``marginMode`` / ``crossMode``), falling back to the GET authority.  A close
# is never forced to ISOLATED and never falls back to a blind mode.

REQUESTED_MARGIN_MODE = "ISOLATED"
MARGIN_MODE_UNKNOWN = "UNKNOWN"
MARGIN_MODE_SOURCE = "KUCOIN_V2_POSITION_MARGIN_MODE"
MARGIN_MODE_AUTHORITY_ENDPOINT = "/api/v2/position/getMarginMode"
CANONICAL_MARGIN_MODES = ("ISOLATED", "CROSS")

# Canonical comparison reasons.  These are the only values the entry
# preflight may emit, so the operator-facing block reason is deterministic.
MARGIN_MODE_COMPATIBLE = "MARGIN_MODE_COMPATIBLE"
MARGIN_MODE_MISMATCH = "MARGIN_MODE_MISMATCH"
MARGIN_MODE_AUTHORITY_UNAVAILABLE = "MARGIN_MODE_AUTHORITY_UNAVAILABLE"

# Structurally absent symbol values.  ``None`` normalizes to the literal
# ``"NONE"`` through the legacy compatibility mapper, so the guard must reject
# the placeholder tokens as well as empty strings.  ``NOT AVAILABLE`` is the
# canonical Operation absent-symbol sentinel already used by the frontend
# (``operationPreparationModel.js``) and must be rejected by the backend too so
# a display placeholder can never be forwarded to an exchange authority read.
# None of these is a symbol.
ABSENT_SYMBOL_VALUES = frozenset(
    {"", "NONE", "NULL", "UNKNOWN", "NOT AVAILABLE"}
)


def normalize_kucoin_risk_ratio(value):
    """Convert KuCoin Classic Futures' account risk ratio to display percent.

    KuCoin defines cross-margin risk rate as a ratio and liquidates at 100%.
    The account-overview ``riskRatio`` is therefore normalized from ratio form
    (1.0 == the 100% liquidation threshold) to the percentage displayed by
    Account Status. Missing, malformed, negative, or non-finite input is
    unavailable rather than a fabricated zero.
    """

    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        ratio = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not ratio.is_finite() or ratio < 0:
        return None
    return float(ratio * Decimal("100"))


def account_status_total_pnl_today(realized_pnl_today, unrealized_pnl):
    """Today's net realized trading result plus current unrealized PnL.

    This is an Account Status snapshot metric, not a daily equity delta.  Both
    operands must be authoritative; a missing or malformed operand makes the
    result unavailable.
    """

    values = []
    for value in (realized_pnl_today, unrealized_pnl):
        if value is None or value == "" or isinstance(value, bool):
            return None
        try:
            normalized = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if not normalized.is_finite():
            return None
        values.append(normalized)
    return float(sum(values, Decimal("0")))


def utc_day_window(now):
    """Return the Account Status UTC-day half-open boundary in milliseconds."""

    if not isinstance(now, datetime) or now.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    observed = now.astimezone(timezone.utc)
    start = observed.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, observed, int(start.timestamp() * 1000), int(observed.timestamp() * 1000)


def normalize_kucoin_realized_pnl_today(items, *, start_ms, end_ms):
    """Normalize one complete Classic Futures UTC-day ledger snapshot.

    Official KuCoin Futures semantics define Realized PnL as net of trading
    fees and funding fees. Consequently ``RealisedPNL.amount`` is summed
    directly; the ledger's separate ``fee`` metadata is deliberately not
    subtracted a second time. Both Completed settlement periods and the
    current eight-hour Pending period are economically realized and included.
    Deposits, withdrawals, transfers, and all other cash movements are
    excluded. Duplicate page rows are counted once.
    """

    if not isinstance(items, (list, tuple)):
        raise ValueError("Futures ledger items required")
    if type(start_ms) is not int or type(end_ms) is not int or end_ms < start_ms:
        raise ValueError("invalid UTC-day window")

    total = Decimal("0")
    seen = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("malformed Futures ledger item")
        if str(item.get("type", "")).lower() != "realisedpnl":
            continue

        required = {"time", "amount", "status", "offset", "currency"}
        if not required.issubset(item):
            raise ValueError("incomplete RealisedPNL ledger item")
        if item.get("currency") != "USDT":
            raise ValueError("unexpected RealisedPNL currency")
        status = item.get("status")
        if status not in {"Completed", "Pending"}:
            raise ValueError("unknown RealisedPNL settlement status")
        try:
            occurred_ms = int(item.get("time"))
            amount = Decimal(str(item.get("amount")))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("invalid RealisedPNL ledger value") from None
        if not amount.is_finite():
            raise ValueError("invalid RealisedPNL ledger value")
        if occurred_ms < start_ms or occurred_ms > end_ms:
            continue

        offset = item.get("offset")
        identity = (
            ("COMPLETED", str(offset))
            if status == "Completed" and offset not in (None, "")
            else (
                "PENDING",
                str(item.get("remark") or ""),
                occurred_ms,
                str(amount),
            )
        )
        canonical = (
            occurred_ms,
            status,
            str(amount),
            str(item.get("remark") or ""),
            item.get("currency"),
        )
        previous = seen.get(identity)
        if previous is not None:
            if previous != canonical:
                raise ValueError("conflicting duplicate RealisedPNL ledger item")
            continue
        seen[identity] = canonical
        total += amount

    return float(total)


def _credential_fingerprint(api_key):
    """Non-reversible credential identity; the raw secret is never exposed."""

    if not api_key:
        return None
    digest = hashlib.sha256(str(api_key).encode("utf-8")).hexdigest()
    return "sha256:" + digest[:16]


def _response_permission_authority(data):
    """Extract an authoritative permission field if the response carries one.

    KuCoin Classic Futures ``account-overview`` does not publish the API key
    permission set.  This helper only returns a value when an explicit,
    response-owned field exists; a client-side or synthesized default never
    becomes authoritative.
    """

    if not isinstance(data, dict):
        return None, None
    for key in (
        "permission",
        "apiKeyPermission",
        "apiKeyPermissions",
        "permissions",
    ):
        if key not in data:
            continue
        value = data.get(key)
        if isinstance(value, (list, tuple, set)):
            values = {str(item).strip().upper() for item in value}
            if "TRADE" in values and "WITHDRAW" in values:
                return "TRADE_AND_WITHDRAW", key
            if "TRADE" in values:
                return "TRADE", key
            if "WITHDRAW" in values:
                return "WITHDRAW", key
            if "READ_ONLY" in values:
                return "READ_ONLY", key
            return None, key
        if isinstance(value, str) and value.strip():
            return value.strip().upper(), key
    return None, None


# =====================================
# LOAD ENV
# =====================================

load_dotenv()


class ForceIPv4Adapter(HTTPAdapter):

    def send(self, request, stream=False, timeout=None, verify=True,
             cert=None, proxies=None):

        original_allowed = _urllib3_conn.allowed_gai_family
        _urllib3_conn.allowed_gai_family = lambda: socket.AF_INET
        try:
            return super().send(
                request,
                stream=stream,
                timeout=timeout,
                verify=verify,
                cert=cert,
                proxies=proxies,
            )
        finally:
            _urllib3_conn.allowed_gai_family = original_allowed


class KucoinTradeClient(BaseClient):

    @staticmethod
    def credentials_present(
        api_key=None,
        api_secret=None,
        passphrase=None
    ):

        return bool(
            (api_key or os.getenv("KUCOIN_API_KEY"))
            and (api_secret or os.getenv("KUCOIN_API_SECRET"))
            and (passphrase or os.getenv("KUCOIN_API_PASSPHRASE"))
        )

    # =====================================
    # INIT
    # =====================================

    def __init__(
        self,
        api_key=None,
        api_secret=None,
        passphrase=None
    ):

        self.logger = logger

        # =====================================
        # ENV LOAD
        # =====================================

        self.api_key = (
            api_key or
            os.getenv("KUCOIN_API_KEY")
        )

        self.api_secret = (
            api_secret or
            os.getenv("KUCOIN_API_SECRET")
        )

        self.passphrase = (
            passphrase or
            os.getenv("KUCOIN_API_PASSPHRASE")
        )

        self.live_order_allowed = False

        self.live_block_reasons = [
            "LIVE_NOT_READY"
        ]

        # Latest exchange trading-permission evidence.  Missing/empty evidence
        # is never treated as verification.
        self.permission_contract = {}

        runtime_debug(
            "KuCoin credentials configured key=%s secret=%s passphrase=%s",
            bool(self.api_key),
            bool(self.api_secret),
            bool(self.passphrase),
        )

        if (
            not self.api_key or
            not self.api_secret or
            not self.passphrase
        ):

            raise Exception(
                "🚨 KUCOIN API KEY REQUIRED"
            )

        self.base_url = (
            "https://api-futures.kucoin.com"
        )

        self.session = requests.Session()
        self.session.mount("https://", ForceIPv4Adapter())
        self.session.mount("http://", ForceIPv4Adapter())
        self.runtime_submission_allowed = True
        self.order_intent_path = None
        self._live_order_intent_store = None
        self.require_durable_intent_store = False
        self._order_recovery_complete = False
        self.exchange_state_fresh = True
        self._daily_pnl_cache = None
        self._daily_pnl_cache_lock = threading.Lock()

    def credentials_ready(self):

        return bool(
            self.api_key
            and self.api_secret
            and self.passphrase
        )

    def private_get(self, endpoint, *, base_url=None, timeout=10):
        """Execute one authenticated GET with the existing KuCoin signer only."""
        if not isinstance(endpoint, str) or not endpoint.startswith("/api/"):
            raise ValueError("KuCoin private GET endpoint required")
        headers = self._headers("GET", endpoint, "")
        response = self.session.get(
            (base_url or self.base_url) + endpoint,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code") != "200000":
            raise RuntimeError("KUCOIN_PRIVATE_GET_FAILED")
        return payload.get("data")

    def get_margin_mode(self, symbol, timeout=10):
        """Read the authoritative KuCoin symbol margin mode (GET only).

        Uses the existing authenticated signer to call the v2
        ``getMarginMode`` endpoint.  The response is normalized to the
        canonical vocabulary ``ISOLATED`` / ``CROSS``.  Any transport,
        authorization, HTTP, malformed, missing, or unknown value is reported
        as unavailable rather than guessed, so the caller can fail closed.
        """

        normalized_symbol = self.normalize_symbol(symbol)

        # Fail closed WITHOUT any exchange request when the symbol is
        # structurally absent.  The legacy mapper turns ``None`` into the
        # literal ``"NONE"``; that placeholder must never reach KuCoin.
        if str(normalized_symbol or "").strip().upper() in ABSENT_SYMBOL_VALUES:
            return {
                "symbol": None,
                "marginMode": None,
                "available": False,
                "source": MARGIN_MODE_SOURCE,
                "reason": MARGIN_MODE_AUTHORITY_UNAVAILABLE,
                "updatedAt": time.time(),
            }

        endpoint = (
            MARGIN_MODE_AUTHORITY_ENDPOINT
            + "?"
            + urlencode({"symbol": normalized_symbol})
        )

        authority = {
            "symbol": normalized_symbol,
            "marginMode": None,
            "available": False,
            "source": MARGIN_MODE_SOURCE,
            "reason": None,
            "updatedAt": time.time(),
        }

        try:
            headers = self._headers("GET", endpoint, "")
            res = self.session.get(
                self.base_url + endpoint,
                headers=headers,
                timeout=timeout,
            )
        except Exception as e:
            authority["reason"] = "MARGIN_MODE_AUTHORITY_REQUEST_FAILED"
            runtime_debug(
                "KuCoin getMarginMode request failed symbol=%s error=%s",
                normalized_symbol,
                e,
            )
            return authority

        status_code = getattr(res, "status_code", None)

        try:
            status_code = (
                int(status_code)
                if status_code is not None
                else None
            )
        except (TypeError, ValueError):
            status_code = None

        if status_code is not None and status_code >= 400:
            authority["reason"] = (
                "MARGIN_MODE_AUTHORITY_HTTP_%s"
                % status_code
            )
            return authority

        try:
            payload = res.json()
        except Exception as e:
            authority["reason"] = "MARGIN_MODE_AUTHORITY_RESPONSE_FAILED"
            runtime_debug(
                "KuCoin getMarginMode malformed response symbol=%s error=%s",
                normalized_symbol,
                e,
            )
            return authority

        if not isinstance(payload, dict) or payload.get("code") != "200000":
            authority["reason"] = "MARGIN_MODE_AUTHORITY_RESPONSE_FAILED"
            return authority

        data = payload.get("data")

        if not isinstance(data, dict):
            authority["reason"] = "MARGIN_MODE_AUTHORITY_RESPONSE_FAILED"
            return authority

        raw_mode = data.get("marginMode")

        if not isinstance(raw_mode, str) or not raw_mode.strip():
            authority["reason"] = "MARGIN_MODE_AUTHORITY_MISSING"
            return authority

        mode = raw_mode.strip().upper()

        if mode not in CANONICAL_MARGIN_MODES:
            authority["reason"] = "MARGIN_MODE_AUTHORITY_UNKNOWN"
            return authority

        authority["marginMode"] = mode
        authority["available"] = True
        return authority

    def margin_mode_authority(self, symbol, timeout=10):
        """Canonical required-vs-actual margin mode comparison (GET only).

        This is the single margin-mode authority for TradingAI.  It combines
        the exchange GET read with the canonical requested mode and emits one
        deterministic comparison contract:

        * ``known``       - an authoritative exchange mode was obtained
        * ``requiredMode``- canonical TradingAI requested mode (ISOLATED)
        * ``actualMode``  - authoritative exchange mode, or ``UNKNOWN``
        * ``compatible``  - required == actual
        * ``reason``      - ``MARGIN_MODE_COMPATIBLE`` | ``MARGIN_MODE_MISMATCH``
                            | ``MARGIN_MODE_AUTHORITY_UNAVAILABLE``
        * ``source`` / ``updatedAt`` / ``authorityReason`` - provenance

        Never guesses an unknown mode and never rewrites the requested mode.
        """

        read = self.get_margin_mode(symbol, timeout=timeout)
        known = bool(read.get("available"))
        actual = (
            read.get("marginMode")
            if known
            else MARGIN_MODE_UNKNOWN
        )

        if not known:
            reason = MARGIN_MODE_AUTHORITY_UNAVAILABLE
            compatible = False
        elif actual == REQUESTED_MARGIN_MODE:
            reason = MARGIN_MODE_COMPATIBLE
            compatible = True
        else:
            reason = MARGIN_MODE_MISMATCH
            compatible = False

        return {
            "known": known,
            "requiredMode": REQUESTED_MARGIN_MODE,
            "actualMode": actual,
            "compatible": compatible,
            "reason": reason,
            "source": read.get("source", MARGIN_MODE_SOURCE),
            "updatedAt": read.get("updatedAt"),
            "symbol": read.get("symbol"),
            "authorityReason": read.get("reason"),
        }

    def margin_mode_entry_gate(self, symbol, timeout=10):
        """Fail-closed margin mode preflight for a LIVE entry.

        Returns ``None`` when the authoritative exchange margin mode equals the
        requested canonical mode.  Otherwise returns a sanitized block
        descriptor with a canonical reason and diagnostic fields:

        * ``MARGIN_MODE_MISMATCH`` when exchange differs from requested
        * ``MARGIN_MODE_AUTHORITY_UNAVAILABLE`` when the exchange mode cannot
          be authoritatively determined (transport / auth / malformed /
          missing / unknown).
        """

        authority = self.margin_mode_authority(symbol, timeout=timeout)
        requested = authority["requiredMode"]
        exchange_mode = authority["actualMode"]

        if not authority["known"]:
            return {
                "reason": MARGIN_MODE_AUTHORITY_UNAVAILABLE,
                "known": False,
                "compatible": False,
                "requestedMarginMode": requested,
                "exchangeMarginMode": MARGIN_MODE_UNKNOWN,
                "marginModeSource": authority["source"],
                "authorityReason": authority.get("authorityReason"),
                "updatedAt": authority.get("updatedAt"),
            }

        if not authority["compatible"]:
            return {
                "reason": MARGIN_MODE_MISMATCH,
                "known": True,
                "compatible": False,
                "requestedMarginMode": requested,
                "exchangeMarginMode": exchange_mode,
                "marginModeSource": authority["source"],
                "authorityReason": None,
                "updatedAt": authority.get("updatedAt"),
            }

        return None

    def position_margin_mode(self, position):
        """Extract a canonical margin mode from a KuCoin v1 position object.

        The v1 position carries the actual position margin mode either as an
        explicit ``marginMode`` string or as the legacy ``crossMode`` boolean
        (true == CROSS).  Returns ``None`` when the value is absent or not one
        of the canonical modes.  This is the authority used for a close.
        """

        if not isinstance(position, dict):
            return None

        raw_mode = position.get("marginMode")

        if isinstance(raw_mode, str):
            candidate = raw_mode.strip().upper()
            if candidate in CANONICAL_MARGIN_MODES:
                return candidate

        cross_mode = position.get("crossMode")

        if isinstance(cross_mode, bool):
            return "CROSS" if cross_mode else "ISOLATED"

        return None

    def close_margin_mode(self, symbol, position=None, timeout=10):
        """Resolve the authoritative margin mode for a reduceOnly close.

        Prefers the existing position's own exchange-reported mode (the
        position is the authority for its own close), then falls back to the
        GET-only symbol authority.  Returns ``None`` when the mode cannot be
        determined so the caller can fail closed instead of guessing a mode.
        """

        raw_position = None
        if isinstance(position, dict):
            raw_position = position.get("raw")
            if not isinstance(raw_position, dict):
                raw_position = position

        position_mode = self.position_margin_mode(raw_position)

        if position_mode is not None:
            return position_mode

        read = self.get_margin_mode(symbol, timeout=timeout)
        if read.get("available"):
            return read.get("marginMode")

        return None

    def get_deposit_history(self, *, start_at, end_at, current_page=1,
                            page_size=50, currency="USDT", timeout=10):
        query = urlencode({"currency": currency, "startAt": int(start_at),
                           "endAt": int(end_at), "currentPage": int(current_page),
                           "pageSize": int(page_size)})
        return self.private_get(
            "/api/v1/deposits?" + query,
            base_url="https://api.kucoin.com", timeout=timeout,
        )

    def get_withdrawal_history(self, *, start_at, end_at, current_page=1,
                               page_size=50, currency="USDT", timeout=10):
        query = urlencode({"currency": currency, "startAt": int(start_at),
                           "endAt": int(end_at), "currentPage": int(current_page),
                           "pageSize": int(page_size)})
        return self.private_get(
            "/api/ua/v1/asset/withdrawal/history?" + query,
            base_url="https://api.kucoin.com", timeout=timeout,
        )

    def get_futures_transaction_history(self, *, start_at, end_at, offset=None,
                                        max_count=50, currency="USDT", timeout=10):
        start_at, end_at = int(start_at), int(end_at)
        if end_at < start_at or end_at - start_at > 86_400_000:
            raise ValueError("Futures transaction history range must not exceed one day")
        params = {"currency": currency, "startAt": int(start_at),
                  "endAt": int(end_at), "maxCount": int(max_count),
                  "forward": "false"}
        if offset is not None:
            params["offset"] = str(offset)
        return self.private_get(
            "/api/v1/transaction-history?" + urlencode(params), timeout=timeout,
        )

    def get_realized_pnl_today(self, *, now=None, cache_ttl_seconds=DAILY_PNL_CACHE_TTL_SECONDS):
        """Return a complete, cached, GET-only UTC-day realized-PnL snapshot."""

        observed = now or datetime.now(timezone.utc)
        start, observed, start_ms, end_ms = utc_day_window(observed)
        if cache_ttl_seconds < 0:
            raise ValueError("cache TTL must be non-negative")
        cache_key = start_ms
        monotonic_now = time.monotonic()

        with self._daily_pnl_cache_lock:
            cached = self._daily_pnl_cache
            if (
                cached
                and cached["dayStartMs"] == cache_key
                and monotonic_now - cached["cachedAt"] < cache_ttl_seconds
            ):
                return dict(cached["result"])

            # The empty interval at the exact UTC boundary is mathematically
            # complete without an exchange request.
            if end_ms == start_ms:
                value = 0.0
            else:
                rows = []
                offset = None
                seen_offsets = set()
                for _ in range(DAILY_PNL_MAX_PAGES):
                    page = self.get_futures_transaction_history(
                        start_at=start_ms,
                        end_at=end_ms,
                        offset=offset,
                        max_count=DAILY_PNL_PAGE_SIZE,
                    )
                    if not isinstance(page, dict) or set(page) != {"dataList", "hasMore"}:
                        raise ValueError("Futures ledger pagination contract invalid")
                    page_rows = page.get("dataList")
                    if not isinstance(page_rows, list) or type(page.get("hasMore")) is not bool:
                        raise ValueError("Futures ledger pagination contract invalid")
                    rows.extend(page_rows)
                    if not page["hasMore"]:
                        break
                    offsets = []
                    for item in page_rows:
                        if not isinstance(item, dict) or isinstance(item.get("offset"), bool):
                            raise ValueError("Futures ledger pagination contract invalid")
                        try:
                            candidate_offset = int(item.get("offset"))
                            # KuCoin emits the current settlement-period Pending
                            # row with the sentinel offset -1. The official
                            # pagination example advances with the Completed
                            # row offset, so the sentinel is never a cursor.
                            if item.get("status") != "Pending" and candidate_offset >= 0:
                                offsets.append(candidate_offset)
                        except (TypeError, ValueError):
                            raise ValueError("Futures ledger pagination contract invalid") from None
                    if not offsets:
                        raise ValueError("Futures ledger pagination inconsistency")
                    next_offset = min(offsets)
                    if next_offset in seen_offsets or next_offset == offset:
                        raise ValueError("Futures ledger pagination cycle")
                    seen_offsets.add(next_offset)
                    offset = next_offset
                else:
                    raise ValueError("Futures ledger pagination limit exceeded")
                value = normalize_kucoin_realized_pnl_today(
                    rows,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )

            result = {
                "value": value,
                "source": "KUCOIN_FUTURES_REALISED_PNL_LEDGER",
                "dayStart": start.isoformat().replace("+00:00", "Z"),
                "observedAt": observed.isoformat().replace("+00:00", "Z"),
                "timezone": "UTC",
                "complete": True,
            }
            self._daily_pnl_cache = {
                "dayStartMs": cache_key,
                "cachedAt": monotonic_now,
                "result": dict(result),
            }
            return result

    def current_credential_fingerprint(self):
        """Non-reversible fingerprint of the credential in use right now."""

        return _credential_fingerprint(self.api_key)

    def trading_permission_authority(self, *, now=None):
        """Re-evaluate the latest trading-permission evidence fail-closed."""

        return evaluate_trading_permission_authority(
            self.permission_contract,
            expected_venue="KUCOIN_FUTURES",
            expected_credential_fingerprint=(
                self.current_credential_fingerprint()
            ),
            now=now,
        )

    def set_live_order_gate(
        self,
        allowed,
        reasons=None
    ):

        self.live_order_allowed = bool(allowed)
        self.live_block_reasons = list(
            reasons
            or (
                []
                if allowed
                else ["LIVE_NOT_READY"]
            )
        )

    # =========================
    # SYMBOL
    # =========================

    def normalize_symbol(
        self,
        symbol: str
    ) -> str:

        mapped = to_kucoin_futures_symbol(symbol)

        runtime_debug(
            "KuCoin trade symbol map '%s' -> '%s'",
            symbol,
            mapped,
        )

        return mapped

    # =========================
    # SIGN
    # =========================

    def _headers(
        self,
        method,
        endpoint,
        body=""
    ):

        now = str(
            int(time.time() * 1000)
        )

        str_to_sign = (
            now + method + endpoint + body
        )

        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                str_to_sign.encode(),
                hashlib.sha256
            ).digest()
        ).decode()

        passphrase = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                self.passphrase.encode(),
                hashlib.sha256
            ).digest()
        ).decode()

        return {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": now,
            "KC-API-PASSPHRASE": passphrase,
            "KC-API-KEY-VERSION": "3",
            "Content-Type": "application/json"
        }

    # =========================
    # BALANCE
    # =========================

    def get_balance(self):

        overview = self.get_account_overview()

        balance = overview.get("balance")

        runtime_debug("KuCoin parsed balance=%s", balance)

        return float(balance or 0.0)

    def get_account_overview(
        self,
        currency="USDT",
        timeout=10,
    ):

        endpoint = (
            "/api/v1/account-overview"
            f"?currency={currency}"
        )

        headers = self._headers(
            "GET",
            endpoint,
            ""
        )

        res = self.session.get(
            self.base_url + endpoint,
            headers=headers,
            timeout=timeout,
        )

        data = res.json()

        runtime_debug("KuCoin raw balance response=%s", data)

        if data.get("code") != "200000":

            raise Exception(
                f"KUCOIN ERROR: {data}"
            )

        d = data.get(
            "data",
            {}
        )

        def as_float(*keys):
            for key in keys:
                if key in d and d.get(key) not in [None, ""]:
                    return float(d.get(key, 0) or 0)
            return None

        # =====================================
        # FUTURES ACCOUNT EQUITY
        # =====================================

        equity = as_float(
            "accountEquity",
            "marginBalance",
            "balance",
        )

        # =====================================
        # AVAILABLE BALANCE
        # =====================================

        available_balance = as_float(
            "availableBalance",
            "available_balance",
        )

        # =====================================
        # MARGIN BALANCE FALLBACK
        # =====================================

        # Official Classic Futures contract:
        # accountEquity = marginBalance + unrealisedPNL.  marginBalance is
        # therefore the pre-unrealized Futures account balance and the
        # authoritative wallet-equivalent for Account Status.  It must remain
        # unavailable when the direct exchange field is absent.
        margin_balance = as_float("marginBalance")
        unrealized_pnl = as_float(
            "unrealisedPNL",
            "unrealizedPnl",
            "unrealisedPnl",
            "unrealizedPNL",
        )
        position_margin = as_float(
            "positionMargin",
            "position_margin",
        )
        order_margin = as_float(
            "orderMargin",
            "order_margin",
        )
        available_margin = as_float(
            "availableMargin",
            "available_margin",
        )
        risk_ratio_raw = d.get("riskRatio")
        margin_ratio = normalize_kucoin_risk_ratio(risk_ratio_raw)
        # Margin in use is authorised by KuCoin's own decomposition of the
        # cross-margin account: occupied margin = margin held for open
        # positions (positionMargin) + margin reserved for open orders
        # (orderMargin). Neither component is optional; if either is absent
        # the occupied-margin figure is treated as unknown (None), never a
        # fabricated zero.
        margin_used = (
            (position_margin + order_margin)
            if position_margin is not None and order_margin is not None
            else None
        )
        balance = (
            equity
            if equity is not None
            else (
                margin_balance
                if margin_balance is not None
                else available_balance
            )
        )

        verified_permission, permission_source_key = (
            _response_permission_authority(d)
        )
        permission_contract = project_permission_contract(
            claimed_permission=PERMISSION_READ_ONLY,
            verified_permission=verified_permission,
            verification_source=(
                "KUCOIN_ACCOUNT_RESPONSE:" + permission_source_key
                if verified_permission and permission_source_key
                else "NOT_VERIFIED"
            ),
            verified_at=(
                time.time() if verified_permission else None
            ),
            credential_fingerprint=_credential_fingerprint(self.api_key),
            authenticated=True,
            venue="KUCOIN_FUTURES",
            account_id=d.get("accountId") or d.get("uid"),
        )
        # Retain the latest evidence on the client so every submission
        # boundary can re-check permission freshness/binding, even when a
        # caller bypasses the engine readiness projection.
        self.permission_contract = dict(permission_contract)

        overview = {
            "source": "KUCOIN_FUTURES_READ_ONLY",
            "accountType": "KUCOIN_FUTURES",
            "currency": d.get("currency", currency),
            "balance": (
                float(balance)
                if balance is not None
                else None
            ),
            "equity": (
                float(equity)
                if equity is not None
                else (
                    float(balance)
                    if balance is not None
                    else None
                )
            ),
            "availableBalance": (
                float(available_balance)
                if available_balance is not None
                else None
            ),
            "marginBalance": (
                float(margin_balance)
                if margin_balance is not None
                else None
            ),
            "walletBalance": (
                float(margin_balance)
                if margin_balance is not None
                else None
            ),
            "unrealizedPnl": (
                float(unrealized_pnl)
                if unrealized_pnl is not None
                else None
            ),
            "positionMargin": (
                float(position_margin)
                if position_margin is not None
                else None
            ),
            "orderMargin": (
                float(order_margin)
                if order_margin is not None
                else None
            ),
            "availableMargin": (
                float(available_margin)
                if available_margin is not None
                else None
            ),
            "marginUsed": (
                float(margin_used)
                if margin_used is not None
                else None
            ),
            "riskRatio": risk_ratio_raw,
            "marginRatio": margin_ratio,
            "exchangeAuth": "VERIFIED",
            "exchangeConnection": "CONNECTED",
            "apiKeyStatus": "VERIFIED",
            # Backward-compatible claimed value.  ``permissionVerified`` below
            # is the only proof field; the claim must not be read as proof.
            "permission": PERMISSION_READ_ONLY,
            "permissionClaimed": permission_contract["claimedPermission"],
            "permissionVerified": (
                permission_contract["permissionStatus"] == "VERIFIED"
            ),
            "permissionStatus": permission_contract["permissionStatus"],
            "permissionVerifiedPermission": (
                permission_contract["verifiedPermission"]
            ),
            "permissionVerificationSource": (
                permission_contract["verificationSource"]
            ),
            "permissionVerifiedAt": permission_contract["verifiedAt"],
            "permissionExpiresAt": permission_contract.get("expiresAt"),
            "permissionVenue": permission_contract.get("venue"),
            "permissionAccountId": permission_contract.get("accountId"),
            "credentialFingerprint": (
                permission_contract["credentialFingerprint"]
            ),
            "permissionContract": permission_contract,
            "lastSync": time.time(),
        }

        runtime_debug("KuCoin parsed account overview=%s", overview)

        return overview

    # =========================
    # POSITIONS
    # =========================

    def get_positions(
        self,
        symbol=None,
        timeout=10,
    ):

        endpoint = "/api/v1/positions"

        headers = self._headers(
            "GET",
            endpoint
        )

        res = self.session.get(
            self.base_url + endpoint,
            headers=headers,
            timeout=timeout,
        )

        data = res.json()

        if data.get("code") != "200000":
            raise Exception(
                f"KUCOIN ERROR: {data}"
            )

        positions = data["data"]

        # Display-only copy of this existing response, before legacy selection.
        # The execution return contract below remains unchanged.
        try:
            from backend.runtime.current_position_view import kucoin_position_observation
            self.account_position_observation = kucoin_position_observation(positions, time.time())
        except Exception:
            # Display metadata must never block the existing execution reader.
            self.account_position_observation = {"positions": None, "sourceUpdatedAt": None}

        active = []

        for p in positions:

            size = float(
                p.get("currentQty", 0)
            )

            if size != 0:

                active.append({
                    "symbol": p["symbol"],
                    "qty": abs(size),
                    "side": (
                        "BUY"
                        if size > 0
                        else "SELL"
                    ),
                    "entry_price": float(
                        p.get(
                            "avgEntryPrice",
                            0
                        )
                    )
                })

        if symbol:

            symbol = self.normalize_symbol(symbol)

            active = [
                p for p in active
                if p["symbol"] == symbol
            ]

        return (
            active[0]
            if active
            else None
        )

    def get_position_authority_snapshot(self, timeout=10):
        """Return an explicit, timestamped shape for Live authority checks.

        The legacy ``get_positions`` API uses ``None`` for a successfully
        verified flat account.  Keep that compatibility surface unchanged,
        while preventing generic consumers from confusing that value with a
        missing or malformed response.
        """
        position = self.get_positions(timeout=timeout)
        evaluated_at = time.time()
        if position is None:
            return {"qty": 0, "evaluatedAt": evaluated_at}
        if isinstance(position, dict):
            return {**position, "evaluatedAt": evaluated_at}
        return position

    def get_current_position(
        self,
        symbol,
        timeout=10,
    ):

        raw_symbol = (
            str(symbol).strip()
            if symbol is not None
            else ""
        )
        normalized_symbol = (
            self.normalize_symbol(raw_symbol)
            if raw_symbol
            else None
        )

        def response(
            success,
            found=False,
            error_code=None,
            error=None,
            raw=None,
            raw_quantity=None,
            side=None,
            quantity=0.0,
            signed_quantity=0.0,
            entry_price=None,
        ):
            result = {
                "success": success,
                "exchange": "kucoin",
                "source": "kucoin",
                "found": found,
                "symbol": normalized_symbol,
                "exchange_symbol": normalized_symbol,
                "side": side,
                "quantity": quantity,
                "signed_quantity": signed_quantity,
                "raw_quantity": raw_quantity,
                "entry_price": entry_price,
                "raw": raw,
                "error_code": error_code,
                "error": error,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin current position result=%s", result)

            return result

        if not normalized_symbol:
            return response(
                False,
                error_code="INVALID_SYMBOL",
                error="symbol is required",
            )

        endpoint = "/api/v1/positions"

        try:
            headers = self._headers(
                "GET",
                endpoint
            )

            res = self.session.get(
                self.base_url + endpoint,
                headers=headers,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as e:
            return response(
                False,
                error_code="TIMEOUT",
                error=str(e),
            )
        except requests.exceptions.RequestException as e:
            return response(
                False,
                error_code="API_ERROR",
                error=str(e),
            )
        except Exception as e:
            return response(
                False,
                error_code="API_ERROR",
                error=str(e),
            )

        status_code = getattr(
            res,
            "status_code",
            None
        )

        try:
            status_code = (
                int(status_code)
                if status_code is not None
                else None
            )
        except (TypeError, ValueError):
            status_code = None

        if status_code in [401, 403]:
            return response(
                False,
                error_code="AUTH_ERROR",
                error=f"HTTP {status_code}",
            )

        if status_code is not None and status_code >= 400:
            return response(
                False,
                error_code="API_ERROR",
                error=f"HTTP {status_code}",
            )

        try:
            data = res.json()
        except Exception as e:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error=str(e),
            )

        if not isinstance(data, dict):
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="response is not a dict",
                raw=data,
            )

        if "code" not in data:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="missing code",
                raw=data,
            )

        if data.get("code") != "200000":
            return response(
                False,
                error_code="API_ERROR",
                error=str(data),
                raw=data,
            )

        if "data" not in data:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="missing data",
                raw=data,
            )

        positions = data.get("data")

        if not isinstance(positions, list):
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="data is not a list",
                raw=data,
            )

        if not positions:
            return response(
                True,
                found=False,
            )

        matches = []

        for item in positions:
            if not isinstance(item, dict):
                return response(
                    False,
                    error_code="MALFORMED_RESPONSE",
                    error="position item is not a dict",
                    raw=item,
                )

            if "symbol" not in item:
                return response(
                    False,
                    error_code="MALFORMED_RESPONSE",
                    error="missing symbol",
                    raw=item,
                )

            raw_item_symbol = item.get("symbol")

            if raw_item_symbol is None:
                return response(
                    False,
                    error_code="MALFORMED_RESPONSE",
                    error="invalid symbol",
                    raw=item,
                )

            item_symbol = str(
                raw_item_symbol
            ).strip().upper()

            if not item_symbol:
                return response(
                    False,
                    error_code="MALFORMED_RESPONSE",
                    error="invalid symbol",
                    raw=item,
                )

            if item_symbol == normalized_symbol:
                matches.append(item)

        if not matches:
            return response(
                True,
                found=False,
            )

        if len(matches) > 1:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="multiple positions for symbol",
                raw=matches,
            )

        position = matches[0]

        if "currentQty" not in position:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="missing currentQty",
                raw=position,
            )

        raw_quantity = position.get("currentQty")

        if isinstance(raw_quantity, bool):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        if raw_quantity is None:
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        if isinstance(raw_quantity, str) and not raw_quantity.strip():
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        try:
            signed_quantity = float(raw_quantity)
        except (TypeError, ValueError):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        if not math.isfinite(signed_quantity):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid currentQty",
                raw=position,
                raw_quantity=raw_quantity,
            )

        if signed_quantity == 0:
            return response(
                True,
                found=False,
                raw=position,
                raw_quantity=raw_quantity,
                signed_quantity=0.0,
                quantity=0.0,
            )

        entry_price = None

        if position.get("avgEntryPrice") not in [None, ""]:
            try:
                parsed_entry = float(
                    position.get("avgEntryPrice")
                )

                if math.isfinite(parsed_entry):
                    entry_price = parsed_entry
            except (TypeError, ValueError):
                entry_price = None

        side = (
            "long"
            if signed_quantity > 0
            else "short"
        )

        return response(
            True,
            found=True,
            raw=position,
            raw_quantity=raw_quantity,
            side=side,
            quantity=abs(signed_quantity),
            signed_quantity=signed_quantity,
            entry_price=entry_price,
        )

    def flatten_current_position(
        self,
        symbol,
        timeout=10,
    ):

        def response(
            success,
            skipped=False,
            accepted=False,
            confirmed=False,
            closed=False,
            error_code=None,
            error=None,
            normalized_symbol=None,
            side=None,
            size=0,
            order_id=None,
            initial_position=None,
            final_position=None,
            raw_order=None,
        ):
            result = {
                "success": success,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "skipped": skipped,
                "accepted": accepted,
                "confirmed": confirmed,
                "closed": closed,
                "side": side,
                "size": size,
                "order_id": order_id,
                "initial_position": initial_position,
                "final_position": final_position,
                "raw_order": raw_order,
                "error_code": error_code,
                "error": error,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin flatten current position result=%s", result)

            return result

        initial = self.get_current_position(
            symbol,
            timeout=timeout,
        )

        normalized_symbol = (
            initial.get("exchange_symbol")
            or initial.get("symbol")
            if isinstance(initial, dict)
            else None
        )

        if not isinstance(initial, dict) or not initial.get("success"):
            return response(
                False,
                error_code=(
                    initial.get("error_code")
                    if isinstance(initial, dict)
                    else "POSITION_CHECK_FAILED"
                ),
                error=(
                    initial.get("error")
                    if isinstance(initial, dict)
                    else "position check failed"
                ),
                normalized_symbol=normalized_symbol,
                initial_position=initial,
            )

        if not initial.get("found"):
            return response(
                True,
                skipped=True,
                confirmed=True,
                normalized_symbol=normalized_symbol,
                initial_position=initial,
                final_position=initial,
            )

        position_side = initial.get("side")

        if position_side == "long":
            close_side = "sell"
        elif position_side == "short":
            close_side = "buy"
        else:
            return response(
                False,
                error_code="MALFORMED_POSITION",
                error="invalid position side",
                normalized_symbol=normalized_symbol,
                initial_position=initial,
            )

        raw_size = initial.get("quantity")

        if isinstance(raw_size, bool) or raw_size in [None, ""]:
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid position quantity",
                normalized_symbol=normalized_symbol,
                initial_position=initial,
                side=close_side,
            )

        try:
            size_value = float(raw_size)
        except (TypeError, ValueError):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid position quantity",
                normalized_symbol=normalized_symbol,
                initial_position=initial,
                side=close_side,
            )

        if (
            not math.isfinite(size_value)
            or size_value <= 0
            or not size_value.is_integer()
        ):
            return response(
                False,
                error_code="INVALID_QUANTITY",
                error="invalid position quantity",
                normalized_symbol=normalized_symbol,
                initial_position=initial,
                side=close_side,
            )

        size = int(size_value)
        endpoint = "/api/v1/orders"

        # =====================================
        # CLOSE MARGIN MODE AUTHORITY (exit safety)
        # =====================================
        # ENTRY safety and EXIT safety are not identical.  A new entry is
        # blocked on a margin-mode mismatch, but an existing real position must
        # still be closable.  The reduceOnly close therefore uses the actual
        # position's own margin mode (or the GET-only symbol authority) instead
        # of blindly forcing ISOLATED.  If the mode cannot be deterministically
        # resolved, fail closed and submit no order rather than risk an
        # incompatible close.
        close_margin_mode = self.close_margin_mode(
            normalized_symbol,
            initial,
            timeout=timeout,
        )

        if close_margin_mode is None:
            return response(
                False,
                error_code=MARGIN_MODE_AUTHORITY_UNAVAILABLE,
                error="close margin mode authority unavailable",
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
            )

        # ReduceOnly close intentionally carries no order-level leverage.
        # KuCoin Futures Add Order contract: `leverage` is "Optional for type
        # is 'isolated margin' order ... If you are to close the position, or
        # add 'cross margin' order, this parameter is not required."  Required
        # fields are clientOid/symbol/side.  A reduceOnly close applies the
        # existing position leverage, so hard-coding 10 here was both
        # unnecessary and an unauthorized leverage authority.
        submission = self.submit_bounded_order(
            purpose=PURPOSE_EXIT,
            symbol=normalized_symbol,
            side=close_side,
            size=size,
            timeout=timeout,
            body_fields={
                "symbol": normalized_symbol,
                "side": close_side,
                "type": "market",
                "size": str(size),
                "reduceOnly": True,
                "marginMode": close_margin_mode,
            },
        )
        if submission.get("submit") is not True:
            return response(
                False,
                error_code=self._live_close_error_code(submission),
                error=submission.get("reason"),
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
                raw_order=submission.get("raw"),
            )
        raw_order = submission.get("raw")
        order_id = submission.get("orderId") or ""
        if not order_id:
            return response(
                False,
                error_code="MALFORMED_RESPONSE",
                error="missing orderId",
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                initial_position=initial,
                raw_order=raw_order,
            )
        final = self.get_current_position(
            normalized_symbol,
            timeout=timeout,
        )
        if not isinstance(final, dict) or not final.get("success"):
            self.confirm_exchange_flat(submission.get("intentId"), None)
            post_error_code = (
                final.get("error_code")
                if isinstance(final, dict)
                else "FAILED"
            )
            return response(
                False,
                accepted=True,
                confirmed=False,
                error_code=f"POST_CHECK_{post_error_code or 'FAILED'}",
                error=(
                    final.get("error")
                    if isinstance(final, dict)
                    else "post-check failed"
                ),
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                order_id=order_id,
                initial_position=initial,
                final_position=final,
                raw_order=raw_order,
            )
        if final.get("found"):
            self.confirm_exchange_flat(submission.get("intentId"), True)
            return response(
                False,
                accepted=True,
                confirmed=False,
                error_code="POSITION_REMAINS",
                error="position remains after flatten order",
                normalized_symbol=normalized_symbol,
                side=close_side,
                size=size,
                order_id=order_id,
                initial_position=initial,
                final_position=final,
                raw_order=raw_order,
            )
        self.confirm_exchange_flat(submission.get("intentId"), False)
        return response(
            True,
            accepted=True,
            confirmed=True,
            closed=True,
            normalized_symbol=normalized_symbol,
            side=close_side,
            size=size,
            order_id=order_id,
            initial_position=initial,
            final_position=final,
            raw_order=raw_order,
        )

    # =========================
    # PRICE
    # =========================

    def get_open_orders(
        self,
        symbol=None
    ):

        normalized_symbol = (
            self.normalize_symbol(symbol)
            if symbol
            else None
        )
        orders = []
        raw_pages = []
        current_page = 1
        total_page = 1
        page_size = 100

        try:

            while current_page <= total_page:

                params = {
                    "status": "active",
                    "currentPage": current_page,
                    "pageSize": page_size,
                }

                if normalized_symbol:
                    params["symbol"] = normalized_symbol

                endpoint = (
                    "/api/v1/orders?"
                    + urlencode(params)
                )

                headers = self._headers(
                    "GET",
                    endpoint
                )

                res = self.session.get(
                    self.base_url + endpoint,
                    headers=headers,
                    timeout=10,
                )

                data = res.json()
                raw_pages.append(data)

                if data.get("code") != "200000":
                    return {
                        "success": False,
                        "exchange": "kucoin",
                        "symbol": normalized_symbol,
                        "orders": [],
                        "count": 0,
                        "error": str(data),
                        "raw": data,
                        "timestamp": time.time(),
                    }

                payload = data.get(
                    "data",
                    {}
                )
                items = (
                    payload
                    if isinstance(payload, list)
                    else payload.get("items", [])
                )

                for item in items or []:
                    orders.append(
                        self._normalize_open_order(
                            item
                        )
                    )

                if not isinstance(payload, dict):
                    break

                total_page = int(
                    payload.get("totalPage")
                    or payload.get("total_page")
                    or current_page
                    or 1
                )
                current_page = int(
                    payload.get("currentPage")
                    or payload.get("current_page")
                    or current_page
                    or 1
                )

                if current_page >= total_page:
                    break

                current_page += 1

            result = {
                "success": True,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "orders": orders,
                "count": len(orders),
                "raw": (
                    raw_pages[0]
                    if len(raw_pages) == 1
                    else {"pages": raw_pages}
                ),
                "pagination": {
                    "pagesFetched": len(raw_pages),
                    "pageSize": page_size,
                    "totalPage": total_page,
                },
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin open orders result=%s", result)

            return result

        except Exception as e:

            self.logger.exception("KUCOIN OPEN ORDERS EXCEPTION")

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "orders": [],
                "count": 0,
                "error": str(e),
                "raw": (
                    raw_pages[-1]
                    if raw_pages
                    else None
                ),
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin open orders result=%s", result)

            return result

    @staticmethod
    def _normalize_open_order(order):

        def as_float(value):
            if value in [None, ""]:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        side = order.get("side")

        return {
            "order_id": (
                order.get("id")
                or order.get("orderId")
            ),
            "symbol": order.get("symbol"),
            "side": (
                str(side).upper()
                if side
                else None
            ),
            "type": (
                order.get("type")
                or order.get("orderType")
            ),
            "price": as_float(order.get("price")),
            "size": as_float(
                order.get("size")
                or order.get("qty")
            ),
            "status": order.get("status"),
            "raw": order,
        }

    def cancel_order(
        self,
        order_id,
        symbol=None
    ):

        normalized_symbol = (
            self.normalize_symbol(symbol)
            if symbol
            else None
        )
        normalized_order_id = (
            str(order_id).strip()
            if order_id is not None
            else ""
        )

        if not normalized_order_id:

            result = {
                "success": False,
                "exchange": "kucoin",
                "order_id": None,
                "symbol": normalized_symbol,
                "cancelled": False,
                "error": "INVALID_ORDER_ID",
                "raw": None,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel order result=%s", result)

            return result

        endpoint = (
            "/api/v1/orders/"
            + quote(normalized_order_id, safe="")
        )
        raw = None

        try:

            headers = self._headers(
                "DELETE",
                endpoint
            )

            res = self.session.delete(
                self.base_url + endpoint,
                headers=headers,
                timeout=10,
            )

            raw = res.json()

            if raw.get("code") != "200000":
                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "order_id": normalized_order_id,
                    "symbol": normalized_symbol,
                    "cancelled": False,
                    "error": str(raw),
                    "raw": raw,
                    "timestamp": time.time(),
                }

                runtime_debug("KuCoin cancel order result=%s", result)

                return result

            result = {
                "success": True,
                "exchange": "kucoin",
                "order_id": normalized_order_id,
                "symbol": normalized_symbol,
                "cancelled": True,
                "raw": raw,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel order result=%s", result)

            return result

        except Exception as e:

            self.logger.exception("KUCOIN CANCEL ORDER EXCEPTION")

            result = {
                "success": False,
                "exchange": "kucoin",
                "order_id": normalized_order_id,
                "symbol": normalized_symbol,
                "cancelled": False,
                "error": str(e),
                "raw": raw,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel order result=%s", result)

            return result

    def cancel_all_orders(
        self,
        symbol
    ):

        raw_symbol = (
            str(symbol).strip()
            if symbol is not None
            else ""
        )

        if not raw_symbol:

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": None,
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
                "skipped": False,
                "results": [],
                "error": "INVALID_SYMBOL",
                "open_orders_raw": None,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel all orders result=%s", result)

            return result

        normalized_symbol = self.normalize_symbol(raw_symbol)

        try:
            open_result = self.get_open_orders(normalized_symbol)
        except Exception as e:
            self.logger.exception("KUCOIN CANCEL ALL OPEN ORDERS EXCEPTION")

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
                "skipped": False,
                "results": [],
                "error": str(e),
                "open_orders_raw": None,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel all orders result=%s", result)

            return result

        open_orders_raw = (
            open_result.get("raw")
            if isinstance(open_result, dict)
            else open_result
        )

        if not isinstance(open_result, dict) or not open_result.get("success"):

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
                "skipped": False,
                "results": [],
                "error": (
                    open_result.get("error")
                    if isinstance(open_result, dict)
                    else "OPEN_ORDERS_FAILED"
                ),
                "open_orders_raw": open_orders_raw,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel all orders result=%s", result)

            return result

        orders = (
            open_result.get("orders")
            or []
        )

        if not orders:

            result = {
                "success": True,
                "exchange": "kucoin",
                "symbol": normalized_symbol,
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
                "skipped": True,
                "results": [],
                "error": None,
                "open_orders_raw": open_orders_raw,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin cancel all orders result=%s", result)

            return result

        results = []
        cancelled = 0
        failed = 0

        for order in orders:

            order_id = None

            try:
                if isinstance(order, dict):
                    order_id = (
                        order.get("order_id")
                        or order.get("id")
                        or order.get("orderId")
                    )

                order_id = (
                    str(order_id).strip()
                    if order_id is not None
                    else ""
                )

                if not order_id:
                    failed += 1
                    results.append({
                        "order_id": None,
                        "success": False,
                        "cancelled": False,
                        "error": "MISSING_ORDER_ID",
                        "raw": order,
                    })
                    continue

                try:
                    cancel_result = self.cancel_order(
                        order_id,
                        normalized_symbol
                    )
                except Exception as e:
                    self.logger.exception("KUCOIN CANCEL ALL ITEM EXCEPTION")
                    cancel_result = {
                        "success": False,
                        "order_id": order_id,
                        "cancelled": False,
                        "error": str(e),
                        "raw": None,
                    }

                item_cancelled = bool(
                    cancel_result.get("success")
                    and cancel_result.get("cancelled")
                )

                if item_cancelled:
                    cancelled += 1
                else:
                    failed += 1

                results.append({
                    "order_id": (
                        cancel_result.get("order_id")
                        or order_id
                    ),
                    "success": bool(cancel_result.get("success")),
                    "cancelled": bool(cancel_result.get("cancelled")),
                    "error": cancel_result.get("error"),
                    "raw": cancel_result.get("raw"),
                })

            except Exception as e:
                failed += 1
                results.append({
                    "order_id": order_id,
                    "success": False,
                    "cancelled": False,
                    "error": str(e),
                    "raw": order,
                })

        result = {
            "success": failed == 0,
            "exchange": "kucoin",
            "symbol": normalized_symbol,
            "requested": len(orders),
            "cancelled": cancelled,
            "failed": failed,
            "skipped": False,
            "results": results,
            "error": (
                None
                if failed == 0
                else "CANCEL_ALL_PARTIAL_FAILURE"
            ),
            "open_orders_raw": open_orders_raw,
            "timestamp": time.time(),
        }

        runtime_debug("KuCoin cancel all orders result=%s", result)

        return result

    def get_price(
        self,
        symbol: str
    ):

        symbol = self.normalize_symbol(symbol)

        endpoint = (
            f"/api/v1/ticker?symbol={symbol}"
        )

        res = self.session.get(
            self.base_url + endpoint
        )

        data = res.json()

        return float(
            data["data"]["price"]
        )

    # =========================
    # SYMBOL RULES
    # =========================

    def get_symbol_rules(
        self,
        symbol: str
    ):

        from backend.market.kucoin_futures_public import get_order_contract_rules
        return get_order_contract_rules(symbol, session=self.session)

    # =========================
    # MIN QTY
    # =========================

    def get_min_qty(
        self,
        symbol
    ):

        rules = self.get_symbol_rules(symbol)

        return rules["min_size"]

    # =========================
    # QTY NORMALIZE
    # =========================

    def normalize_qty(
        self,
        symbol: str,
        qty: float
    ) -> int:

        rules = self.get_symbol_rules(symbol)

        min_size = rules["min_size"]

        qty = floor_contracts(qty, rules.get("qty_step", min_size))
        if qty < number(min_size):
            return 0
        qty = int(qty)

        return qty

    # =========================
    # LEVERAGE
    # =========================

    def set_leverage(
        self,
        symbol: str,
        leverage: int
    ):

        symbol = self.normalize_symbol(symbol)

        endpoint = (
            "/api/v1/position/leverage"
        )

        body_dict = {
            "symbol": symbol,
            "leverage": str(leverage)
        }

        runtime_debug("KuCoin leverage payload=%s", body_dict)

        body = json.dumps(body_dict)

        headers = self._headers(
            "POST",
            endpoint,
            body
        )

        res = self.session.post(
            self.base_url + endpoint,
            headers=headers,
            data=body
        )

        data = res.json()

        if data.get("code") != "200000":

            self.logger.error("KuCoin leverage error: %s", data)

        else:

            self.logger.info("KuCoin leverage set=%s", leverage)

    # =========================
    # ORDER
    # =========================

    @staticmethod
    def _order_leverage_authority(leverage):
        """Validate the canonical effective leverage for a LIVE order.

        Returns the normalized string form of the canonical effective
        leverage, or ``None`` when the authority is missing, non-numeric,
        zero, negative or non-finite.  The KuCoin order payload must never
        silently fall back to a hard-coded leverage.
        """
        if leverage is None or isinstance(leverage, bool):
            return None
        try:
            value = Decimal(str(leverage))
        except (InvalidOperation, ValueError, TypeError):
            return None
        if not value.is_finite() or value <= 0:
            return None
        return format(value.normalize(), "f")

    def _order_intent_store(self):
        store = self._live_order_intent_store
        if store is not None:
            return store
        if self.require_durable_intent_store:
            return None
        path = self.order_intent_path or os.environ.get("TRADINGAI_LIVE_ORDER_INTENT_PATH")
        if not path:
            path = os.path.join(
                tempfile.gettempdir(),
                f"tradingai-live-order-intents-{uuid.uuid4().hex}.json",
            )
        store = IntentStore(path)
        self._live_order_intent_store = store
        return store

    def configure_live_runtime_intent_store(self, path=None):
        """Require a durable intent file before any formal LIVE write.

        Does not create a production directory or read an exchange. A missing
        path, unreadable directory, corrupt file, or failed load stays closed.
        """

        self.require_durable_intent_store = True
        self._order_recovery_complete = False
        self._live_order_intent_store = None
        chosen = path or os.environ.get("TRADINGAI_LIVE_ORDER_INTENT_PATH")
        self.order_intent_path = chosen or None
        if not chosen:
            return {"ready": False, "reason": "STORE_PATH_MISSING"}
        directory = os.path.dirname(os.path.abspath(chosen))
        if not os.path.isdir(directory) or not os.access(directory, os.R_OK | os.W_OK):
            return {"ready": False, "reason": "STORE_PATH_MISSING"}
        try:
            store = IntentStore(chosen)
        except OSError:
            return {"ready": False, "reason": "STORE_READ_FAILED"}
        if store.load_error:
            self._live_order_intent_store = store
            return {"ready": False, "reason": store.load_error}
        self._live_order_intent_store = store
        return {"ready": True, "reason": None}

    def _closed_order_gates(self, reason):
        return {
            "storeReady": False,
            "recoveryComplete": False,
            "unknownCommitClear": False,
            "unprotectedClear": False,
            "protectionPendingClear": False,
            "protectionKnown": False,
            "exitReconciliationClear": False,
            "exchangeStateFresh": False,
            "reason": reason,
            "intents": [],
        }

    def runtime_order_gates(self):
        """Existing readiness facts for the formal LIVE path.

        Isolated client tests leave ``require_durable_intent_store`` false and
        receive no extra gates.
        """

        if self.require_durable_intent_store is not True:
            return None
        store = self._live_order_intent_store
        if store is None:
            return self._closed_order_gates("STORE_PATH_MISSING")
        if store.load_error:
            return self._closed_order_gates(store.load_error)
        records = store.records()
        states = {record.get("state") for record in records}
        filled_ids = {
            record.get("intentId")
            for record in records
            if record.get("purpose") == PURPOSE_ENTRY and record.get("state") == FILLED
        }
        confirmed_parents = {
            record.get("parentId")
            for record in records
            if record.get("purpose") == PURPOSE_PROTECTION
            and record.get("state") == PROTECTION_CONFIRMED
        }
        unprotected = UNPROTECTED in states or any(
            intent_id not in confirmed_parents for intent_id in filled_ids
        )
        fresh = self.exchange_state_fresh is True
        return {
            "storeReady": True,
            "recoveryComplete": self._order_recovery_complete is True and fresh,
            "unknownCommitClear": UNKNOWN_COMMIT not in states and NOT_FOUND_INCONCLUSIVE not in states,
            "unprotectedClear": not unprotected,
            "protectionPendingClear": PROTECTION_PENDING not in states,
            "protectionKnown": PROTECTION_UNKNOWN not in states,
            "exitReconciliationClear": EXIT_PENDING not in states and RECONCILIATION_REQUIRED not in states,
            "exchangeStateFresh": fresh,
            "reason": None,
            "intents": records,
        }

    def recover_unresolved_intents(self):
        """Read-only restart recovery. Never posts, deletes, or marks FLAT."""

        if self.require_durable_intent_store is not True:
            return {"complete": True, "skipped": True, "postAttempts": 0, "intents": []}
        store = self._live_order_intent_store
        if store is None or store.load_error:
            self._order_recovery_complete = False
            reason = "STORE_PATH_MISSING" if store is None else store.load_error
            return {"complete": False, "reason": reason, "postAttempts": 0, "intents": []}
        for record in list(store.records()):
            if record.get("state") in {
                UNKNOWN_COMMIT,
                ACCEPTED,
                PROTECTION_PENDING,
                PROTECTION_UNKNOWN,
                EXIT_PENDING,
                NOT_FOUND_INCONCLUSIVE,
                INTENT_RECORDED,
            }:
                self.reconcile_intent(record.get("intentId"))
        remaining = [
            record for record in store.records()
            if record.get("state") not in {REJECTED, FLAT_CONFIRMED, PROTECTION_CONFIRMED}
        ]
        self._order_recovery_complete = not remaining
        return {
            "complete": self._order_recovery_complete,
            "reason": None if self._order_recovery_complete else "UNRESOLVED_INTENTS",
            "postAttempts": 0,
            "intents": remaining,
        }

    def liquidation_risk_status(self):
        return liquidation_risk_boundary()

    def _submission_gate(self, symbol, account_symbol=None, purpose=None):
        # Entry and protective-stop writes require live order authority. A
        # reduce-only EXIT does not: emergency flatten must remain available
        # after DISARM/STOP, exactly as the documented emergency-exit
        # capability requires. Exit is still constrained by the durable store
        # and by the position/account identity checks.
        if purpose != PURPOSE_EXIT:
            if not self.live_order_allowed:
                return {"submit": False, "commitState": "DISARMED", "reason": "REAL_ORDER_DISARMED"}
            if self.runtime_submission_allowed is not True:
                return {"submit": False, "commitState": "STOPPED", "reason": "RUNTIME_STOPPED"}
        if account_symbol and str(account_symbol).strip() != str(symbol).strip():
            return {"submit": False, "commitState": "REJECTED", "reason": "ACCOUNT_SYMBOL_MISMATCH"}
        return None

    def _live_close_error_code(self, submission):
        """Translate durable-submission facts to the flatten error contract."""

        reason = submission.get("reason")
        if reason == "Timeout":
            return "TIMEOUT"
        if reason in {"ConnectionError", "TRANSPORT"}:
            return "API_ERROR"
        if reason == "AUTH_ERROR":
            return "AUTH_ERROR"
        if reason == "MALFORMED_RESPONSE":
            return "MALFORMED_RESPONSE"
        if reason == "EXCHANGE_REJECTED":
            return "API_ERROR"
        if isinstance(reason, str) and reason.startswith("HTTP_"):
            return "API_ERROR"
        return submission.get("commitState") or reason

    def submit_bounded_order(
        self,
        *,
        purpose,
        symbol,
        side,
        size,
        body_fields,
        intent_id=None,
        parent_id=None,
        stop_price=None,
        account_symbol=None,
        timeout=10,
    ):
        """Persist the intent, then POST at most once for that logical order."""

        gate = self._submission_gate(symbol, account_symbol, purpose=purpose)
        if gate is not None:
            return gate
        store = self._order_intent_store()
        if store is None or getattr(store, "load_error", None):
            reason = "STORE_PATH_MISSING" if store is None else store.load_error
            return {"submit": False, "commitState": "REJECTED", "reason": reason}
        if intent_id is None:
            existing = store.unresolved(purpose, symbol)
            if existing is not None and existing.get("state") != INTENT_RECORDED:
                return {
                    "submit": False,
                    "commitState": existing.get("state"),
                    "reason": "INTENT_ALREADY_RECORDED",
                    "intentId": existing.get("intentId"),
                    "clientOid": existing.get("clientOid"),
                    "intent": existing,
                }
            if existing is not None:
                intent_id = existing.get("intentId")
        if purpose == PURPOSE_ENTRY:
            blocked = store.entry_blocked(symbol)
            if blocked is not None and blocked.get("intentId") != intent_id:
                return {
                    "submit": False,
                    "commitState": blocked.get("state"),
                    "reason": "ENTRY_BLOCKED",
                    "intentId": blocked.get("intentId"),
                    "clientOid": blocked.get("clientOid"),
                }
            # A new ENTRY must prove current, bound trading permission at the
            # exchange submission boundary too.  Protective stops and
            # reduce-only EXIT remain governed by their own paths so an open
            # position can still be protected / closed safely.
            permission = self.trading_permission_authority()
            if permission.get("allowed") is not True:
                return {
                    "submit": False,
                    "commitState": "REJECTED",
                    "reason": permission.get("reason")
                    or "TRADING_PERMISSION_UNVERIFIED",
                    "blockReasons": list(permission.get("reasons") or []),
                }
        record = store.begin(
            purpose=purpose,
            symbol=symbol,
            side=side,
            size=size,
            intent_id=intent_id,
            parent_id=parent_id,
            stop_price=stop_price,
        )
        if record.get("ok") is not True:
            return {"submit": False, "commitState": "REJECTED", "reason": record.get("reason"), "intent": record}
        if record.get("created") is not True and record.get("state") == INTENT_RECORDED:
            stored = store.mark(record["intentId"], UNKNOWN_COMMIT, reason="PERSISTED_BEFORE_ACK")
            return {
                "submit": False,
                "commitState": UNKNOWN_COMMIT,
                "reason": "PERSISTED_BEFORE_ACK",
                "intentId": record.get("intentId"),
                "clientOid": record.get("clientOid"),
                "intent": stored or record,
            }
        if record.get("duplicate") or record.get("state") != INTENT_RECORDED:
            return {
                "submit": False,
                "commitState": record.get("state"),
                "reason": "INTENT_ALREADY_RECORDED",
                "intentId": record.get("intentId"),
                "clientOid": record.get("clientOid"),
                "intent": record,
            }
        body_dict = dict(body_fields)
        body_dict["clientOid"] = record["clientOid"]
        endpoint = "/api/v1/orders"
        body = json.dumps(body_dict)
        try:
            headers = self._headers("POST", endpoint, body)
            response = self.session.post(
                self.base_url + endpoint,
                headers=headers,
                data=body,
                timeout=timeout,
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            unknown_state = PROTECTION_UNKNOWN if purpose == PURPOSE_PROTECTION else UNKNOWN_COMMIT
            stored = store.mark(record["intentId"], unknown_state, reason=type(exc).__name__)
            return {
                "submit": False,
                "commitState": unknown_state,
                "reason": type(exc).__name__,
                "intentId": record["intentId"],
                "clientOid": record["clientOid"],
                "intent": stored,
            }
        except requests.exceptions.RequestException as exc:
            unknown_state = PROTECTION_UNKNOWN if purpose == PURPOSE_PROTECTION else UNKNOWN_COMMIT
            stored = store.mark(record["intentId"], unknown_state, reason="TRANSPORT")
            return {
                "submit": False,
                "commitState": unknown_state,
                "reason": str(exc.__class__.__name__),
                "intentId": record["intentId"],
                "clientOid": record["clientOid"],
                "intent": stored,
            }
        status_code = getattr(response, "status_code", None)
        try:
            status_code = int(status_code) if status_code is not None else None
        except (TypeError, ValueError):
            status_code = None
        if status_code is not None and status_code >= 500:
            unknown_state = PROTECTION_UNKNOWN if purpose == PURPOSE_PROTECTION else UNKNOWN_COMMIT
            stored = store.mark(record["intentId"], unknown_state, reason=f"HTTP_{status_code}")
            return {
                "submit": False,
                "commitState": unknown_state,
                "reason": f"HTTP_{status_code}",
                "intentId": record["intentId"],
                "clientOid": record["clientOid"],
                "intent": stored,
            }
        if status_code is not None and status_code in (401, 403):
            stored = store.mark(record["intentId"], REJECTED, reason="AUTH_ERROR")
            return {
                "submit": False,
                "commitState": REJECTED,
                "reason": "AUTH_ERROR",
                "intentId": record["intentId"],
                "clientOid": record["clientOid"],
                "intent": stored,
            }
        if status_code is not None and status_code >= 400:
            stored = store.mark(record["intentId"], REJECTED, reason=f"HTTP_{status_code}")
            return {
                "submit": False,
                "commitState": REJECTED,
                "reason": f"HTTP_{status_code}",
                "intentId": record["intentId"],
                "clientOid": record["clientOid"],
                "intent": stored,
            }
        try:
            payload = response.json()
        except Exception:
            unknown_state = PROTECTION_UNKNOWN if purpose == PURPOSE_PROTECTION else UNKNOWN_COMMIT
            stored = store.mark(record["intentId"], unknown_state, reason="MALFORMED_RESPONSE")
            return {
                "submit": False,
                "commitState": unknown_state,
                "reason": "MALFORMED_RESPONSE",
                "intentId": record["intentId"],
                "clientOid": record["clientOid"],
                "intent": stored,
            }
        if not isinstance(payload, dict):
            # A non-object body cannot prove the exchange rejected the order.
            unknown_state = PROTECTION_UNKNOWN if purpose == PURPOSE_PROTECTION else UNKNOWN_COMMIT
            stored = store.mark(record["intentId"], unknown_state, reason="MALFORMED_RESPONSE")
            return {
                "submit": False,
                "commitState": unknown_state,
                "reason": "MALFORMED_RESPONSE",
                "raw": payload,
                "intentId": record["intentId"],
                "clientOid": record["clientOid"],
                "intent": stored,
            }
        if payload.get("code") != "200000":
            stored = store.mark(record["intentId"], REJECTED, reason="EXCHANGE_REJECTED", rawCode=payload.get("code"))
            return {
                "submit": False,
                "commitState": REJECTED,
                "reason": "EXCHANGE_REJECTED",
                "raw": payload,
                "intentId": record["intentId"],
                "clientOid": record["clientOid"],
                "intent": stored,
            }
        order_id = None
        data = payload.get("data")
        if isinstance(data, dict) and data.get("orderId"):
            order_id = str(data.get("orderId"))
        if not order_id:
            # Accepted without an exchange order id is not confirmation.
            unknown_state = PROTECTION_UNKNOWN if purpose == PURPOSE_PROTECTION else UNKNOWN_COMMIT
            stored = store.mark(record["intentId"], unknown_state, reason="MALFORMED_RESPONSE")
            return {
                "submit": False,
                "commitState": unknown_state,
                "reason": "MALFORMED_RESPONSE",
                "raw": payload,
                "intentId": record["intentId"],
                "clientOid": record["clientOid"],
                "intent": stored,
            }
        next_state = PROTECTION_PENDING if purpose == PURPOSE_PROTECTION else ACCEPTED
        if purpose == PURPOSE_EXIT:
            next_state = EXIT_PENDING
        stored = store.mark(record["intentId"], next_state, orderId=order_id)
        return {
            "submit": True,
            "commitState": next_state,
            "orderId": order_id,
            "raw": payload,
            "body": body_dict,
            "intentId": record["intentId"],
            "clientOid": record["clientOid"],
            "intent": stored,
        }

    def lookup_order_by_client_oid(self, client_oid, *, symbol=None, stop=False, timeout=10):
        """Read-only lookup. One NOT_FOUND result is not proof of absence."""

        if stop:
            endpoint = "/api/v1/stopOrders"
            if symbol:
                endpoint += "?symbol=" + quote(str(symbol), safe="")
        else:
            endpoint = "/api/v1/orders/byClientOid?clientOid=" + quote(str(client_oid), safe="")
        try:
            headers = self._headers("GET", endpoint, "")
            response = self.session.get(
                self.base_url + endpoint,
                headers=headers,
                timeout=timeout,
            )
            payload = response.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException):
            return {"classification": "UNKNOWN"}
        except Exception:
            return {"classification": "UNKNOWN"}
        if not isinstance(payload, dict):
            return {"classification": "UNKNOWN"}
        if payload.get("code") != "200000":
            message = str(payload.get("msg") or payload.get("code") or "").lower()
            if "not exist" in message or "not found" in message or str(payload.get("code")) in {"100001", "200004"}:
                return {"classification": "NOT_FOUND", "raw": payload}
            return {"classification": "UNKNOWN", "raw": payload}
        data = payload.get("data")
        items = []
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            items = data.get("items")
        elif isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        for item in items:
            if isinstance(item, dict) and str(item.get("clientOid") or "") == str(client_oid):
                return {"classification": "FOUND", "order": item}
        if stop:
            return {"classification": "NOT_FOUND", "raw": payload}
        if isinstance(data, dict) and str(data.get("clientOid") or "") == str(client_oid):
            return {"classification": "FOUND", "order": data}
        return {"classification": "NOT_FOUND", "raw": payload}

    def reconcile_intent(self, intent_id, *, timeout=10):
        store = self._order_intent_store()
        record = store.get(intent_id)
        if record is None:
            return {"commitState": "UNKNOWN", "reason": "INTENT_MISSING"}
        stop = record.get("purpose") == PURPOSE_PROTECTION
        looked = self.lookup_order_by_client_oid(
            record.get("clientOid"),
            symbol=record.get("symbol"),
            stop=stop,
            timeout=timeout,
        )
        if looked.get("classification") == "UNKNOWN":
            stored = store.mark(intent_id, UNKNOWN_COMMIT if not stop else PROTECTION_UNKNOWN, reason="LOOKUP_UNKNOWN")
            return {"commitState": stored.get("state"), "intent": stored}
        if looked.get("classification") == "NOT_FOUND":
            stored = store.note_not_found(intent_id)
            return {"commitState": stored.get("state"), "reason": stored.get("reason"), "intent": stored}
        order = looked.get("order") or {}
        if str(order.get("symbol") or record.get("symbol")) != record.get("symbol"):
            stored = store.mark(intent_id, RECONCILIATION_REQUIRED, reason="ACCOUNT_SYMBOL_MISMATCH")
            return {"commitState": stored.get("state"), "intent": stored}
        if stop:
            evidence_ok = (
                str(order.get("side") or "").lower() == record.get("side")
                and str(order.get("size") or order.get("qty") or "") == str(record.get("size"))
                and str(order.get("stopPrice") or "") == str(record.get("stopPrice") or "")
                and order.get("reduceOnly") is True
            )
            if not evidence_ok:
                stored = store.mark(intent_id, PROTECTION_UNKNOWN, reason="PROTECTION_EVIDENCE_MISMATCH")
                return {"commitState": stored.get("state"), "intent": stored}
            stored = store.mark(intent_id, PROTECTION_CONFIRMED, orderId=order.get("id") or order.get("orderId"))
            return {"commitState": PROTECTION_CONFIRMED, "intent": stored}
        status = str(order.get("status") or "").lower()
        if status in {"done", "filled", "finished"}:
            stored = store.mark(intent_id, FILLED, orderId=order.get("id") or order.get("orderId"))
            return {"commitState": FILLED, "intent": stored}
        stored = store.mark(intent_id, ACCEPTED, orderId=order.get("id") or order.get("orderId"))
        return {"commitState": ACCEPTED, "intent": stored}

    def place_exchange_protective_stop(
        self,
        *,
        symbol,
        position_side,
        filled_qty,
        stop_price,
        margin_mode,
        parent_intent_id,
        account_symbol=None,
        timeout=10,
        tick_size=None,
    ):
        """Submit a reduce-only KuCoin stop and leave it unconfirmed until lookup."""

        close_side, direction = protective_stop_sides(position_side)
        if tick_size is not None:
            price_text = quantize_stop_price(stop_price, tick_size, close_side)
        else:
            price_text = format_stop_price(stop_price)
        if close_side is None or price_text is None or not margin_mode:
            return {"submit": False, "commitState": UNPROTECTED, "reason": "STOP_CONTRACT_UNAVAILABLE"}
        result = self.submit_bounded_order(
            purpose=PURPOSE_PROTECTION,
            symbol=symbol,
            side=close_side,
            size=filled_qty,
            parent_id=parent_intent_id,
            stop_price=price_text,
            account_symbol=account_symbol,
            timeout=timeout,
            body_fields={
                "symbol": symbol,
                "side": close_side,
                "type": "market",
                "size": str(filled_qty),
                "stop": direction,
                "stopPriceType": "MP",
                "stopPrice": price_text,
                "reduceOnly": True,
                "marginMode": margin_mode,
            },
        )
        if result.get("commitState") == REJECTED:
            intent_id = result.get("intentId")
            if intent_id:
                self._order_intent_store().mark(intent_id, UNPROTECTED, reason="STOP_REJECTED")
                result["commitState"] = UNPROTECTED
        return result

    def confirm_exchange_flat(self, exit_intent_id, position_found):
        """FLAT requires a position read, not only an exit acknowledgement."""

        store = self._order_intent_store()
        if position_found is True:
            stored = store.mark(exit_intent_id, EXIT_PENDING, reason="POSITION_REMAINS")
            return {"commitState": EXIT_PENDING, "intent": stored}
        if position_found is not False:
            stored = store.mark(exit_intent_id, RECONCILIATION_REQUIRED, reason="FLAT_UNKNOWN")
            return {"commitState": RECONCILIATION_REQUIRED, "intent": stored}
        stored = store.mark(exit_intent_id, FLAT_CONFIRMED, reason="EXCHANGE_FLAT")
        record = store.get(exit_intent_id)
        parent = record.get("parentId") if record else None
        if parent:
            store.mark(parent, FLAT_CONFIRMED, reason="EXCHANGE_FLAT")
        return {"commitState": FLAT_CONFIRMED, "intent": stored}

    def create_order(
        self,
        symbol,
        side,
        qty,
        price=None,
        leverage=None,
        sizing_validator=None
    ):

        if not self.live_order_allowed:

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "blockedReason": "LIVE_NOT_READY",
                "liveBlockReasons": list(
                    self.live_block_reasons
                    or ["LIVE_NOT_READY"]
                ),
                "error": "LIVE_NOT_READY",
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin order blocked result=%s", result)

            return result

        permission = self.trading_permission_authority()
        if permission.get("allowed") is not True:
            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "blockedReason": permission.get("reason")
                or "TRADING_PERMISSION_UNVERIFIED",
                "liveBlockReasons": list(permission.get("reasons") or []),
                "error": permission.get("reason")
                or "TRADING_PERMISSION_UNVERIFIED",
                "timestamp": time.time(),
            }
            runtime_debug("KuCoin order blocked result=%s", result)
            return result

        runtime_debug(
            "KuCoin create order symbol=%s side=%s qty=%s price=%s",
            symbol,
            side,
            qty,
            price,
        )

        try:

            symbol = self.normalize_symbol(symbol)

            # =====================================
            # CANONICAL LEVERAGE AUTHORITY (fail-closed)
            # =====================================
            # The LIVE order payload leverage is the canonical effective
            # leverage resolved by the Money Management / runtime authority
            # at the START boundary.  It must never be replaced by a
            # hard-coded value.  A missing / invalid authority fails closed
            # and no exchange order is constructed.

            order_leverage = self._order_leverage_authority(leverage)

            if order_leverage is None:

                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "blockedReason": "LEVERAGE_AUTHORITY_UNAVAILABLE",
                    "error": "LEVERAGE_AUTHORITY_UNAVAILABLE",
                    "timestamp": time.time(),
                }

                runtime_debug("KuCoin order blocked result=%s", result)

                return result

            # =====================================
            # BTC QTY -> CONTRACT SIZE
            # =====================================

            rules = self.get_symbol_rules(symbol)

            multiplier = rules.get(
                "multiplier",
                1
            )

            ticker = self.get_price(symbol)

            runtime_debug("KuCoin order ticker=%s", ticker)

            price_now = float(ticker)

            contracts = number(qty) / number(multiplier)

            # =====================================
            # MIN CONTRACT SAFETY
            # =====================================

            min_size = rules.get(
                "min_size",
                1
            )

            if contracts < min_size:

                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "error": (
                        f"position size below minimum "
                        f"contract size "
                        f"({contracts} < {min_size})"
                    ),
                    "timestamp": time.time(),
                }

                self.logger.warning(
                    "ORDER REJECTED: below minimum contracts=%s min_size=%s",
                    contracts,
                    min_size,
                )

                runtime_debug("KuCoin normalized result=%s", result)

                return result

            qty = floor_contracts(contracts, rules.get("qty_step", min_size))
            if qty < number(min_size):
                raise SizingRejected("NO_VALID_QUANTITY_FOR_EXCHANGE_CONSTRAINTS")
            if not callable(sizing_validator):
                raise SizingRejected("FINAL_SIZING_AUTHORITY_UNAVAILABLE")
            # This is the exact integer contract size serialized below. Nothing
            # may round, clamp or otherwise increase it after this validation.
            if qty != qty.to_integral_value():
                raise SizingRejected("INVALID_INTEGER_CONTRACT_QUANTITY")
            qty = int(qty)
            if sizing_validator(symbol=symbol, contracts=qty, price=price_now,
                                rules=rules, leverage=leverage) is not True:
                raise SizingRejected("FINAL_NORMALIZED_QUANTITY_REJECTED")

            submission = self.submit_bounded_order(
                purpose=PURPOSE_ENTRY,
                symbol=symbol,
                side=side.lower(),
                size=qty,
                body_fields={
                    "symbol": symbol,
                    "side": side.lower(),
                    "type": "market",
                    "size": str(qty),
                    "leverage": order_leverage,
                    "marginMode": REQUESTED_MARGIN_MODE,
                },
            )

            if submission.get("submit") is not True:
                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "error": submission.get("reason"),
                    "commitState": submission.get("commitState"),
                    "clientOid": submission.get("clientOid"),
                    "intentId": submission.get("intentId"),
                    "raw": submission.get("raw"),
                    "timestamp": time.time(),
                }
                runtime_debug("KuCoin normalized result=%s", result)
                return result

            data = submission.get("raw") or {}
            self.logger.info("ORDER SENT: KuCoin response=%s", data)

            result = {
                "success": True,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "order_id": submission.get("orderId"),
                "commitState": submission.get("commitState"),
                "clientOid": submission.get("clientOid"),
                "intentId": submission.get("intentId"),
                "raw": data,
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin normalized result=%s", result)

            return result

        except Exception as e:

            self.logger.exception("KUCOIN ORDER EXCEPTION")

            result = {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "error": str(e),
                "timestamp": time.time(),
            }

            runtime_debug("KuCoin normalized result=%s", result)

            return result

    def place_order(
        self,
        symbol,
        side,
        qty,
        price=None,
        leverage=None,
        sizing_validator=None
    ):
        # =====================================
        # MARGIN MODE AUTHORITY (fail-closed)
        # =====================================
        # Every LIVE entry (BOT and MANUAL) funnels through this shared method
        # before any order is constructed.  The requested canonical mode
        # (ISOLATED) must match the authoritative exchange symbol margin mode.
        # A mismatch or an unavailable authority blocks before
        # POST /api/v1/orders.  The disarmed gate is resolved by create_order
        # so LIVE_NOT_READY keeps precedence when live orders are not allowed.
        if self.live_order_allowed:
            block = self.margin_mode_entry_gate(symbol)

            if block is not None:
                result = {
                    "success": False,
                    "exchange": "kucoin",
                    "symbol": self.normalize_symbol(symbol),
                    "side": side,
                    "qty": qty,
                    "blockedReason": block["reason"],
                    "error": block["reason"],
                    "requestedMarginMode": block["requestedMarginMode"],
                    "exchangeMarginMode": block["exchangeMarginMode"],
                    "marginModeSource": block["marginModeSource"],
                    "marginModeAuthorityReason": block.get("authorityReason"),
                    "timestamp": time.time(),
                }

                runtime_debug(
                    "KuCoin margin mode gate blocked result=%s",
                    result,
                )

                return result

        return self.create_order(
            symbol,
            side,
            qty,
            price,
            leverage,
            sizing_validator=sizing_validator
        )

    # =========================
    # CLOSE POSITION
    # =========================

    def close_position(
        self,
        symbol,
        leverage=None
    ):

        pos = self.get_positions(symbol)

        if not pos:

            runtime_debug("KuCoin close skipped: no position")

            return {
                "success": False,
                "exchange": "kucoin",
                "symbol": symbol,
                "error": "NO POSITION TO CLOSE",
                "timestamp": time.time(),
            }

        side = (
            "SELL"
            if pos["side"] == "BUY"
            else "BUY"
        )

        # =====================================
        # CONTRACT -> COIN QTY
        # =====================================

        rules = self.get_symbol_rules(symbol)

        multiplier = rules["multiplier"]

        coin_qty = (
            pos["qty"] * multiplier
        )

        runtime_debug(
            "KuCoin close conversion contracts=%s multiplier=%s coin_qty=%s",
            pos["qty"],
            multiplier,
            coin_qty,
        )

        return self.create_order(
            symbol=symbol,
            side=side,
            qty=coin_qty,
            leverage=leverage
        )
