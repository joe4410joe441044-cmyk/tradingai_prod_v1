from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.auto_market_selection.market_scanner import (
    MarketScanner, ScannerInput, ScannerRejectionReason, ScannerStatus,
    TickerSnapshot,
)
from backend.market.kucoin_futures_public import (
    FuturesContractMetadata, FuturesTicker, MarketUniverseSnapshot,
)
from backend.money_management.capital_eligibility import (
    PerMarketEligibilityResult, build_capital_eligibility_contract,
)


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


def metadata(symbol="BTCUSDT", exchange_symbol="XBTUSDTM", **changes):
    value = FuturesContractMetadata(
        symbol, exchange_symbol, "XBT", "USDT", "USDT", "FFWCSX", "Open",
        Decimal("0.001"), Decimal("1"), Decimal("1"), None,
        Decimal("0.1"), Decimal("0.0002"), Decimal("0.0006"), Decimal("100"),
        {"initialMargin": Decimal("0.01")}, Decimal("60000"), NOW,
    )
    return replace(value, **changes)


def ticker(exchange_symbol="XBTUSDTM", **changes):
    value = FuturesTicker(
        exchange_symbol, Decimal("60000"), Decimal("59999"), Decimal("60001"),
        Decimal("5"), Decimal("7"), None, 1,
    )
    return replace(value, **changes)


def capital(**changes):
    values = dict(
        equity=Decimal("1000"), available_capital=Decimal("900"),
        risk_budget=Decimal("4.5"), max_position_notional=Decimal("100"),
        total_exposure_percent=Decimal("20"), open_exposure=Decimal("0"),
        position_count=0, pending_order_count=0, mm_regime="NORMAL",
        policy_version="test/v1", evaluated_at=NOW,
    )
    values.update(changes)
    return build_capital_eligibility_contract(**values)


def eligibility(item, authority, *, eligible=True, reasons=()):
    return PerMarketEligibilityResult(
        item.canonical_symbol, eligible, eligible, eligible,
        Decimal("1") if eligible else None, tuple(reasons), "MONEY_MANAGEMENT",
        authority.risk_budget, authority.remaining_exposure,
        authority.remaining_position_capacity, item.metadata_evaluated_at,
        authority.evaluated_at,
    )


def scanner_input(*, contracts=None, tickers=None, authority=None,
                  eligibility_map=None, universe_freshness="FRESH",
                  ticker_freshness="FRESH", evaluated_at=NOW):
    contracts = tuple(contracts if contracts is not None else [metadata()])
    tickers = tuple(tickers if tickers is not None else [ticker()])
    authority = capital() if authority is None else authority
    if eligibility_map is None:
        eligibility_map = {
            item.canonical_symbol: eligibility(item, authority) for item in contracts
        }
    return ScannerInput(
        MarketUniverseSnapshot(contracts, NOW, universe_freshness),
        TickerSnapshot(tickers, NOW, ticker_freshness), authority,
        eligibility_map, evaluated_at,
    )


def reason_values(result):
    return {reason.value for reason in result.rejections[0].rejection_reasons}


def test_same_input_is_deterministic_and_serializable():
    source = scanner_input()
    first = MarketScanner().scan(source)
    second = MarketScanner().scan(source)
    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.status is ScannerStatus.CANDIDATES_AVAILABLE
    assert first.eligible_count == 1
    assert first.candidates[0].spread == Decimal("2")
    assert first.candidates[0].activity_metric is None
    assert first.candidates[0].to_dict()["activityMetric"] is None


def test_order_is_canonical_symbol_ascending_not_ranking():
    eth = metadata("ETHUSDT", "ETHUSDTM", base_currency="ETH")
    btc = metadata()
    source = scanner_input(
        contracts=[eth, btc], tickers=[ticker("ETHUSDTM"), ticker()],
    )
    result = MarketScanner().scan(source)
    assert [item.symbol for item in result.candidates] == ["BTCUSDT", "ETHUSDT"]


def test_non_tradable_and_incomplete_metadata_fail_closed():
    item = metadata(tradable_status="Closed", tick_size=None)
    result = MarketScanner().scan(scanner_input(contracts=[item]))
    assert {"NOT_TRADABLE", "METADATA_INCOMPLETE"} <= reason_values(result)


