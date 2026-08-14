"""Deterministic, authority-first Live readiness reason projection."""

from collections.abc import Mapping


REASON_ORDER = (
    ("selectedModeLive", "SELECTED_MODE_NOT_LIVE"),
    ("dryRunDisabled", "DRY_RUN_ACTIVE"),
    ("allowLive", "LIVE_NOT_ENABLED"),
    ("tradeModeLive", "TRADE_MODE_NOT_LIVE"),
    ("exchangeAuthReady", "KUCOIN_CREDENTIALS_MISSING"),
    ("exchangeClientReady", "EXCHANGE_CLIENT_NOT_READY"),
    ("balanceCheckOk", "BALANCE_CHECK_FAILED"),
    ("positionCheckOk", "POSITION_CHECK_FAILED"),
    ("pendingOrdersKnown", "PENDING_ORDERS_UNKNOWN"),
    ("pendingOrdersClear", "PENDING_ORDERS_EXIST"),
    ("mmFresh", "MM_STALE"),
    ("executionEnabled", "EXECUTION_DISABLED"),
    ("emergencyStopClear", "EMERGENCY_STOP_ACTIVE"),
    ("governanceAllow", "GOVERNANCE_BLOCK"),
)

REAL_ACCOUNT_SOURCES = frozenset({
    "REAL_LIVE_ACCOUNT",
    "KUCOIN_FUTURES_READ_ONLY",
})


def derive_live_readiness(readiness, real_account=None, *, reported_reasons=None):
    """Rebuild reasons from current facts; optional reported reasons are audited."""
    if not isinstance(readiness, Mapping):
        raise TypeError("readiness mapping required")
    account = real_account if isinstance(real_account, Mapping) else {}
    result = dict(readiness)
    checks = dict(result.get("checks") or {})

    has_account_authority = bool(account)
    authenticated = bool(
        account.get("authenticated")
        and account.get("apiKeyStatus", "VERIFIED") == "VERIFIED"
        and account.get("credentialValid", True) is True
    )
    connected = bool(account.get("connected"))
    fresh = account.get("stale") is False
    balance_valid = bool(
        fresh
        and account.get("balanceSource") in REAL_ACCOUNT_SOURCES
        and (account.get("equity") is not None or account.get("balance") is not None)
    )
    position_state = account.get("positionSummary")
    position_valid = bool(
        fresh
        and account.get("positionSource") in REAL_ACCOUNT_SOURCES
        and position_state in ("FLAT", "OPEN")
    )
    checks.update({
        "exchangeAuthReady": authenticated if has_account_authority else bool(checks.get("exchangeAuthReady")),
        "exchangeClientReady": connected if has_account_authority else bool(checks.get("exchangeClientReady")),
        "balanceCheckOk": balance_valid if has_account_authority else bool(checks.get("balanceCheckOk")),
        "positionCheckOk": position_valid if has_account_authority else bool(checks.get("positionCheckOk")),
    })
    pending_state = result.get("pendingOrderState")
    if isinstance(pending_state, Mapping):
        pending_state = pending_state.get("state") or pending_state.get("status")
    pending_state = str(pending_state).strip().upper() if pending_state is not None else None
    if pending_state is not None:
        checks["pendingOrdersKnown"] = pending_state in ("NONE", "EXISTS")
        checks["pendingOrdersClear"] = pending_state == "NONE"
    if "mmFresh" not in checks and "mmFresh" in result:
        checks["mmFresh"] = result.get("mmFresh") is True
    if "governanceAllow" not in checks and "governanceAllow" in result:
        checks["governanceAllow"] = result.get("governanceAllow") is True

    reasons = [reason for key, reason in REASON_ORDER if key in checks and not checks[key]]
    if position_valid and position_state == "OPEN":
        position_index = next(
            (index for index, reason in enumerate(reasons) if reason.startswith("PENDING_")),
            len(reasons),
        )
        reasons.insert(position_index, "POSITION_NOT_FLAT")

    if reported_reasons is not None:
        reported = tuple(dict.fromkeys(reported_reasons or ()))
        contradictions = {
            "KUCOIN_CREDENTIALS_MISSING": checks.get("exchangeAuthReady") is True,
            "EXCHANGE_CLIENT_NOT_READY": checks.get("exchangeClientReady") is True,
            "BALANCE_CHECK_FAILED": checks.get("balanceCheckOk") is True,
            "POSITION_CHECK_FAILED": checks.get("positionCheckOk") is True,
        }
        if any(reason in reported and contradicted for reason, contradicted in contradictions.items()):
            reasons.append("LIVE_STATUS_CONSISTENCY_REQUIRED")

    reasons = list(dict.fromkeys(reasons))
    result.update({
        "checks": checks,
        "blockReasons": reasons,
        "exchangeAuthReady": checks.get("exchangeAuthReady", False),
        "exchangeClientReady": checks.get("exchangeClientReady", False),
        "balanceCheckOk": checks.get("balanceCheckOk", False),
        "positionCheckOk": checks.get("positionCheckOk", False),
        "ready": not reasons,
        "realOrderAllowed": not reasons,
        "statusConsistent": "LIVE_STATUS_CONSISTENCY_REQUIRED" not in reasons,
    })
    return result
