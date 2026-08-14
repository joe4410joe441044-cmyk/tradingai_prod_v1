from datetime import datetime, timezone
from decimal import Decimal

import pytest
import requests

from backend.auto_market_selection import LiveReadOnlyValidation
from backend.market.kucoin_futures_public import (
    KucoinFuturesPublicClient, KucoinPublicMarketError,
)
from tests.test_ams_0d_foundation import Response, Session, capital, contract_payload


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)
SAFETY = {
    "realOrderAllowed": False, "dryRun": True,
    "executionRealOrderDisabled": True,
    "autoTradeDisabled": True, "liveAutoSwitchDisabled": True,
    "emergencyAvailable": True, "governanceAvailable": True,
}


def ticker_payload(**changes):
    value = {
        "symbol": "XBTUSDTM", "price": "60000",
        "bestBidPrice": "59999", "bestAskPrice": "60001",
        "bestBidSize": "5", "bestAskSize": "7", "ts": 1,
    }
    value.update(changes)
    return value


def service(*, session=None, safety=None, active=None):
    session = session or Session([
        Response({"code": "200000", "data": [contract_payload()]}),
        Response({"code": "200000", "data": [ticker_payload()]}),
    ])
    authority = capital(evaluated_at=NOW)
    validation = LiveReadOnlyValidation(
        KucoinFuturesPublicClient(session=session, timeout=2),
        capital_provider=lambda: authority,
        active_symbol_provider=lambda: active or "ETHUSDT",
        safety_provider=lambda: safety or SAFETY,
        position_provider=lambda: "FLAT",
        pending_order_provider=lambda: False,
        emergency_provider=lambda: True,
        clock=lambda: NOW,
    )
    return validation, session


def test_public_universe_scanner_ranking_and_proposal_are_observed_without_action():
    validation, session = service()
    result = validation.observe()
    payload = result.to_dict()
    assert payload["mode"] == "LIVE_READ_ONLY"
    assert payload["universeCount"] == payload["tradableCount"] == 1
    assert payload["normalizedCount"] == 1 and payload["invalidCount"] == 0
    assert payload["evaluatedCount"] == payload["eligibleCount"] == 1
    assert payload["topCandidate"] == payload["proposedSymbol"] == "BTCUSDT"
    assert payload["activeSymbol"] == "ETHUSDT"
    assert payload["switchEligiblePreview"] is True
    assert payload["actualSwitch"] is False and payload["realOrderCreated"] is False
    assert payload["topFive"][0]["activityMetric"] is None
    assert payload["topFive"][0]["effectiveWeights"]["activity"] is None
    assert payload["scannerCycleId"] and payload["rankingCycleId"]
    assert payload["observationId"].startswith("ams-observation-")
    assert payload["auditEventId"] and payload["selectionProposalId"]
    assert len(session.calls) == 2
    assert session.calls[0][0].endswith("/api/v1/contracts/active")
    assert session.calls[1][0].endswith("/api/v1/allTickers")
    assert all(call[1] == 2 for call in session.calls)
    assert payload["topRejectionReasons"] == []


def test_ranked_active_market_score_uses_the_same_ranking_cycle():
    validation, _ = service(active="BTCUSDT")

    payload = validation.observe().to_dict()

    assert payload["candidateScore"] == payload["topScore"] == "1"
    assert payload["activeMarketScore"] == "1"
    assert payload["rankedCandidates"][0]["symbol"] == payload["activeSymbol"]
    assert payload["rankingCycleId"]


def test_exchange_alias_active_symbol_uses_canonical_same_cycle_score():
    validation, _ = service(active="XBTUSDTM")
    repeated, _ = service(active="XBTUSDTM")

    first = validation.observe().to_dict()
    second = repeated.observe().to_dict()

    assert first["activeSymbol"] == "BTCUSDT"
    assert first["activeMarketScore"] == "1"
    assert first["observationId"] == second["observationId"]


