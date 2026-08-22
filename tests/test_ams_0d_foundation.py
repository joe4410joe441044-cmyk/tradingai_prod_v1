from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import requests

from backend.market.kucoin_futures_public import (
    KucoinFuturesPublicClient, KucoinMarketUniverseCache,
    KucoinPublicMarketError, canonicalize_futures_symbol,
    to_kucoin_futures_symbol,
)
from backend.money_management.capital_eligibility import (
    build_capital_eligibility_contract, evaluate_market_capital_eligibility,
)


NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("failed")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def contract_payload(**changes):
    value = {
        "symbol": "XBTUSDTM", "baseCurrency": "XBT",
        "quoteCurrency": "USDT", "settleCurrency": "USDT",
        "type": "FFWCSX", "status": "Open", "multiplier": "0.001",
        "lotSize": 1, "tickSize": "0.1", "makerFeeRate": "0.0002",
        "takerFeeRate": "0.0006", "maxLeverage": 100,
        "initialMargin": "0.01", "maintainMargin": "0.005",
        "lastTradePrice": "60000",
    }
    value.update(changes)
    return value


def client_for(payload):
    return KucoinFuturesPublicClient(
        session=Session([Response(payload)]), timeout=2,
    )


def capital(**changes):
    values = dict(
        equity=Decimal("1000"), available_capital=Decimal("900"),
        risk_budget=Decimal("4.5"), max_position_notional=Decimal("100"),
        total_exposure_percent=Decimal("20"), open_exposure=Decimal("0"),
        position_count=0, pending_order_count=0, mm_regime="NORMAL",
        policy_version="money-management-http/v1:1", evaluated_at=NOW,
    )
    values.update(changes)
    return build_capital_eligibility_contract(**values)


def test_public_client_needs_no_credentials_and_parses_authoritative_metadata():
    session = Session([Response({"code": "200000", "data": [contract_payload()]})])
    client = KucoinFuturesPublicClient(session=session, timeout=2)
    item = client.get_active_contracts(evaluated_at=NOW)[0]
    assert item.canonical_symbol == "BTCUSDT"
    assert item.exchange_symbol == "XBTUSDTM"
    assert item.contract_multiplier == Decimal("0.001")
    assert item.minimum_quantity == Decimal("1")
    assert item.minimum_notional is None
    assert session.calls[0][1] == 2


@pytest.mark.parametrize("payload", [
    {"code": "400000", "data": []}, {"code": "200000", "data": []},
    {"code": "200000", "data": [{}]}, ValueError("bad json"),
])
def test_universe_bad_responses_fail_closed(payload):
    with pytest.raises(KucoinPublicMarketError):
        client_for(payload).get_active_contracts(evaluated_at=NOW)


def test_only_explicit_open_contracts_are_tradable():
    data = [contract_payload(symbol="ETHUSDTM", status="Closed"), contract_payload()]
    result = client_for({"code": "200000", "data": data}).get_active_contracts(evaluated_at=NOW)
    assert [item.exchange_symbol for item in result] == ["XBTUSDTM"]


def test_symbol_normalization_has_one_bidirectional_authority():
    assert canonicalize_futures_symbol("XBTUSDTM") == "BTCUSDT"
    assert to_kucoin_futures_symbol("BTCUSDT") == "XBTUSDTM"
    assert to_kucoin_futures_symbol("XRPUSDTM") == "XRPUSDTM"


def test_cache_retains_last_good_but_marks_it_stale_and_failed_refresh_does_not_replace_it():
    clock = [NOW]
    session = Session([
        Response({"code": "200000", "data": [contract_payload()]}),
        requests.Timeout(),
    ])
    cache = KucoinMarketUniverseCache(
        KucoinFuturesPublicClient(session=session), ttl=timedelta(minutes=1),
        clock=lambda: clock[0],
    )
    assert cache.refresh().freshness == "FRESH"
    clock[0] += timedelta(minutes=2)
    assert cache.get().freshness == "STALE"
    with pytest.raises(KucoinPublicMarketError):
        cache.refresh()
    assert cache.get().freshness == "STALE"


def test_all_tickers_is_one_lightweight_request_and_does_not_create_websockets():
    session = Session([Response({"code": "200000", "data": [{
        "symbol": "XBTUSDTM", "price": "60000", "bestBidPrice": "59999",
        "bestAskPrice": "60001", "bestBidSize": 5, "bestAskSize": 7,
        "ts": 123,
    }]})])
    ticker = KucoinFuturesPublicClient(session=session).get_all_tickers()[0]
    assert ticker.last_price == Decimal("60000")
    assert ticker.volume_activity is None
    assert len(session.calls) == 1
    assert session.calls[0][0].endswith("/api/v1/allTickers")


def test_capital_contract_units_capacity_and_unimplemented_policies_are_explicit():
    result = capital(open_exposure=Decimal("25"))
    assert result.max_total_exposure == Decimal("200")
    assert result.remaining_exposure == Decimal("175")
    assert result.to_dict()["totalExposurePercent"] == "20"
    assert result.to_dict()["maxTotalExposureAmount"] == "200"
    assert result.to_dict()["remainingExposureAmount"] == "175"
    assert result.executable_max_concurrent_positions == 1
    assert result.remaining_position_capacity == 1
    assert result.ruin_guard_status == "UNAVAILABLE"
    assert result.compounding_enabled is False
    assert result.mm_mode == "MANUAL"


