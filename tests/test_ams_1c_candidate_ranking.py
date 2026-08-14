from dataclasses import replace
from decimal import Decimal
import inspect

from backend.auto_market_selection.candidate_ranking import (
    CandidateRankingEngine, RANKING_CONTRACT_VERSION, RankingReason,
    RankingStatus,
)
from backend.auto_market_selection.market_scanner import (
    MarketScanner, ScannerRejectionReason,
)
from tests.test_ams_1a_market_scanner import metadata, scanner_input, ticker


def ranked_source(rows):
    contracts, tickers = [], []
    for symbol, exchange, spread, bid_size, ask_size, activity in rows:
        contracts.append(metadata(symbol, exchange, base_currency=symbol[:-4]))
        mid = Decimal("100")
        tickers.append(ticker(
            exchange, best_bid=mid - spread / 2, best_ask=mid + spread / 2,
            bid_size=bid_size, ask_size=ask_size, volume_activity=activity,
        ))
    return scanner_input(contracts=contracts, tickers=tickers)


def run(rows):
    scan = MarketScanner().scan(ranked_source(rows))
    return scan, CandidateRankingEngine().rank(scan)


def row(symbol="BTCUSDT", exchange="XBTUSDTM", spread="2", bid="5", ask="7",
        activity=None):
    return (symbol, exchange, Decimal(spread), Decimal(bid), Decimal(ask),
            Decimal(activity) if activity is not None else None)


def by_symbol(result, symbol):
    return next(item for item in result.ranked_candidates if item.symbol == symbol)


def test_lower_spread_and_higher_balanced_liquidity_normalize_better():
    _, result = run([
        row(), row("ETHUSDT", "ETHUSDTM", "4", "10", "10"),
    ])
    btc, eth = by_symbol(result, "BTCUSDT"), by_symbol(result, "ETHUSDT")
    assert btc.ranking_features.spread_score == Decimal("1")
    assert eth.ranking_features.spread_score == Decimal("0")
    assert btc.ranking_features.liquidity_score == Decimal("0")
    assert eth.ranking_features.liquidity_score == Decimal("1")


def test_unbalanced_book_uses_smaller_side():
    _, result = run([
        row(bid="100", ask="2"),
        row("ETHUSDT", "ETHUSDTM", bid="5", ask="5"),
    ])
    assert by_symbol(result, "BTCUSDT").ranking_features.raw_top_book_liquidity == 2
    assert by_symbol(result, "ETHUSDT").ranking_features.raw_top_book_liquidity == 5


def test_activity_is_included_when_present_and_missing_is_not_zero():
    _, result = run([
        row(activity="10"), row("ETHUSDT", "ETHUSDTM", activity=None),
    ])
    btc, eth = by_symbol(result, "BTCUSDT"), by_symbol(result, "ETHUSDT")
    assert btc.ranking_features.activity_score == Decimal("1")
    assert btc.ranking_features.effective_weights.activity == Decimal("0.20") / Decimal("0.90")
    assert eth.ranking_features.raw_activity_metric is None
    assert eth.ranking_features.activity_score is None
    assert eth.ranking_features.effective_weights.activity is None
    assert eth.ranking_features.effective_weights.spread == Decimal("0.40") / Decimal("0.70")


def test_missing_required_spread_or_liquidity_fails_closed():
    scan = MarketScanner().scan(scanner_input())
    base = scan.candidates[0]
    for changes in (
        {"spread": None, "spread_percent": None}, {"bid_size": None}, {"ask_size": None},
    ):
        candidate = replace(base, **changes)
        malformed = replace(scan, candidates=(candidate,))
        result = CandidateRankingEngine().rank(malformed)
        assert result.status is RankingStatus.NO_RANKABLE_MARKET
        assert result.evaluated_candidates[0].ranking_reason_codes == (
            RankingReason.RANKING_DATA_INCOMPLETE,
        )