def test_observation_identity_changes_with_new_scanner_and_ranking_cycle():
    first, _ = service(active="BTCUSDT")
    second, _ = service(active="BTCUSDT")
    second.clock = lambda: NOW.replace(second=NOW.second + 1)

    initial = first.observe().to_dict()
    changed = second.observe().to_dict()

    assert initial["scannerCycleId"] != changed["scannerCycleId"]
    assert initial["rankingCycleId"] != changed["rankingCycleId"]
    assert initial["observationId"] != changed["observationId"]


def test_complete_observation_identity_does_not_require_active_symbol():
    validation, _ = service(active="BTCUSDT")
    validation.active_symbol_provider = lambda: None

    payload = validation.observe().to_dict()

    assert payload["activeSymbol"] is None
    assert payload["scannerCycleId"] and payload["rankingCycleId"]
    assert payload["observationId"].startswith("ams-observation-")


def test_ineligible_active_market_has_explicit_reason_and_no_score():
    validation, _ = service(active="XRPUSDT")

    payload = validation.observe().to_dict()

    assert payload["activeMarketScore"] is None
    assert "ACTIVE_MARKET_NOT_IN_UNIVERSE" in payload["reasonCodes"]


def test_capital_ineligible_active_market_uses_same_cycle_comparison_score():
    session = Session([
        Response({"code": "200000", "data": [
            contract_payload(),
            contract_payload(
                symbol="XRPUSDTM", baseCurrency="XRP", multiplier="1",
                lotSize=100000, lastTradePrice="1",
            ),
        ]}),
        Response({"code": "200000", "data": [
            ticker_payload(),
            ticker_payload(
                symbol="XRPUSDTM", price="1", bestBidPrice="0.99",
                bestAskPrice="1.01", bestBidSize="10", bestAskSize="10",
            ),
        ]}),
    ])
    validation, _ = service(session=session, active="XRPUSDT")

    payload = validation.observe().to_dict()

    assert payload["activeSymbol"] == "XRPUSDT"
    assert payload["activeMarketScore"] is not None
    assert payload["candidateScore"] is not None
    assert all(
        item["symbol"] != "XRPUSDT" for item in payload["rankedCandidates"]
    )
    assert payload["eligibleCount"] == 1 and payload["rejectedCount"] == 1
    assert "ACTIVE_MARKET_NOT_SCANNER_ELIGIBLE" not in payload["reasonCodes"]



def test_preflight_blocks_before_public_network_and_preserves_active_authority():
    for key, unsafe in (
        ("realOrderAllowed", True), ("dryRun", False),
        ("executionRealOrderDisabled", False),
        ("autoTradeDisabled", False), ("liveAutoSwitchDisabled", False),
        ("emergencyAvailable", False), ("governanceAvailable", False),
    ):
        state = {**SAFETY, key: unsafe}
        validation, session = service(safety=state)
        with pytest.raises(RuntimeError, match="LIVE_READ_ONLY_PREFLIGHT_BLOCKED"):
            validation.observe()
        assert session.calls == []


def test_no_eligible_market_is_previewed_without_fallback_or_switch():
    session = Session([
        Response({"code": "200000", "data": [contract_payload(lotSize=None)]}),
        Response({"code": "200000", "data": [ticker_payload()]}),
    ])
    validation, _ = service(session=session)
    payload = validation.observe().to_dict()
    assert payload["eligibleCount"] == 0
    assert payload["topCandidate"] is None and payload["proposedSymbol"] is None
    assert payload["switchEligiblePreview"] is False
    assert payload["activeSymbol"] == "ETHUSDT" and payload["actualSwitch"] is False
    assert payload["observationId"] is None