def test_occupied_or_unknown_position_state_fails_capacity_safely():
    assert capital(position_count=1).remaining_position_capacity == 0
    assert capital(pending_order_count=1).remaining_position_capacity == 0
    assert capital(position_count=None).remaining_position_capacity is None
    assert capital(position_count=-1).remaining_position_capacity is None
    assert capital(authority_fresh=False).remaining_position_capacity is None


def test_stale_or_locked_mm_authority_is_not_market_eligible():
    metadata = client_for({"code": "200000", "data": [contract_payload()]}).get_active_contracts(evaluated_at=NOW)[0]
    for authority, reason in (
        (capital(authority_fresh=False), "CAPITAL_AUTHORITY_STALE"),
        (capital(execution_entry_allowed=False), "MM_ENTRY_LOCKED"),
    ):
        result = evaluate_market_capital_eligibility(
            metadata, authority, stop_loss_percent=Decimal("1"),
            effective_cost_percent=Decimal("0.2"), risk_percent=Decimal("0.5"),
            evaluated_at=NOW,
        )
        assert not result.eligible
        assert reason in result.reason_codes


def test_market_eligibility_reuses_sizing_and_never_creates_order():
    metadata = client_for({"code": "200000", "data": [contract_payload()]}).get_active_contracts(evaluated_at=NOW)[0]
    result = evaluate_market_capital_eligibility(
        metadata, capital(), stop_loss_percent=Decimal("1"),
        effective_cost_percent=Decimal("0.2"), risk_percent=Decimal("0.5"),
        evaluated_at=NOW,
    )
    payload = result.to_dict()
    assert result.calculation_allowed
    assert result.position_feasible
    assert result.approved_quantity_preview == Decimal("1")
    assert payload["orderCreated"] is False
    assert payload["sizingStage"] == "PRE_SELECTION_ELIGIBILITY"


def test_incomplete_market_metadata_is_ineligible_not_fabricated():
    metadata = client_for({"code": "200000", "data": [contract_payload(lotSize=None)]}).get_active_contracts(evaluated_at=NOW)[0]
    result = evaluate_market_capital_eligibility(
        metadata, capital(), stop_loss_percent=Decimal("1"),
        effective_cost_percent=Decimal("0.2"), risk_percent=Decimal("0.5"),
        evaluated_at=NOW,
    )
    assert not result.eligible
    assert "MARKET_METADATA_INCOMPLETE" in result.reason_codes


@pytest.mark.parametrize("metadata_at", [
    NOW - timedelta(minutes=5),
    NOW + timedelta(minutes=5),
])
def test_metadata_freshness_is_independent_of_capital_ordering(metadata_at):
    metadata = client_for({"code": "200000", "data": [contract_payload()]}).get_active_contracts(evaluated_at=metadata_at)[0]
    result = evaluate_market_capital_eligibility(
        metadata, capital(evaluated_at=NOW),
        stop_loss_percent=Decimal("1"), effective_cost_percent=Decimal("0.2"),
        risk_percent=Decimal("0.5"),
        evaluated_at=NOW + timedelta(minutes=5),
    )
    assert "MARKET_METADATA_STALE" not in result.reason_codes


def test_stale_metadata_is_not_fresh_eligibility_authority():
    metadata = client_for({"code": "200000", "data": [contract_payload()]}).get_active_contracts(evaluated_at=NOW)[0]
    result = evaluate_market_capital_eligibility(
        metadata, capital(evaluated_at=NOW + timedelta(minutes=20)),
        stop_loss_percent=Decimal("1"), effective_cost_percent=Decimal("0.2"),
        risk_percent=Decimal("0.5"),
        evaluated_at=NOW + timedelta(minutes=16),
    )
    assert not result.eligible
    assert "MARKET_METADATA_STALE" in result.reason_codes


def test_materially_future_metadata_fails_closed_but_small_skew_is_allowed():
    for offset, expected_stale in (
        (timedelta(milliseconds=500), False),
        (timedelta(seconds=2), True),
    ):
        metadata = client_for({"code": "200000", "data": [contract_payload()]}).get_active_contracts(evaluated_at=NOW + offset)[0]
        result = evaluate_market_capital_eligibility(
            metadata, capital(), stop_loss_percent=Decimal("1"),
            effective_cost_percent=Decimal("0.2"), risk_percent=Decimal("0.5"),
            evaluated_at=NOW,
        )
        assert ("MARKET_METADATA_STALE" in result.reason_codes) is expected_stale


def test_mm_status_preserves_legacy_exposure_field_and_adds_explicit_units():
    from tests.test_money_management_api import ready_boundary

    payload = ready_boundary()[0].get_status().to_dict()
    assert payload["metrics"]["exposureLimit"] == "20"
    assert payload["metrics"]["totalExposurePercent"] == "20"
    assert payload["metrics"]["maxTotalExposureAmount"] == "200"
    assert payload["metrics"]["remainingExposureAmount"] == "200"
    assert payload["capitalEligibility"]["capitalAuthority"] == "MONEY_MANAGEMENT"