def test_stale_universe_rejects_every_market():
    result = MarketScanner().scan(scanner_input(universe_freshness="STALE"))
    assert "UNIVERSE_STALE" in reason_values(result)


def test_stale_or_missing_ticker_and_invalid_book_fail_closed():
    stale = MarketScanner().scan(scanner_input(ticker_freshness="STALE"))
    missing = MarketScanner().scan(scanner_input(tickers=[]))
    invalid = MarketScanner().scan(scanner_input(
        tickers=[ticker(best_bid=Decimal("60002"), best_ask=Decimal("60001"))],
    ))
    assert "TICKER_STALE" in reason_values(stale)
    assert "TICKER_UNAVAILABLE" in reason_values(missing)
    assert "INVALID_BID_ASK" in reason_values(invalid)
    assert invalid.rejections[0].spread is None


def test_mm_unavailable_stale_and_locked_fail_closed():
    base = scanner_input()
    unavailable = MarketScanner().scan(replace(base, capital=None))
    stale_capital = capital(authority_fresh=False)
    stale_item = base.universe.contracts[0]
    stale = MarketScanner().scan(replace(
        base, capital=stale_capital,
        per_market_eligibility={stale_item.canonical_symbol: eligibility(
            stale_item, stale_capital, eligible=False,
            reasons=("CAPITAL_AUTHORITY_STALE",),
        )},
    ))
    locked_capital = capital(execution_entry_allowed=False)
    locked = MarketScanner().scan(replace(
        base, capital=locked_capital,
        per_market_eligibility={stale_item.canonical_symbol: eligibility(
            stale_item, locked_capital, eligible=False, reasons=("MM_ENTRY_LOCKED",),
        )},
    ))
    assert "MM_UNAVAILABLE" in reason_values(unavailable)
    assert "MM_STALE" in reason_values(stale)
    assert "MM_LOCKED" in reason_values(locked)


def test_position_capacity_and_other_capital_ineligibility_are_not_recalculated():
    source = scanner_input()
    item, authority = source.universe.contracts[0], source.capital
    exhausted = replace(source, per_market_eligibility={
        item.canonical_symbol: eligibility(
            item, authority, eligible=False, reasons=("POSITION_CAPACITY_EXHAUSTED",),
        )
    })
    generic = replace(source, per_market_eligibility={
        item.canonical_symbol: eligibility(
            item, authority, eligible=False, reasons=("MINIMUM_ORDER_NOT_FEASIBLE",),
        )
    })
    assert {"POSITION_CAPACITY_EXHAUSTED", "CAPITAL_INELIGIBLE"} <= reason_values(
        MarketScanner().scan(exhausted)
    )
    assert "CAPITAL_INELIGIBLE" in reason_values(MarketScanner().scan(generic))


def test_missing_or_stale_per_market_eligibility_fails_closed():
    source = scanner_input(eligibility_map={})
    assert "ELIGIBILITY_UNAVAILABLE" in reason_values(MarketScanner().scan(source))
    item, authority = source.universe.contracts[0], source.capital
    old = replace(eligibility(item, authority), mm_evaluated_at=NOW - timedelta(hours=1))
    result = MarketScanner().scan(replace(source, per_market_eligibility={item.canonical_symbol: old}))
    assert "ELIGIBILITY_STALE" in reason_values(result)


def test_zero_markets_is_explicit_and_unavailable_universe_is_safe():
    empty = scanner_input(contracts=[], tickers=[], eligibility_map={})
    result = MarketScanner().scan(empty)
    assert result.status is ScannerStatus.NO_ELIGIBLE_MARKET
    assert result.evaluated_count == result.eligible_count == 0
    unavailable = MarketScanner().scan(replace(empty, universe=None))
    assert unavailable.status is ScannerStatus.AUTO_SELECTION_UNAVAILABLE
    assert unavailable.global_rejection_reasons == (
        ScannerRejectionReason.UNIVERSE_UNAVAILABLE,
    )


def test_scanner_is_pure_and_has_no_execution_or_feed_dependencies():
    import inspect
    from backend.auto_market_selection import market_scanner

    source = inspect.getsource(market_scanner)
    forbidden = ("WebSocket", "subscribe", "create_order", "activeSymbol",
                 "realOrderAllowed", "dryRun")
    assert all(term not in source for term in forbidden)