@pytest.mark.parametrize("response,error", [
    (requests.Timeout(), "KUCOIN_PUBLIC_MARKET_UNAVAILABLE"),
    (Response({}, status=503), "KUCOIN_PUBLIC_MARKET_UNAVAILABLE"),
    (Response({"code": "400000", "data": []}), "KUCOIN_PUBLIC_RESPONSE_INVALID"),
    (Response({"code": "200000", "data": []}), "KUCOIN_PUBLIC_DATA_EMPTY"),
])
def test_network_and_response_failures_are_fail_closed(response, error):
    validation, _ = service(session=Session([response]))
    with pytest.raises(KucoinPublicMarketError, match=error):
        validation.observe()


def test_partial_malformed_or_crossed_ticker_is_rejected_not_ranked():
    for ticker in (
        ticker_payload(bestBidPrice=None),
        ticker_payload(bestBidPrice="60002", bestAskPrice="60001"),
    ):
        session = Session([
            Response({"code": "200000", "data": [contract_payload()]}),
            Response({"code": "200000", "data": [ticker]}),
        ])
        validation, _ = service(session=session)
        result = validation.observe().to_dict()
        assert result["eligibleCount"] == 0
        assert result["topCandidate"] is None and result["actualSwitch"] is False


def test_twenty_mock_observations_are_stable_rate_controlled_by_caller():
    responses = []
    for _ in range(20):
        responses.extend([
            Response({"code": "200000", "data": [contract_payload()]}),
            Response({"code": "200000", "data": [ticker_payload()]}),
        ])
    validation, session = service(session=Session(responses))
    active = "ETHUSDT"
    results = [validation.observe().to_dict() for _ in range(20)]
    assert len(results) == 20 and len(session.calls) == 40
    assert {item["activeSymbol"] for item in results} == {active}
    assert {item["topCandidate"] for item in results} == {"BTCUSDT"}
    assert all(not item["actualSwitch"] and not item["realOrderCreated"] for item in results)


def test_live_bot_manager_switch_adapter_rejects_commit():
    from backend.auto_market_selection import BotManagerSwitchRuntime, PreparedFeed

    class Manager:
        config = {"mode": "live", "dry_run": True, "realOrderAllowed": False}
        activeSymbol = "ETHUSDT"

        def _commit_active_symbol_for_safe_switch(self, *args):
            raise AssertionError("Live commit boundary called")

    manager = Manager()
    adapter = BotManagerSwitchRuntime(
        manager, position_provider=lambda: "FLAT", mm_provider=lambda: None,
        emergency_provider=lambda: True,
    )
    handle = PreparedFeed(object(), "runtime-new", object(), "runtime-old",
                          "BTCUSDT", "XBTUSDTM")
    assert adapter.commit_active_symbol("ETHUSDT", "BTCUSDT", handle, "tx") is False
    assert manager.activeSymbol == "ETHUSDT"


def test_observation_contains_no_credentials_or_action_surface():
    validation, _ = service()
    payload = validation.observe().to_dict()
    serialized = str(payload).lower()
    assert all(term not in serialized for term in (
        "apikey", "api_key", "secret", "passphrase", "token", "credential",
    ))
    source = __import__(
        "backend.auto_market_selection.live_read_only", fromlist=["x"]
    ).__file__
    text = open(source, encoding="utf-8").read()
    assert all(term not in text for term in (
        "SafeSymbolSwitch", "execute_safe_switch", "create_order", "submit_order",
        "realOrderAllowed =", ".activeSymbol =",
    ))


def test_dashboard_labels_observation_live_read_only_not_auto_live():
    from backend.auto_market_selection import build_auto_market_selection_status

    validation, _ = service()
    observation = validation.observe()
    status = build_auto_market_selection_status(
        active_symbol="ETHUSDT", live_observation=observation,
    )
    assert status["autoRuntime"]["mode"] == "LIVE_READ_ONLY"
    assert status["autoRuntime"]["runtimeState"] == "OBSERVING"
    assert status["activeSymbol"] == "ETHUSDT"
    assert status["liveReadOnly"]["topCandidate"] == "BTCUSDT"
    assert "AUTO_LIVE" not in str(status)
