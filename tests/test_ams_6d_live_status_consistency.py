from copy import deepcopy

import pytest

from backend.auto_market_selection.live_status_consistency import derive_live_readiness


def base():
    return {
        "checks": {
            "selectedModeLive": False,
            "dryRunDisabled": False,
            "allowLive": False,
            "tradeModeLive": False,
            "exchangeClientReady": False,
            "exchangeAuthReady": False,
            "balanceCheckOk": False,
            "positionCheckOk": False,
            "executionEnabled": False,
            "emergencyStopClear": True,
        },
        "blockReasons": [
            "SELECTED_MODE_NOT_LIVE", "DRY_RUN_ACTIVE", "LIVE_NOT_ENABLED",
            "TRADE_MODE_NOT_LIVE", "KUCOIN_CREDENTIALS_MISSING",
            "EXCHANGE_CLIENT_NOT_READY", "BALANCE_CHECK_FAILED",
            "POSITION_CHECK_FAILED", "EXECUTION_DISABLED",
        ],
    }


def account(**changes):
    value = {
        "authenticated": True,
        "connected": True,
        "stale": False,
        "equity": 1,
        "balanceSource": "KUCOIN_FUTURES_READ_ONLY",
        "positionSource": "KUCOIN_FUTURES_READ_ONLY",
        "positionSummary": "FLAT",
    }
    value.update(changes)
    return value


def test_verified_stopped_paper_rebuilds_only_current_live_disabled_reasons():
    result = derive_live_readiness(base(), account())
    assert result["exchangeAuthReady"] and result["exchangeClientReady"]
    assert result["balanceCheckOk"] and result["positionCheckOk"]
    assert result["blockReasons"] == [
        "SELECTED_MODE_NOT_LIVE", "DRY_RUN_ACTIVE", "LIVE_NOT_ENABLED",
        "TRADE_MODE_NOT_LIVE", "EXECUTION_DISABLED",
    ]
    assert not result["ready"] and not result["realOrderAllowed"]


@pytest.mark.parametrize("changes,reason", [
    ({"authenticated": False}, "KUCOIN_CREDENTIALS_MISSING"),
    ({"connected": False}, "EXCHANGE_CLIENT_NOT_READY"),
    ({"balanceSource": None}, "BALANCE_CHECK_FAILED"),
    ({"positionSummary": "UNKNOWN"}, "POSITION_CHECK_FAILED"),
    ({"stale": True}, "BALANCE_CHECK_FAILED"),
])
def test_unavailable_authority_retains_correct_block(changes, reason):
    source = base()
    source["checks"].update({
        "exchangeAuthReady": False, "exchangeClientReady": False,
        "balanceCheckOk": False, "positionCheckOk": False,
    })
    result = derive_live_readiness(source, account(**changes))
    assert reason in result["blockReasons"]
    assert not result["ready"]


def test_open_position_is_valid_but_not_flat():
    result = derive_live_readiness(base(), account(positionSummary="OPEN"))
    assert result["positionCheckOk"]
    assert "POSITION_CHECK_FAILED" not in result["blockReasons"]
    assert "POSITION_NOT_FLAT" in result["blockReasons"]


@pytest.mark.parametrize("state,expected", [
    ("NONE", None),
    ("EXISTS", "PENDING_ORDERS_EXIST"),
    ("UNKNOWN", "PENDING_ORDERS_UNKNOWN"),
])
def test_pending_order_states_are_fail_closed(state, expected):
    source = base()
    source["pendingOrderState"] = state
    result = derive_live_readiness(source, account())
    if expected is None:
        assert not any(reason.startswith("PENDING_") for reason in result["blockReasons"])
    else:
        assert expected in result["blockReasons"]


def test_contradictory_reported_reason_adds_consistency_guard():
    source = base()
    stale = deepcopy(source["blockReasons"])
    result = derive_live_readiness(source, account(), reported_reasons=stale)
    assert "KUCOIN_CREDENTIALS_MISSING" not in result["blockReasons"]
    assert "LIVE_STATUS_CONSISTENCY_REQUIRED" in result["blockReasons"]
    assert not result["statusConsistent"]


def test_reason_order_and_deduplication_are_deterministic():
    first = derive_live_readiness(base(), account(authenticated=False))
    second = derive_live_readiness(base(), account(authenticated=False))
    assert first["blockReasons"] == second["blockReasons"]
    assert len(first["blockReasons"]) == len(set(first["blockReasons"]))


def test_current_account_authority_overrides_stale_positive_checks():
    source = base()
    source["checks"].update({
        "exchangeAuthReady": True,
        "exchangeClientReady": True,
        "balanceCheckOk": True,
        "positionCheckOk": True,
    })
    result = derive_live_readiness(
        source,
        account(
            authenticated=False,
            connected=False,
            balanceSource=None,
            positionSource=None,
        ),
    )
    assert "KUCOIN_CREDENTIALS_MISSING" in result["blockReasons"]
    assert "EXCHANGE_CLIENT_NOT_READY" in result["blockReasons"]
    assert "BALANCE_CHECK_FAILED" in result["blockReasons"]
    assert "POSITION_CHECK_FAILED" in result["blockReasons"]


def test_real_live_account_source_and_mapping_pending_state_are_supported():
    current = account(
        balanceSource="REAL_LIVE_ACCOUNT",
        positionSource="REAL_LIVE_ACCOUNT",
    )
    source = base()
    source["pendingOrderState"] = {"state": "NONE"}
    result = derive_live_readiness(source, current)
    assert result["balanceCheckOk"] and result["positionCheckOk"]
    assert not any(reason.startswith("PENDING_") for reason in result["blockReasons"])


def test_invalid_current_credential_cannot_be_overridden_by_verified_labels():
    current = account(apiKeyStatus="VERIFIED", credentialValid=False)
    result = derive_live_readiness(base(), current)
    assert "KUCOIN_CREDENTIALS_MISSING" in result["blockReasons"]