def test_equal_values_and_single_candidate_score_one():
    _, tied = run([row(), row("ETHUSDT", "ETHUSDTM")])
    for item in tied.ranked_candidates:
        assert item.ranking_features.spread_score == 1
        assert item.ranking_features.liquidity_score == 1
        assert item.ranking_score == 1
    _, single = run([row()])
    assert single.ranked_candidates[0].ranking_score == 1
    assert single.ranked_candidates[0].rank == 1
    assert single.top_candidate == single.ranked_candidates[0]


def test_same_input_same_scores_ranks_serialization_and_cycle_id():
    scan = MarketScanner().scan(ranked_source([row(), row("ETHUSDT", "ETHUSDTM")]))
    first = CandidateRankingEngine().rank(scan)
    second = CandidateRankingEngine().rank(scan)
    assert first == second
    assert first.to_dict() == second.to_dict()
    assert first.ranking_cycle_id == second.ranking_cycle_id
    assert first.scanner_cycle_id == scan.scanner_cycle_id


def test_tie_break_lower_spread_then_liquidity_then_symbol():
    _, result = run([
        row(), row("ETHUSDT", "ETHUSDTM"), row("SOLUSDT", "SOLUSDTM"),
    ])
    base = result.ranked_candidates[0]
    score = Decimal("0.5")
    def candidate(symbol, spread, liquidity):
        features = replace(
            base.ranking_features, raw_spread_percent=Decimal(spread),
            raw_top_book_liquidity=Decimal(liquidity),
        )
        return replace(base, symbol=symbol, ranking_features=features,
                       ranking_score=score, rank=None)

    engine = CandidateRankingEngine()
    values = (
        candidate("SOLUSDT", "2", "10"),
        candidate("ETHUSDT", "1", "5"),
        candidate("BTCUSDT", "1", "5"),
        candidate("XRPUSDT", "1", "8"),
    )
    ordered = sorted(values, key=engine._sort_key)
    assert [item.symbol for item in ordered] == [
        "XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT",
    ]


def test_rank_top_candidate_and_no_external_mutation():
    scan = MarketScanner().scan(ranked_source([row(), row("ETHUSDT", "ETHUSDTM", spread="3")]))
    before = scan.to_dict()
    result = CandidateRankingEngine().rank(scan)
    assert [item.rank for item in result.ranked_candidates] == [1, 2]
    assert result.top_candidate.rank == 1
    assert scan.to_dict() == before


def test_no_candidate_and_scanner_rejection_never_return():
    source = scanner_input(tickers=[ticker(best_bid=Decimal("2"), best_ask=Decimal("1"))])
    scan = MarketScanner().scan(source)
    result = CandidateRankingEngine().rank(scan)
    assert scan.rejected_count == 1
    assert result.status is RankingStatus.NO_RANKABLE_MARKET
    assert result.ranked_candidates == () and result.top_candidate is None


def test_capital_is_gate_not_score():
    scan = MarketScanner().scan(scanner_input())
    blocked = replace(scan.candidates[0], capital_eligible=False)
    result = CandidateRankingEngine().rank(replace(scan, candidates=(blocked,)))
    assert result.ranked_candidates == ()
    source = inspect.getsource(CandidateRankingEngine)
    assert "risk_budget" not in source and "available_capital" not in source


