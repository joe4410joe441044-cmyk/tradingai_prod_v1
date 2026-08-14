from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.auto_market_selection import (
    LiveCalibrationCampaign, LiveReadOnlyObservation, analyze_calibration,
    simulate_hypothetical_switches,
)
from tests.test_ams_5b_live_read_only import service


NOW = datetime(2026, 8, 9, 4, tzinfo=timezone.utc)


def source(ranked, *, active="BTCUSDT", timestamp="2026-08-09T04:00:00Z"):
    candidates = tuple({"symbol": symbol, "rank": i + 1, "rankingScore": score}
                       for i, (symbol, score) in enumerate(ranked))
    top5 = tuple({**item, "spreadPercent": "0.1", "topBookLiquidity": "10",
                  "activityMetric": None, "effectiveWeights": {}} for item in candidates[:5])
    return LiveReadOnlyObservation(
        timestamp, len(ranked), len(ranked), len(ranked), 0, len(ranked), len(ranked), 0,
        top5, ranked[0][1] if ranked else None, active,
        ranked[0][0] if ranked else None, ranked[0][0] if ranked else None, True,
        (), (), "scan", "rank", "audit", "proposal", candidates,
        timestamp, timestamp, timestamp,
    )


class Validation:
    def __init__(self, values): self.values = iter(values)
    def observe(self):
        value = next(self.values)
        if isinstance(value, Exception): raise value
        return value


def campaign(values):
    validation, _ = service()
    validation.observe = Validation(values).observe
    moments = iter(NOW + timedelta(seconds=i * 5) for i in range(len(values) * 2 + 2))
    ticks = iter(float(i) for i in range(len(values) * 2 + 2))
    return LiveCalibrationCampaign(validation, clock=lambda: next(moments),
                                   monotonic_clock=lambda: next(ticks), sleeper=lambda _: None)


def test_observation_is_deterministic_and_active_uses_same_ranked_contract():
    value = source((("ETHUSDT", "0.9"), ("BTCUSDT", "0.6")))
    record = campaign((value,)).observe_once()
    assert record.observation_id == "ams-6b-000001"
    assert record.active_symbol_rank == 2
    assert record.active_symbol_score == Decimal("0.6")
    assert record.top_candidate_score == Decimal("0.9")
    assert record.score_advantage == Decimal("0.3")
    assert record.universe_evaluated_at == value.universe_evaluated_at


def test_unrankable_active_has_null_advantage_and_explicit_reason():
    record = campaign((source((("ETHUSDT", "0.9"),), active="BTCUSDT"),)).observe_once()
    assert record.active_symbol_rank is None and record.score_advantage is None
    assert "CURRENT_ACTIVE_NOT_RANKABLE" in record.reason_codes


def test_consecutive_wins_transitions_and_dwell_are_tracked():
    values = tuple(source(((symbol, "0.9"), ("BTCUSDT", "0.5")))
                   for symbol in ("ETHUSDT", "ETHUSDT", "SOLUSDT"))
    records = campaign(values).run(3, interval_seconds=30)
    assert [item.consecutive_top_candidate_wins for item in records] == [1, 2, 1]
    assert records[2].top_candidate_changed is True
    result = analyze_calibration(records)
    assert result["topChanges"] == 1 and len(result["transitions"]) == 1
    assert result["dwell"]["max"] == Decimal("10.0")


def test_a_b_a_oscillation_and_stability_metrics_are_detected():
    symbols = ("AUSDT", "BUSDT", "AUSDT", "BUSDT")
    values = tuple(source(((symbol, "0.9"), ("BTCUSDT", "0.5"),
                           ("ETHUSDT", "0.4"), ("SOLUSDT", "0.3"))) for symbol in symbols)
    result = analyze_calibration(campaign(values).run(4, interval_seconds=30))
    assert result["oscillationCount"] == 2
    assert result["oscillationPatterns"] == ("AUSDT-BUSDT-AUSDT", "BUSDT-AUSDT-BUSDT")
    assert result["top1ChangeRate"] == Decimal("1")
    assert result["top3MembershipChangeRate"] == Decimal("1")
    assert result["top5MembershipChangeRate"] == Decimal("1")


def test_score_distributions_use_interpolated_percentiles():
    values = tuple(source((("ETHUSDT", str(score)), ("BTCUSDT", "0")))
                   for score in (1, 2, 3, 4, 5))
    result = analyze_calibration(campaign(values).run(5, interval_seconds=0))
    assert result["scoreAdvantage"] == {
        "min": Decimal("1"), "p10": Decimal("1.40"), "p25": Decimal("2.00"),
        "median": Decimal("3.0"), "p75": Decimal("4.00"),
        "p90": Decimal("4.60"), "p95": Decimal("4.80"), "max": Decimal("5"),
    }
    assert result["top1VsTop2"]["median"] == Decimal("3.0")


def test_extended_run_dwell_and_grid_statistics_do_not_mutate_runtime():
    from backend.auto_market_selection import simulate_anti_flapping_grid
    values = tuple(source(((symbol, "0.9"), ("BTCUSDT", "0.4")))
                   for symbol in ("AUSDT",)*4 + ("BUSDT",)*2 + ("AUSDT",)*5)
    records = campaign(values).run(len(values), interval_seconds=0)
    analysis = analyze_calibration(records)
    assert analysis["runLength"]["min"] == 2
    assert analysis["runLength"]["max"] == 5
    assert analysis["rightCensoredRun"] is True
    assert analysis["oscillationCount"] == 1
    grid = simulate_anti_flapping_grid(
        records, score_advantages=("0.40",), consecutive_wins=(3, 5),
        active_durations=(10,), cooldowns=(30, 60),
    )
    assert len(grid) == 4
    assert all(item["runtimeMutationCount"] == 0 for item in grid)


def test_network_failure_is_missing_and_never_reuses_previous_top():
    from backend.market.kucoin_futures_public import KucoinPublicMarketError
    values = (source((("ETHUSDT", "0.9"),)),
              KucoinPublicMarketError("KUCOIN_PUBLIC_MARKET_UNAVAILABLE"))
    records = campaign(values).run(2, interval_seconds=0)
    assert records[1].missing is True and records[1].top_candidate_symbol is None
    assert "OBSERVATION_MISSING" in records[1].reason_codes
    assert analyze_calibration(records)["networkFailures"] == 1


def test_hypothetical_simulation_has_flags_only_and_no_action():
    values = tuple(source((("ETHUSDT", "0.9"), ("BTCUSDT", "0.5"))) for _ in range(3))
    records = campaign(values).run(3, interval_seconds=0)
    result = simulate_hypothetical_switches(
        records, minimum_score_advantage="0.3", required_consecutive_wins=2,
        minimum_active_duration="5",
    )
    assert [item["wouldSwitch"] for item in result] == [False, True, True]
    assert all(set(item) == {"observationId", "wouldSwitch"} for item in result)
    serialized = str([item.to_dict() for item in records]).lower()
    assert "credential" not in serialized
    assert all(not item.to_dict()["actualSwitch"] and not item.to_dict()["realOrderCreated"]
               for item in records)
