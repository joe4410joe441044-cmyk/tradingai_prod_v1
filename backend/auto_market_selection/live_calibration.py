"""AMS-6B read-only calibration campaign and offline analysis.

This module owns no switch, execution, governance, or configuration surface.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from time import monotonic, sleep
from typing import Mapping, Optional, Tuple

from backend.market.kucoin_futures_public import KucoinPublicMarketError
from .live_read_only import LiveReadOnlyObservation, LiveReadOnlyValidation


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _iso(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


def _decimal(value):
    if value is None:
        return None
    result = Decimal(str(value))
    return result if result.is_finite() else None


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * Decimal(str(percentile))
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def distribution(values):
    numbers = tuple(value for value in values if value is not None)
    if not numbers:
        return {key: None for key in ("min", "p10", "p25", "median", "p75", "p90", "p95", "max")}
    return {
        "min": min(numbers), "p10": _percentile(numbers, Decimal("0.10")),
        "p25": _percentile(numbers, Decimal("0.25")),
        "median": _percentile(numbers, Decimal("0.5")),
        "p75": _percentile(numbers, Decimal("0.75")),
        "p90": _percentile(numbers, Decimal("0.90")),
        "p95": _percentile(numbers, Decimal("0.95")), "max": max(numbers),
    }


@dataclass(frozen=True)
class CalibrationObservation:
    observation_id: str
    observed_at: str
    active_symbol: Optional[str]
    active_symbol_rank: Optional[int]
    active_symbol_score: Optional[Decimal]
    top_candidate_symbol: Optional[str]
    top_candidate_rank: Optional[int]
    top_candidate_score: Optional[Decimal]
    score_advantage: Optional[Decimal]
    top1_vs_top2_difference: Optional[Decimal]
    top5: Tuple[Mapping[str, object], ...]
    ranked_count: int
    eligible_count: int
    rejected_count: int
    previous_top_candidate: Optional[str]
    top_candidate_changed: bool
    consecutive_top_candidate_wins: int
    time_since_last_top_change: Decimal
    time_since_hypothetical_switch: Optional[Decimal]
    universe_evaluated_at: Optional[str]
    ticker_evaluated_at: Optional[str]
    ranking_evaluated_at: Optional[str]
    network_duration: Decimal
    total_observation_duration: Decimal
    reason_codes: Tuple[str, ...]
    missing: bool = False
    universe_count: int = 0
    candidate_dwell_duration: Decimal = Decimal("0")

    def to_dict(self):
        def value(item):
            return format(item, "f") if isinstance(item, Decimal) else item
        return {
            "observationId": self.observation_id, "observedAt": self.observed_at,
            "activeSymbol": self.active_symbol, "activeSymbolRank": self.active_symbol_rank,
            "activeSymbolScore": value(self.active_symbol_score),
            "topCandidateSymbol": self.top_candidate_symbol,
            "topCandidateRank": self.top_candidate_rank,
            "topCandidateScore": value(self.top_candidate_score),
            "scoreAdvantage": value(self.score_advantage),
            "top1VsTop2Difference": value(self.top1_vs_top2_difference),
            "top5": [dict(item) for item in self.top5], "rankedCount": self.ranked_count,
            "eligibleCount": self.eligible_count, "rejectedCount": self.rejected_count,
            "previousTopCandidate": self.previous_top_candidate,
            "topCandidateChanged": self.top_candidate_changed,
            "consecutiveTopCandidateWins": self.consecutive_top_candidate_wins,
            "timeSinceLastTopChange": value(self.time_since_last_top_change),
            "timeSinceHypotheticalSwitch": value(self.time_since_hypothetical_switch),
            "universeEvaluatedAt": self.universe_evaluated_at,
            "tickerEvaluatedAt": self.ticker_evaluated_at,
            "rankingEvaluatedAt": self.ranking_evaluated_at,
            "networkDuration": value(self.network_duration),
            "totalObservationDuration": value(self.total_observation_duration),
            "reasonCodes": list(self.reason_codes), "missing": self.missing,
            "universeCount": self.universe_count,
            "candidateDwellDuration": value(self.candidate_dwell_duration),
            "actualSwitch": False, "safeSwitchCommit": False, "realOrderCreated": False,
        }


class LiveCalibrationCampaign:
    """Stateful observation tracker over the existing read-only validation."""

    def __init__(self, validation, *, clock=None, monotonic_clock=None, sleeper=None):
        if not isinstance(validation, LiveReadOnlyValidation):
            raise TypeError("LiveReadOnlyValidation required")
        self.validation = validation
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic_clock or monotonic
        self.sleeper = sleeper or sleep
        self.records = []
        self._last_top = None
        self._wins = 0
        self._last_change_at = None

    def observe_once(self):
        started_at, started_tick = _utc(self.clock()), self.monotonic()
        try:
            source = self.validation.observe()
        except KucoinPublicMarketError as exc:
            finished_at, elapsed = _utc(self.clock()), Decimal(str(self.monotonic() - started_tick))
            record = CalibrationObservation(
                f"ams-6b-{len(self.records)+1:06d}", _iso(finished_at), None, None, None,
                None, None, None, None, None, (), 0, 0, 0, self._last_top, False, 0,
                Decimal("0"), None, None, None, None, elapsed, elapsed,
                (str(exc), "OBSERVATION_MISSING"), True,
            )
            self.records.append(record)
            return record
        finished_at, elapsed = _utc(self.clock()), Decimal(str(self.monotonic() - started_tick))
        return self._record(source, finished_at, elapsed)

    def _record(self, source, observed_at, elapsed):
        ranked = tuple(source.ranked_candidates)
        by_symbol = {str(item["symbol"]): item for item in ranked}
        active = by_symbol.get(source.active_symbol)
        top = ranked[0] if ranked else None
        top_score = _decimal(top.get("rankingScore")) if top else None
        active_score = _decimal(active.get("rankingScore")) if active else None
        advantage = top_score - active_score if top_score is not None and active_score is not None else None
        top2_score = _decimal(ranked[1].get("rankingScore")) if len(ranked) > 1 else None
        top_difference = top_score - top2_score if top_score is not None and top2_score is not None else None
        symbol = top.get("symbol") if top else None
        changed = self._last_top is not None and symbol != self._last_top
        if symbol is None:
            self._wins = 0
        elif symbol == self._last_top:
            self._wins += 1
        else:
            self._wins = 1
            self._last_change_at = observed_at
        since_change = Decimal("0") if self._last_change_at is None else Decimal(str(
            (observed_at - self._last_change_at).total_seconds()
        ))
        reasons = list(source.reason_codes)
        if source.active_symbol and active is None:
            reasons.append("CURRENT_ACTIVE_NOT_RANKABLE")
        record = CalibrationObservation(
            f"ams-6b-{len(self.records)+1:06d}", _iso(observed_at), source.active_symbol,
            active.get("rank") if active else None, active_score, symbol,
            top.get("rank") if top else None, top_score, advantage, top_difference,
            source.top_five, len(ranked), source.eligible_count, source.rejected_count,
            self._last_top, changed, self._wins, since_change, None,
            source.universe_evaluated_at, source.ticker_evaluated_at,
            source.ranking_evaluated_at, elapsed, elapsed, tuple(dict.fromkeys(reasons)),
            False, source.universe_count, since_change,
        )
        self.records.append(record)
        self._last_top = symbol
        return record

    def run(self, count, *, interval_seconds):
        if type(count) is not int or count <= 0 or interval_seconds < 0:
            raise ValueError("positive count and nonnegative interval required")
        result = []
        for index in range(count):
            result.append(self.observe_once())
            if index + 1 < count:
                self.sleeper(interval_seconds)
        return tuple(result)


def analyze_calibration(records):
    valid = tuple(item for item in records if not item.missing)
    top_symbols = tuple(item.top_candidate_symbol for item in valid)
    changes = sum(item.top_candidate_changed for item in valid)
    transitions = []
    for item in valid:
        if item.top_candidate_changed:
            transitions.append({"previousTop": item.previous_top_candidate,
                                "newTop": item.top_candidate_symbol,
                                "timestamp": item.observed_at,
                                "newScore": item.top_candidate_score,
                                "scoreAdvantage": item.score_advantage})
    change_points = []
    for item in valid:
        if not change_points or change_points[-1].top_candidate_symbol != item.top_candidate_symbol:
            change_points.append(item)
    oscillations, intervals = [], []
    for index in range(2, len(change_points)):
        symbols = tuple(x.top_candidate_symbol for x in change_points[index-2:index+1])
        if symbols[0] == symbols[2] != symbols[1]:
            oscillations.append("-".join(symbols))
            first = datetime.fromisoformat(change_points[index-2].observed_at.replace("Z", "+00:00"))
            last = datetime.fromisoformat(change_points[index].observed_at.replace("Z", "+00:00"))
            intervals.append(Decimal(str((last-first).total_seconds())))
    dwell = []
    if valid:
        start = datetime.fromisoformat(valid[0].observed_at.replace("Z", "+00:00"))
        current = valid[0].top_candidate_symbol
        for previous, item in zip(valid, valid[1:]):
            if item.top_candidate_symbol != current:
                ended = datetime.fromisoformat(previous.observed_at.replace("Z", "+00:00"))
                dwell.append(Decimal(str((ended-start).total_seconds())))
                start = datetime.fromisoformat(item.observed_at.replace("Z", "+00:00"))
                current = item.top_candidate_symbol
        ended = datetime.fromisoformat(valid[-1].observed_at.replace("Z", "+00:00"))
        dwell.append(Decimal(str((ended-start).total_seconds())))
    def membership_rate(size):
        if len(valid) < 2:
            return None
        changes_count = sum(
            set(x["symbol"] for x in previous.top5[:size]) != set(x["symbol"] for x in item.top5[:size])
            for previous, item in zip(valid, valid[1:])
        )
        return Decimal(changes_count) / Decimal(len(valid)-1)
    run_lengths = []
    for item in valid:
        if item.top_candidate_changed and run_lengths:
            run_lengths.append(1)
        elif run_lengths:
            run_lengths[-1] += 1
        else:
            run_lengths.append(1)
    return {
        "requested": len(records), "completed": len(valid),
        "networkFailures": len(records)-len(valid), "uniqueTopCandidates": len(set(top_symbols)),
        "topChanges": changes, "longestConsecutiveWins": max((x.consecutive_top_candidate_wins for x in valid), default=0),
        "medianConsecutiveWins": Decimal(str(median(run_lengths))) if run_lengths else None,
        "scoreAdvantage": distribution(tuple(x.score_advantage for x in valid)),
        "top1VsTop2": distribution(tuple(x.top1_vs_top2_difference for x in valid)),
        "dwell": distribution(tuple(dwell)), "oscillationCount": len(oscillations),
        "runLength": distribution(tuple(Decimal(x) for x in run_lengths)),
        "rightCensoredRun": bool(valid),
        "oscillationPatterns": tuple(oscillations),
        "shortestOscillationInterval": min(intervals) if intervals else None,
        "medianOscillationInterval": Decimal(str(median(intervals))) if intervals else None,
        "p90OscillationInterval": _percentile(tuple(intervals), Decimal("0.90")),
        "oscillationRate": Decimal(len(oscillations))/Decimal(len(change_points)-2) if len(change_points)>2 else None,
        "top1ChangeRate": Decimal(changes)/Decimal(len(valid)-1) if len(valid)>1 else None,
        "top3MembershipChangeRate": membership_rate(3), "top5MembershipChangeRate": membership_rate(5),
        "networkDuration": distribution(tuple(x.network_duration for x in records)),
        "transitions": tuple(transitions),
    }


def simulate_hypothetical_switches(records, *, minimum_score_advantage,
                                    required_consecutive_wins, minimum_active_duration):
    """Offline flags only; intentionally has no runtime or switch dependency."""
    threshold, duration = Decimal(str(minimum_score_advantage)), Decimal(str(minimum_active_duration))
    return tuple({
        "observationId": item.observation_id,
        "wouldSwitch": bool(
            not item.missing and item.score_advantage is not None
            and item.score_advantage >= threshold
            and item.consecutive_top_candidate_wins >= required_consecutive_wins
            and item.time_since_last_top_change >= duration
        ),
    } for item in records)


def simulate_anti_flapping(records, *, minimum_score_advantage,
                           required_consecutive_wins, minimum_active_duration,
                           switch_cooldown):
    """Compare a parameter tuple without mutating live or runtime state."""
    advantage = Decimal(str(minimum_score_advantage))
    duration = Decimal(str(minimum_active_duration))
    cooldown = Decimal(str(switch_cooldown))
    last_switch_at = None
    switched_to = None
    switches, suppressed, persistence, gaps, sequence = 0, 0, [], [], []
    for item in records:
        if item.missing or item.score_advantage is None or item.top_candidate_symbol is None:
            continue
        passes_score = item.score_advantage >= advantage
        passes_persistence = item.consecutive_top_candidate_wins >= required_consecutive_wins
        passes_duration = item.candidate_dwell_duration >= duration
        observed = datetime.fromisoformat(item.observed_at.replace("Z", "+00:00"))
        since_switch = (
            Decimal(str((observed-last_switch_at).total_seconds()))
            if last_switch_at is not None else None
        )
        passes_cooldown = since_switch is None or since_switch >= cooldown
        new_candidate = item.top_candidate_symbol != switched_to
        would_switch = all((passes_score, passes_persistence, passes_duration,
                            passes_cooldown, new_candidate))
        if would_switch:
            if since_switch is not None:
                gaps.append(since_switch)
            switches += 1
            persistence.append(item.consecutive_top_candidate_wins)
            sequence.append(item.top_candidate_symbol)
            switched_to, last_switch_at = item.top_candidate_symbol, observed
        elif passes_score and new_candidate:
            suppressed += 1
    oscillations = sum(sequence[i] == sequence[i-2] != sequence[i-1]
                       for i in range(2, len(sequence)))
    return {
        "minimumScoreAdvantage": advantage,
        "requiredConsecutiveWins": required_consecutive_wins,
        "minimumActiveDuration": duration, "switchCooldown": cooldown,
        "hypotheticalSwitchCount": switches, "suppressedSwitchCount": suppressed,
        "oscillationCount": oscillations,
        "candidatePersistenceBeforeSwitch": distribution(tuple(Decimal(x) for x in persistence)),
        "timeBetweenSwitches": distribution(tuple(gaps)),
        "runtimeMutationCount": 0,
    }


def simulate_anti_flapping_grid(records, *, score_advantages=("0.40", "0.41", "0.42", "0.43"),
                                  consecutive_wins=(3, 5, 7, 10),
                                  active_durations=(15, 30, 45, 60),
                                  cooldowns=(30, 60, 90, 120)):
    return tuple(
        simulate_anti_flapping(
            records, minimum_score_advantage=score,
            required_consecutive_wins=wins, minimum_active_duration=duration,
            switch_cooldown=cooldown,
        )
        for score in score_advantages for wins in consecutive_wins
        for duration in active_durations for cooldown in cooldowns
    )