def test_active_outside_ranking_gets_same_cycle_comparison_without_eligibility():
    scan = MarketScanner().scan(ranked_source([
        row("BTCUSDT", "XBTUSDTM", spread="1", bid="8", ask="8"),
        row("ETHUSDT", "ETHUSDTM", spread="3", bid="4", ask="4"),
        row("XRPUSDT", "XRPUSDTM", spread="2", bid="6", ask="6"),
    ]))
    active = next(item for item in scan.candidates if item.symbol == "XRPUSDT")
    active = replace(
        active, scanner_eligible=False, capital_eligible=False,
        rejection_reasons=(ScannerRejectionReason.CAPITAL_INELIGIBLE,),
        capital_reason_codes=("MINIMUM_ORDER_NOT_FEASIBLE", "POSITION_SIZE_ZERO"),
    )
    scan = replace(
        scan,
        candidates=tuple(item for item in scan.candidates if item.symbol != "XRPUSDT"),
        rejections=(active,), eligible_count=2, rejected_count=1,
    )
    engine = CandidateRankingEngine()
    ranking = engine.rank(scan)

    comparison = engine.compare_active_market(scan, ranking, "XRPUSDT")

    assert comparison.unavailable_reason is None
    assert comparison.candidate_symbol == ranking.top_candidate.symbol == "BTCUSDT"
    assert isinstance(comparison.candidate_score, Decimal)
    assert isinstance(comparison.active_market_score, Decimal)
    assert comparison.candidate_score - comparison.active_market_score == Decimal("0.5")
    assert comparison.scanner_cycle_id == scan.scanner_cycle_id
    assert comparison.ranking_cycle_id == ranking.ranking_cycle_id
    assert comparison.ranking_contract_version == RANKING_CONTRACT_VERSION
    assert comparison.comparison_id.startswith("ams-score-comparison-")
    assert all(item.symbol != "XRPUSDT" for item in ranking.ranked_candidates)
    assert active.scanner_eligible is False and active.capital_eligible is False


def test_active_comparison_fails_closed_on_cycle_contract_and_feature_mismatch():
    scan, ranking = run([
        row(), row("ETHUSDT", "ETHUSDTM", spread="4", bid="10", ask="10"),
    ])
    engine = CandidateRankingEngine()
    assert engine.compare_active_market(
        scan, replace(ranking, scanner_cycle_id="other"), "BTCUSDT",
    ).unavailable_reason == "SCANNER_RANKING_CYCLE_MISMATCH"
    assert engine.compare_active_market(
        scan, replace(ranking, ranking_contract_version="other"), "BTCUSDT",
    ).unavailable_reason == "RANKING_CONTRACT_MISMATCH"
    changed_source = replace(
        scan.candidates[0], bid_size=scan.candidates[0].bid_size + Decimal("1"),
    )
    changed_scan = replace(scan, candidates=(changed_source, scan.candidates[1]))
    assert engine.compare_active_market(
        changed_scan, ranking, "BTCUSDT",
    ).unavailable_reason == "CANDIDATE_FEATURE_SNAPSHOT_MISMATCH"
    assert engine.compare_active_market(
        scan, ranking, "XRPUSDT",
    ).unavailable_reason == "ACTIVE_MARKET_NOT_IN_SCANNER_CYCLE"

    active = replace(
        scan.candidates[0], bid_size=None, scanner_eligible=False,
        capital_eligible=False,
        rejection_reasons=(ScannerRejectionReason.CAPITAL_INELIGIBLE,),
    )
    malformed = replace(
        scan, candidates=(scan.candidates[1],), rejections=(active,),
        eligible_count=1, rejected_count=1,
    )
    malformed_ranking = engine.rank(malformed)
    assert engine.compare_active_market(
        malformed, malformed_ranking, active.symbol,
    ).unavailable_reason == "ACTIVE_MARKET_RANKING_DATA_INCOMPLETE"


def test_audit_serialization_retains_raw_scores_weights_and_rank():
    _, result = run([row(activity="3")])
    payload = result.to_dict()["rankedCandidates"][0]
    features = payload["rankingFeatures"]
    assert features["rawSpreadPercent"] is not None
    assert features["spreadScore"] == "1"
    assert features["rawTopBookLiquidity"] == "5"
    assert features["liquidityScore"] == "1"
    assert features["rawActivityMetric"] == "3"
    assert features["activityScore"] == "1"
    assert features["effectiveWeights"]["dataQuality"] is None
    assert payload["rankingScore"] == "1"
    assert payload["rank"] == 1


def test_no_deep_analysis_activation_or_trading_dependencies():
    from backend.auto_market_selection import candidate_ranking

    source = inspect.getsource(candidate_ranking)
    forbidden = (
        "WebSocket", "subscribe", "Strategy", "backend.ai", "create_order",
        "submit_order", "activeSymbol", "realOrderAllowed", "dryRun",
    )
    assert all(term not in source for term in forbidden)
