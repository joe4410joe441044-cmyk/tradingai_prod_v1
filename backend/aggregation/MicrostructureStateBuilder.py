# ============================================================
# FILE:
# backend/aggregation/MicrostructureStateBuilder.py
# ============================================================

# ============================================================
# MicrostructureStateBuilder.py
# ============================================================
#
# PURPOSE
# ------------------------------------------------------------
# Build normalized microstructure cognition state
# from validated market telemetry.
#
# This layer converts:
#
#     exchange packets
#         ↓
#     normalized telemetry
#         ↓
#     execution cognition state
#
# IMPORTANT:
# ------------------------------------------------------------
# This layer DOES NOT predict price.
#
# It measures:
#
# - pressure
# - spread condition
# - liquidity condition
# - momentum persistence
# - execution danger
#
# ============================================================

from collections import deque
from copy import deepcopy
from datetime import datetime
import math

from backend.utils.log_buffer import runtime_debug
from backend.strategy.normalized_parameters import parameter_value


class MicrostructureStateBuilder:

    ORDERBOOK_AGGREGATION_DEPTH = 20
    ABSORPTION_VOLUME_THRESHOLD = 50000.0
    ABSORPTION_ABS_PRICE_DELTA_THRESHOLD = 0.0001
    STAGNANT_VOLUME_THRESHOLD = 75000.0
    STAGNANT_SPREAD_THRESHOLD = 0.0003
    FAKE_PRESSURE_DIFFERENCE_THRESHOLD = 0.70
    FAKE_PRESSURE_ABS_PRICE_DELTA_THRESHOLD = 0.0001

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self, parameter_set=None):

        self.parameter_set = deepcopy(parameter_set)
        self.normalized_parameters_enabled = (
            isinstance(self.parameter_set, dict)
            and self.parameter_set.get("scope") == "PAPER_ONLY"
        )
        volume_window_size = int(parameter_value(
            self.parameter_set,
            "volumeWindowSize",
            100,
        ))
        self.total_volume_history = deque(
            maxlen=max(1, volume_window_size)
        )

        self.previous_spread = None

        self.previous_price = None

        self.momentum_window = []

        self.max_window_size = 20

        self.momentum_persistence_debug = None

        # Parallel debug-only observations. These values are never read by
        # momentum, strategy, governance, or execution logic.
        self.price_history_generation_debug = None

        self._price_history_observations = []

        # Debug-only AI momentum history. It is intentionally separate from
        # momentum_window and is not consumed by strategy or AI runtimes.
        self._ai_momentum_price_samples = []

        self._ai_momentum_deltas = []

        self._ai_momentum_last_sample_at = None

        self.ai_momentum_persistence = 0.0

        self.ai_momentum_trace = None

        # Paper-only Strategy momentum uses causal wall-clock buckets.  The
        # legacy callback-count window above remains untouched for Live/default.
        self._strategy_momentum_samples = deque()

        self.strategy_momentum_features = None

    @staticmethod
    def _rolling_percentile(values, percentile):
        """Deterministic linear percentile over prior causal observations."""

        ordered = sorted(float(value) for value in values)
        if not ordered:
            return None
        position = (len(ordered) - 1) * float(percentile)
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] + (
            (ordered[upper] - ordered[lower]) * weight
        )

    def observe_price_history_generation(
        self,
        current_price,
        price_path_debug=None,
    ):

        price_path_debug = dict(
            price_path_debug
            or {}
        )

        observed_at = price_path_debug.get(
            "marketUpdateTime",
            datetime.utcnow().timestamp(),
        )

        price_delta = None

        if isinstance(self.momentum_persistence_debug, dict):
            price_delta = self.momentum_persistence_debug.get(
                "priceDelta"
            )

        self._price_history_observations.append({
            "price": current_price,
            "delta": price_delta,
            "timestamp": observed_at,
        })

        self._price_history_observations = (
            self._price_history_observations[
                -self.max_window_size:
            ]
        )

        prices = [
            item["price"]
            for item in self._price_history_observations
        ]

        deltas = [
            item["delta"]
            for item in self._price_history_observations
        ]

        timestamps = [
            item["timestamp"]
            for item in self._price_history_observations
        ]

        unique_price_count = len(set(prices))

        valid_timestamps = (
            timestamps
            and all(
                isinstance(timestamp, (int, float))
                and not isinstance(timestamp, bool)
                for timestamp in timestamps
            )
        )

        history_window_seconds = None
        history_window_ms = None
        intervals_ms = []

        if valid_timestamps:
            history_window_seconds = (
                timestamps[-1] - timestamps[0]
            )
            history_window_ms = (
                history_window_seconds * 1000
            )
            intervals_ms = [
                (newer - older) * 1000
                for older, newer in zip(
                    timestamps,
                    timestamps[1:],
                )
            ]

        average_interval_ms = (
            sum(intervals_ms) / len(intervals_ms)
            if intervals_ms
            else None
        )

        price_change_events = sum(
            current != previous
            for previous, current in zip(
                prices,
                prices[1:],
            )
        )

        same_price_run_length = 0

        if prices:
            latest_price = prices[-1]

            for price in reversed(prices):
                if price != latest_price:
                    break

                same_price_run_length += 1

        ticks_until_price_change = None

        if price_change_events:
            latest_change_index = max(
                index
                for index in range(1, len(prices))
                if prices[index] != prices[index - 1]
            )
            previous_run_price = prices[
                latest_change_index - 1
            ]
            ticks_until_price_change = 0

            for index in range(
                latest_change_index - 1,
                -1,
                -1,
            ):
                if prices[index] != previous_run_price:
                    break

                ticks_until_price_change += 1

        self.price_history_generation_debug = {
            "lastWsPrice": price_path_debug.get(
                "lastWsPrice"
            ),
            "lastWsReceiveTime": price_path_debug.get(
                "lastWsReceiveTime"
            ),
            "wsUpdateCount": price_path_debug.get(
                "wsUpdateCount"
            ),
            "marketUpdatePrice": price_path_debug.get(
                "marketUpdatePrice"
            ),
            "marketUpdateTime": price_path_debug.get(
                "marketUpdateTime"
            ),
            "providerPrice": price_path_debug.get(
                "providerPrice"
            ),
            "providerPreviousPrice": price_path_debug.get(
                "providerPreviousPrice"
            ),
            "providerUpdateCount": price_path_debug.get(
                "providerUpdateCount"
            ),
            "providerTimestamp": price_path_debug.get(
                "providerTimestamp"
            ),
            "providerPriceChanged": price_path_debug.get(
                "providerPriceChanged"
            ),
            "historyLength": len(prices),
            "historyCapacity": self.max_window_size,
            "last20Prices": prices,
            "last20PriceDeltas": deltas,
            "last20Timestamps": timestamps,
            "historyWindowMs": history_window_ms,
            "historyWindowSeconds": history_window_seconds,
            "averageIntervalMs": average_interval_ms,
            "minIntervalMs": (
                min(intervals_ms)
                if intervals_ms
                else None
            ),
            "maxIntervalMs": (
                max(intervals_ms)
                if intervals_ms
                else None
            ),
            "updatesPerSecondEstimate": (
                len(intervals_ms) / history_window_seconds
                if intervals_ms
                and history_window_seconds > 0
                else None
            ),
            "priceChangeEventsInLast20": (
                price_change_events
            ),
            "ticksUntilPriceChange": (
                ticks_until_price_change
            ),
            "samePriceRunLength": same_price_run_length,
            "latest20TimeRange": {
                "oldestTimestamp": (
                    timestamps[0]
                    if timestamps
                    else None
                ),
                "newestTimestamp": (
                    timestamps[-1]
                    if timestamps
                    else None
                ),
            },
            "duplicatePriceCount": (
                len(prices) - unique_price_count
            ),
            "uniquePriceCount": unique_price_count,
            "flatPriceCount": len([
                delta
                for delta in deltas
                if delta == 0
            ]),
            "newestHistoryPrice": (
                prices[-1]
                if prices
                else None
            ),
            "oldestHistoryPrice": (
                prices[0]
                if prices
                else None
            ),
            "historyUpdatedAt": observed_at,
            "bufferAppendAttempted": True,
            "bufferAppendExecuted": True,
            "bufferIgnored": False,
            "bufferIgnoreReason": None,
        }

    def compute_ai_momentum_persistence(
        self,
        current_price,
        sampled_at=None,
    ):

        if not isinstance(sampled_at, (int, float)) or isinstance(
            sampled_at,
            bool,
        ):
            sampled_at = datetime.utcnow().timestamp()

        reason = None

        if (
            self._ai_momentum_last_sample_at is not None
            and sampled_at < self._ai_momentum_last_sample_at
        ):
            self._ai_momentum_price_samples = []
            self._ai_momentum_deltas = []
            self._ai_momentum_last_sample_at = None
            reason = "TIMESTAMP_REVERSED"

        should_sample = (
            self._ai_momentum_last_sample_at is None
            or (
                sampled_at
                - self._ai_momentum_last_sample_at
            ) * 1000 >= 100.0 - 0.000001
        )

        if should_sample:
            if self._ai_momentum_price_samples:
                previous_price = (
                    self._ai_momentum_price_samples[-1]["price"]
                )
                self._ai_momentum_deltas.append(
                    current_price - previous_price
                )
                self._ai_momentum_deltas = (
                    self._ai_momentum_deltas[-20:]
                )

            self._ai_momentum_price_samples.append({
                "price": current_price,
                "timestamp": sampled_at,
            })
            self._ai_momentum_price_samples = (
                self._ai_momentum_price_samples[-21:]
            )
            self._ai_momentum_last_sample_at = sampled_at

        positive = len([
            delta
            for delta in self._ai_momentum_deltas
            if delta > 0
        ])
        negative = len([
            delta
            for delta in self._ai_momentum_deltas
            if delta < 0
        ])
        persistence = round(
            max(positive, negative)
            / max(1, len(self._ai_momentum_deltas)),
            4,
        )

        flat = len([
            delta
            for delta in self._ai_momentum_deltas
            if delta == 0
        ])
        dominant_direction_count = max(positive, negative)

        if positive > negative:
            dominant_direction = "UP"
        elif negative > positive:
            dominant_direction = "DOWN"
        elif positive:
            dominant_direction = "TIE"
        else:
            dominant_direction = "FLAT"

        sample_prices = [
            sample["price"]
            for sample in self._ai_momentum_price_samples
        ]
        first_price = (
            sample_prices[0]
            if sample_prices
            else None
        )
        last_price = (
            sample_prices[-1]
            if sample_prices
            else None
        )
        net_price_change = (
            last_price - first_price
            if first_price is not None
            and last_price is not None
            else None
        )
        abs_net_price_change = (
            abs(net_price_change)
            if net_price_change is not None
            else None
        )
        delta_count = len(self._ai_momentum_deltas)
        active_delta_count = positive + negative
        flat_excluded_momentum = (
            dominant_direction_count / active_delta_count
            if active_delta_count > 0
            else 0
        )
        active_delta_ratio = (
            active_delta_count / delta_count
            if delta_count > 0
            else 0
        )

        if net_price_change is None:
            price_direction = None
        elif net_price_change > 0:
            price_direction = "UP"
        elif net_price_change < 0:
            price_direction = "DOWN"
        else:
            price_direction = "FLAT"

        direction_confirmed = (
            (dominant_direction in ("UP", "BUY")
             and price_direction == "UP")
            or (dominant_direction in ("DOWN", "SELL")
                and price_direction == "DOWN")
        )
        activity_gate_passed = active_delta_ratio >= 0.35
        price_move_gate_passed = (
            abs_net_price_change is not None
            and abs_net_price_change > 0
        )

        timestamps = [
            sample["timestamp"]
            for sample in self._ai_momentum_price_samples
        ]
        intervals_ms = [
            (newer - older) * 1000
            for older, newer in zip(
                timestamps,
                timestamps[1:],
            )
        ]

        if reason is None:
            reason = (
                "OK"
                if len(self._ai_momentum_deltas) == 20
                else "INSUFFICIENT_AI_PRICE_HISTORY"
            )

        self.ai_momentum_persistence = persistence
        self.ai_momentum_trace = {
            "sampleCount": len(
                self._ai_momentum_price_samples
            ),
            "deltaCount": len(self._ai_momentum_deltas),
            "timeSpanMs": (
                round((timestamps[-1] - timestamps[0]) * 1000, 6)
                if len(timestamps) > 1
                else 0.0
            ),
            "minIntervalMs": (
                round(min(intervals_ms), 6)
                if intervals_ms
                else None
            ),
            "maxIntervalMs": (
                round(max(intervals_ms), 6)
                if intervals_ms
                else None
            ),
            "positiveDeltaCount": positive,
            "negativeDeltaCount": negative,
            "flatDeltaCount": flat,
            "dominantDirection": dominant_direction,
            "dominantDirectionCount": dominant_direction_count,
            "samplePrices": list(sample_prices),
            "sampleDeltas": list(self._ai_momentum_deltas),
            "firstPrice": first_price,
            "lastPrice": last_price,
            "netPriceChange": net_price_change,
            "absNetPriceChange": abs_net_price_change,
            "value": persistence,
            "reason": reason,
            "comparisonMetrics": {
                "currentMomentum": persistence,
                "flatExcludedMomentum": flat_excluded_momentum,
                "activeDeltaRatio": active_delta_ratio,
                "netPriceChange": net_price_change,
                "absNetPriceChange": abs_net_price_change,
            },
            "candidateMetrics": {
                "directionPurity": flat_excluded_momentum,
                "activityRatio": active_delta_ratio,
                "priceDirection": price_direction,
                "priceMove": abs_net_price_change,
                "directionConfirmed": direction_confirmed,
                "activityGatePassed": activity_gate_passed,
                "priceMoveGatePassed": price_move_gate_passed,
                "proposedMomentumScore": flat_excluded_momentum,
                "proposedMomentumUsable": (
                    direction_confirmed
                    and activity_gate_passed
                    and price_move_gate_passed
                ),
            },
        }

        return persistence

    # ========================================================
    # IMBALANCE
    # ========================================================

    def compute_imbalance_strength(
        self,
        buy_volume,
        sell_volume,
    ):

        total = buy_volume + sell_volume

        if total <= 0:

            return 0.0

        imbalance = abs(
            buy_volume - sell_volume
        ) / total

        return round(imbalance, 4)

    # ========================================================
    # MOMENTUM PERSISTENCE
    # ========================================================

    def compute_momentum_persistence(
        self,
        current_price,
    ):

        if self.previous_price is None:

            self.momentum_persistence_debug = {
                "inputReady": True,
                "priceHistoryLength": len(
                    self.momentum_window
                ),
                "priceHistoryMinRequired": None,
                "latestPrice": current_price,
                "previousPrice": None,
                "priceDelta": None,
                "priceDeltaAbs": None,
                "priceDeltaPct": None,
                "direction": "FLAT",
                "sameDirectionCount": 0,
                "upMoveCount": 0,
                "downMoveCount": 0,
                "flatMoveCount": 1,
                "returnValue": 0.0,
                "returnReason": (
                    "INSUFFICIENT_PRICE_HISTORY"
                ),
            }

            self.previous_price = current_price

            return 0.0

        previous_price = self.previous_price

        delta = (
            current_price
            - previous_price
        )
        
        self.momentum_window.append(delta)

        self.previous_price = current_price

        # ----------------------------------------------------
        # Window Control
        # ----------------------------------------------------

        if (
            len(self.momentum_window)
            > self.max_window_size
        ):

            self.momentum_window = (
                self.momentum_window[
                    -self.max_window_size:
                ]
            )

        # ----------------------------------------------------
        # Persistence
        # ----------------------------------------------------

        positive = len([
            x for x in self.momentum_window
            if x > 0
        ])

        negative = len([
            x for x in self.momentum_window
            if x < 0
        ])

        dominant = max(
            positive,
            negative,
        )

        persistence = (
            dominant
            / max(
                1,
                len(self.momentum_window),
            )
        )

        flat = (
            len(self.momentum_window)
            - positive
            - negative
        )

        if delta > 0:
            direction = "UP"
        elif delta < 0:
            direction = "DOWN"
        else:
            direction = "FLAT"

        return_value = round(persistence, 4)

        self.momentum_persistence_debug = {
            "inputReady": True,
            "priceHistoryLength": len(
                self.momentum_window
            ),
            "priceHistoryMinRequired": None,
            "latestPrice": current_price,
            "previousPrice": previous_price,
            "priceDelta": delta,
            "priceDeltaAbs": abs(delta),
            "priceDeltaPct": (
                (delta / previous_price) * 100
                if previous_price != 0
                else None
            ),
            "direction": direction,
            "sameDirectionCount": dominant,
            "upMoveCount": positive,
            "downMoveCount": negative,
            "flatMoveCount": flat,
            "returnValue": return_value,
            "returnReason": "DOMINANT_DIRECTION_RATIO",
        }

        runtime_debug(
            "Momentum audit current=%s delta=%s "
            "window=%d positive=%d negative=%d persistence=%s",
            current_price,
            delta,
            len(self.momentum_window),
            positive,
            negative,
            persistence,
        )




        return return_value

    def compute_strategy_momentum_features(
        self,
        current_price,
        sampled_at=None,
    ):
        """Build the Paper-only, time-normalized Strategy momentum contract."""

        if not isinstance(sampled_at, (int, float)) or isinstance(
            sampled_at,
            bool,
        ):
            sampled_at = datetime.utcnow().timestamp()

        window_seconds = float(parameter_value(
            self.parameter_set,
            "momentumWindowSeconds",
            60.0,
        ))
        cadence_seconds = float(parameter_value(
            self.parameter_set,
            "momentumSampleCadenceSeconds",
            1.0,
        ))
        minimum_warmup_seconds = float(parameter_value(
            self.parameter_set,
            "momentumMinimumWarmupSeconds",
            20.0,
        ))
        minimum_samples = int(parameter_value(
            self.parameter_set,
            "momentumMinimumSamples",
            10,
        ))
        activity_exponent = float(parameter_value(
            self.parameter_set,
            "momentumActivityExponent",
            0.5,
        ))
        cadence_seconds = max(cadence_seconds, 0.001)
        window_seconds = max(window_seconds, cadence_seconds)

        bucket = math.floor(sampled_at / cadence_seconds)
        reset_reason = None
        if (
            self._strategy_momentum_samples
            and bucket < self._strategy_momentum_samples[-1]["bucket"]
        ):
            self._strategy_momentum_samples.clear()
            reset_reason = "TIMESTAMP_REVERSED"

        sample = {
            "bucket": bucket,
            "timestamp": float(sampled_at),
            "price": float(current_price),
        }
        if (
            self._strategy_momentum_samples
            and bucket == self._strategy_momentum_samples[-1]["bucket"]
        ):
            self._strategy_momentum_samples[-1] = sample
        else:
            self._strategy_momentum_samples.append(sample)

        minimum_bucket = bucket - math.ceil(
            window_seconds / cadence_seconds
        )
        while (
            self._strategy_momentum_samples
            and self._strategy_momentum_samples[0]["bucket"]
            < minimum_bucket
        ):
            self._strategy_momentum_samples.popleft()

        samples = tuple(self._strategy_momentum_samples)
        deltas = [
            newer["price"] - older["price"]
            for older, newer in zip(samples, samples[1:])
        ]
        up_moves = sum(delta > 0 for delta in deltas)
        down_moves = sum(delta < 0 for delta in deltas)
        non_flat_moves = up_moves + down_moves
        flat_moves = len(deltas) - non_flat_moves

        if up_moves > down_moves:
            dominant_direction = "UP"
        elif down_moves > up_moves:
            dominant_direction = "DOWN"
        else:
            dominant_direction = "FLAT"

        direction_purity = (
            max(up_moves, down_moves) / non_flat_moves
            if non_flat_moves
            else 0.0
        )
        elapsed_slots = (
            bucket - samples[0]["bucket"]
            if samples
            else 0
        )
        total_observation_slots = max(1, elapsed_slots)
        activity_ratio = min(
            1.0,
            non_flat_moves / total_observation_slots,
        )
        activity_factor = activity_ratio ** activity_exponent
        normalized_momentum = direction_purity * activity_factor
        elapsed_seconds = elapsed_slots * cadence_seconds
        warmup_ready = (
            elapsed_seconds >= minimum_warmup_seconds
            and len(samples) >= minimum_samples
        )

        self.strategy_momentum_features = {
            "contractVersion": "TIME_SYMBOL_NORMALIZED_V1",
            "windowSeconds": window_seconds,
            "sampleCadenceSeconds": cadence_seconds,
            "sampleCount": len(samples),
            "totalObservationSlots": total_observation_slots,
            "elapsedSeconds": round(elapsed_seconds, 6),
            "upMoves": up_moves,
            "downMoves": down_moves,
            "flatMoves": flat_moves,
            "nonFlatMoves": non_flat_moves,
            "momentumDirection": dominant_direction,
            "directionPurity": round(direction_purity, 4),
            "activityRatio": round(activity_ratio, 4),
            "activityFactor": round(activity_factor, 4),
            "normalizedMomentum": round(normalized_momentum, 4),
            "warmupReady": warmup_ready,
            "warmupReason": (
                reset_reason
                or (None if warmup_ready else "INSUFFICIENT_TIME_NORMALIZED_HISTORY")
            ),
        }
        return dict(self.strategy_momentum_features)

    # ========================================================
    # SPREAD VOLATILITY
    # ========================================================

    def compute_spread_volatility(
        self,
        spread,
    ):

        if self.previous_spread is None:

            self.previous_spread = spread

            return 0.0

        volatility = abs(
            spread - self.previous_spread
        )

        self.previous_spread = spread

        return round(volatility, 6)

    # ========================================================
    # SPREAD QUALITY
    # ========================================================

    def compute_spread_quality(
        self,
        spread,
    ):

        if spread <= 0:

            return 0.0

        quality = max(
            0.0,
            1.0 - (spread * 1000)
        )

        return round(quality, 4)

    # ========================================================
    # LIQUIDITY QUALITY
    # ========================================================

    def compute_liquidity_quality(
        self,
        total_volume,
    ):

        normalized = min(
            total_volume / 100000,
            1.0,
        )

        return round(normalized, 4)

    @staticmethod
    def compute_normalized_spread_quality(spread_pct, maximum_spread_pct):
        if spread_pct is None or maximum_spread_pct <= 0:
            return 0.0
        quality = 1.0 - (float(spread_pct) / float(maximum_spread_pct))
        return round(max(0.0, min(quality, 1.0)), 4)

    @staticmethod
    def compute_normalized_liquidity_quality(total_volume, reference_volume):
        if reference_volume is None or reference_volume <= 0:
            return 0.0
        quality = float(total_volume) / float(reference_volume)
        return round(max(0.0, min(quality, 1.0)), 4)

    # ========================================================
    # ABSORPTION DETECTION
    # ========================================================

    def detect_absorption(
        self,
        buy_volume,
        sell_volume,
        price_delta,
    ):

        heavy_volume = (
            buy_volume + sell_volume
        ) > self.ABSORPTION_VOLUME_THRESHOLD

        weak_price_move = (
            abs(price_delta)
            < self.ABSORPTION_ABS_PRICE_DELTA_THRESHOLD
        )

        return (
            heavy_volume
            and weak_price_move
        )

    # ========================================================
    # STAGNANT FLOW
    # ========================================================

    def detect_stagnant_heavy_flow(
        self,
        total_volume,
        spread,
    ):

        return (
            total_volume > self.STAGNANT_VOLUME_THRESHOLD
            and spread > self.STAGNANT_SPREAD_THRESHOLD
        )

    # ========================================================
    # FAKE PRESSURE
    # ========================================================

    def detect_fake_pressure(
        self,
        buy_pressure,
        sell_pressure,
        price_delta,
    ):

        imbalance = abs(
            buy_pressure - sell_pressure
        )

        return (
            imbalance
            > self.FAKE_PRESSURE_DIFFERENCE_THRESHOLD
            and abs(price_delta)
            < self.FAKE_PRESSURE_ABS_PRICE_DELTA_THRESHOLD
        )

    # ========================================================
    # BUILD STATE
    # ========================================================

    def build_microstructure_state(
        self,
        market_data,
    ):

        # ----------------------------------------------------
        # Market Inputs
        # ----------------------------------------------------

        scalar_buy_volume = float(
            market_data.get(
                "buyVolume",
                0.0,
            )
        )

        scalar_sell_volume = float(
            market_data.get(
                "sellVolume",
                0.0,
            )
        )

        orderbook_bids = market_data.get("orderbookBids")
        orderbook_asks = market_data.get("orderbookAsks")

        has_orderbook = (
            orderbook_bids is not None
            and orderbook_asks is not None
        )

        if has_orderbook:
            bid_levels = sorted(
                (
                    (float(price), float(size))
                    for price, size in orderbook_bids.items()
                ),
                key=lambda level: level[0],
                reverse=True,
            )
            ask_levels = sorted(
                (
                    (float(price), float(size))
                    for price, size in orderbook_asks.items()
                ),
                key=lambda level: level[0],
            )

            strategy_bid_levels = bid_levels[
                :self.ORDERBOOK_AGGREGATION_DEPTH
            ]
            strategy_ask_levels = ask_levels[
                :self.ORDERBOOK_AGGREGATION_DEPTH
            ]

            raw_full_bid_total = sum(
                size for _, size in bid_levels
            )
            raw_full_ask_total = sum(
                size for _, size in ask_levels
            )
            strategy_bid_total = sum(
                size for _, size in strategy_bid_levels
            )
            strategy_ask_total = sum(
                size for _, size in strategy_ask_levels
            )

            buy_volume = strategy_bid_total
            sell_volume = strategy_ask_total
            orderbook_aggregation_mode = "TOP_N"
            excluded_bid_levels = max(
                0,
                len(bid_levels)
                - self.ORDERBOOK_AGGREGATION_DEPTH,
            )
            excluded_ask_levels = max(
                0,
                len(ask_levels)
                - self.ORDERBOOK_AGGREGATION_DEPTH,
            )
            min_included_bid = (
                strategy_bid_levels[-1][0]
                if strategy_bid_levels
                else None
            )
            max_included_ask = (
                strategy_ask_levels[-1][0]
                if strategy_ask_levels
                else None
            )
            min_raw_bid = bid_levels[-1][0] if bid_levels else None
            max_raw_bid = bid_levels[0][0] if bid_levels else None
            min_raw_ask = ask_levels[0][0] if ask_levels else None
            max_raw_ask = ask_levels[-1][0] if ask_levels else None
        else:
            buy_volume = scalar_buy_volume
            sell_volume = scalar_sell_volume
            raw_full_bid_total = buy_volume
            raw_full_ask_total = sell_volume
            strategy_bid_total = buy_volume
            strategy_ask_total = sell_volume
            orderbook_aggregation_mode = "SCALAR_FALLBACK"
            excluded_bid_levels = 0
            excluded_ask_levels = 0
            min_included_bid = None
            max_included_ask = None
            min_raw_bid = None
            max_raw_bid = None
            min_raw_ask = None
            max_raw_ask = None

        best_bid = float(
            market_data.get(
                "bestBid",
                0.0,
            )
        )

        best_ask = float(
            market_data.get(
                "bestAsk",
                0.0,
            )
        )

        last_price = float(
            market_data.get(
                "lastPrice",
                0.0,
            )
        )

        # ----------------------------------------------------
        # Spread
        # ----------------------------------------------------

        spread = max(
            0.0,
            best_ask - best_bid,
        )

        mid_price = (
            (best_bid + best_ask) / 2
            if best_bid > 0 and best_ask > 0
            else None
        )
        spread_pct = (
            (spread / mid_price) * 100
            if mid_price
            else None
        )

        # ----------------------------------------------------
        # Volume
        # ----------------------------------------------------

        total_volume = (
            buy_volume + sell_volume
        )

        raw_full_total_volume = (
            raw_full_bid_total + raw_full_ask_total
        )

        if raw_full_total_volume <= 0:
            raw_full_pressure_diff = 0.0
        else:
            raw_full_pressure_diff = abs(
                (
                    raw_full_bid_total
                    / raw_full_total_volume
                )
                - (
                    raw_full_ask_total
                    / raw_full_total_volume
                )
            )

        # ----------------------------------------------------
        # Price Delta
        # ----------------------------------------------------

        if self.previous_price is None:

            price_delta = 0.0

        else:

            price_delta = (
                last_price
                - self.previous_price
            )

        price_delta_pct = (
            (price_delta / self.previous_price) * 100
            if self.previous_price not in (None, 0)
            else None
        )

        # ----------------------------------------------------
        # Metrics
        # ----------------------------------------------------

        imbalance_strength = (
            self.compute_imbalance_strength(
                buy_volume,
                sell_volume,
            )
        )

        momentum_persistence = (
            self.compute_momentum_persistence(
                last_price
            )
        )

        price_path_debug = dict(
            market_data.get("pricePathDebug")
            or {}
        )

        if self.normalized_parameters_enabled:
            strategy_momentum_features = (
                self.compute_strategy_momentum_features(
                    last_price,
                    price_path_debug.get("marketUpdateTime"),
                )
            )
        else:
            strategy_momentum_features = {}

        self.observe_price_history_generation(
            last_price,
            market_data.get("pricePathDebug"),
        )

        spread_volatility = (
            self.compute_spread_volatility(
                spread
            )
        )

        spread_quality = (
            self.compute_spread_quality(
                spread
            )
        )

        liquidity_quality = (
            self.compute_liquidity_quality(
                total_volume
            )
        )
        normalized_spread_quality = spread_quality
        normalized_liquidity_quality = liquidity_quality

        # ----------------------------------------------------
        # Pressure
        # ----------------------------------------------------

        if total_volume <= 0:

            buy_pressure = 0.0
            sell_pressure = 0.0

        else:

            buy_pressure = (
                buy_volume / total_volume
            )

            sell_pressure = (
                sell_volume / total_volume
            )

        # ----------------------------------------------------
        # Detection
        # ----------------------------------------------------

        pressure_difference = abs(buy_pressure - sell_pressure)
        liquidity_calibration_ready = True

        if self.normalized_parameters_enabled:
            history = tuple(self.total_volume_history)
            minimum_history = int(parameter_value(
                self.parameter_set,
                "volumeMinimumHistory",
                20,
            ))
            absorption_percentile = float(parameter_value(
                self.parameter_set,
                "absorptionVolumePercentile",
                0.90,
            ))
            stagnant_percentile = float(parameter_value(
                self.parameter_set,
                "stagnantVolumePercentile",
                0.90,
            ))
            absorption_volume_threshold = self._rolling_percentile(
                history,
                absorption_percentile,
            )
            stagnant_volume_threshold = self._rolling_percentile(
                history,
                stagnant_percentile,
            )
            liquidity_quality_percentile = float(parameter_value(
                self.parameter_set,
                "liquidityQualityPercentile",
                0.90,
            ))
            liquidity_quality_reference = self._rolling_percentile(
                history,
                liquidity_quality_percentile,
            )
            absorption_max_delta_pct = float(parameter_value(
                self.parameter_set,
                "absorptionMaxPriceDeltaPct",
                0.10,
            ))
            stagnant_min_spread_pct = float(parameter_value(
                self.parameter_set,
                "stagnantMinSpreadPct",
                0.50,
            ))
            fake_pressure_threshold = float(parameter_value(
                self.parameter_set,
                "fakePressureDifference",
                self.FAKE_PRESSURE_DIFFERENCE_THRESHOLD,
            ))
            fake_pressure_max_delta_pct = float(parameter_value(
                self.parameter_set,
                "fakePressureMaxPriceDeltaPct",
                0.10,
            ))
            liquidity_calibration_ready = (
                len(history) >= minimum_history
                and price_delta_pct is not None
                and spread_pct is not None
            )
            absorption_volume_passed = (
                liquidity_calibration_ready
                and total_volume >= absorption_volume_threshold
            )
            absorption_delta_passed = (
                liquidity_calibration_ready
                and abs(price_delta_pct) < absorption_max_delta_pct
            )
            stagnant_volume_passed = (
                liquidity_calibration_ready
                and total_volume >= stagnant_volume_threshold
            )
            stagnant_spread_passed = (
                liquidity_calibration_ready
                and spread_pct > stagnant_min_spread_pct
            )
            fake_pressure_difference_passed = (
                liquidity_calibration_ready
                and pressure_difference > fake_pressure_threshold
            )
            fake_pressure_delta_passed = (
                liquidity_calibration_ready
                and abs(price_delta_pct) < fake_pressure_max_delta_pct
            )
            absorption_detected = (
                absorption_volume_passed and absorption_delta_passed
            )
            stagnant_heavy_flow = (
                stagnant_volume_passed and stagnant_spread_passed
            )
            fake_pressure_detected = (
                fake_pressure_difference_passed
                and fake_pressure_delta_passed
            )
            maximum_strategy_spread_pct = float(parameter_value(
                self.parameter_set,
                "maximumStrategySpreadPct",
                0.50,
            ))
            normalized_spread_quality = (
                self.compute_normalized_spread_quality(
                    spread_pct,
                    maximum_strategy_spread_pct,
                )
            )
            normalized_liquidity_quality = (
                self.compute_normalized_liquidity_quality(
                    total_volume,
                    liquidity_quality_reference,
                )
            )
            parameter_authority = deepcopy(self.parameter_set)
            detector_details = {
                "calibrationReady": liquidity_calibration_ready,
                "historyCount": len(history),
                "minimumHistory": minimum_history,
                "normalizedQuality": {
                    "spreadQuality": normalized_spread_quality,
                    "spreadPct": spread_pct,
                    "maximumStrategySpreadPct": maximum_strategy_spread_pct,
                    "liquidityQuality": normalized_liquidity_quality,
                    "observedTotalVolume": total_volume,
                    "referenceRollingVolume": liquidity_quality_reference,
                    "referenceVolumePercentile": liquidity_quality_percentile,
                },
                "absorption": {
                    "observedTotalVolume": total_volume,
                    "thresholdRollingVolume": absorption_volume_threshold,
                    "thresholdVolumePercentile": absorption_percentile,
                    "totalVolumeOperator": ">=",
                    "totalVolumeConditionPassed": absorption_volume_passed,
                    "observedAbsPriceDelta": abs(price_delta),
                    "observedAbsPriceDeltaPct": (
                        abs(price_delta_pct)
                        if price_delta_pct is not None
                        else None
                    ),
                    "thresholdMaxPriceDeltaPct": absorption_max_delta_pct,
                    "absPriceDeltaPctOperator": "<",
                    "absPriceDeltaConditionPassed": absorption_delta_passed,
                    "conditionPassed": absorption_detected,
                },
                "stagnantHeavyFlow": {
                    "observedTotalVolume": total_volume,
                    "thresholdRollingVolume": stagnant_volume_threshold,
                    "thresholdVolumePercentile": stagnant_percentile,
                    "totalVolumeOperator": ">=",
                    "totalVolumeConditionPassed": stagnant_volume_passed,
                    "observedSpread": spread,
                    "observedSpreadPct": spread_pct,
                    "thresholdMinSpreadPct": stagnant_min_spread_pct,
                    "spreadPctOperator": ">",
                    "spreadConditionPassed": stagnant_spread_passed,
                    "conditionPassed": stagnant_heavy_flow,
                },
                "fakePressure": {
                    "observedPressureDifference": pressure_difference,
                    "thresholdPressureDifference": fake_pressure_threshold,
                    "pressureDifferenceOperator": ">",
                    "pressureDifferenceConditionPassed": (
                        fake_pressure_difference_passed
                    ),
                    "observedAbsPriceDelta": abs(price_delta),
                    "observedAbsPriceDeltaPct": (
                        abs(price_delta_pct)
                        if price_delta_pct is not None
                        else None
                    ),
                    "thresholdMaxPriceDeltaPct": fake_pressure_max_delta_pct,
                    "absPriceDeltaPctOperator": "<",
                    "absPriceDeltaConditionPassed": fake_pressure_delta_passed,
                    "conditionPassed": fake_pressure_detected,
                },
            }
        else:
            absorption_detected = self.detect_absorption(
                buy_volume,
                sell_volume,
                price_delta,
            )
            stagnant_heavy_flow = self.detect_stagnant_heavy_flow(
                total_volume,
                spread,
            )
            fake_pressure_detected = self.detect_fake_pressure(
                buy_pressure,
                sell_pressure,
                price_delta,
            )
            parameter_authority = {
                "source": "MicrostructureStateBuilder",
                "kind": "classConstant",
            }
            detector_details = {
                "absorption": {
                    "observedTotalVolume": total_volume,
                    "thresholdTotalVolume": self.ABSORPTION_VOLUME_THRESHOLD,
                    "totalVolumeOperator": ">",
                    "totalVolumeConditionPassed": (
                        total_volume > self.ABSORPTION_VOLUME_THRESHOLD
                    ),
                    "observedAbsPriceDelta": abs(price_delta),
                    "thresholdAbsPriceDelta": self.ABSORPTION_ABS_PRICE_DELTA_THRESHOLD,
                    "absPriceDeltaOperator": "<",
                    "absPriceDeltaConditionPassed": (
                        abs(price_delta)
                        < self.ABSORPTION_ABS_PRICE_DELTA_THRESHOLD
                    ),
                    "conditionPassed": absorption_detected,
                },
                "stagnantHeavyFlow": {
                    "observedTotalVolume": total_volume,
                    "thresholdTotalVolume": self.STAGNANT_VOLUME_THRESHOLD,
                    "totalVolumeOperator": ">",
                    "totalVolumeConditionPassed": (
                        total_volume > self.STAGNANT_VOLUME_THRESHOLD
                    ),
                    "observedSpread": spread,
                    "thresholdSpread": self.STAGNANT_SPREAD_THRESHOLD,
                    "spreadOperator": ">",
                    "spreadConditionPassed": (
                        spread > self.STAGNANT_SPREAD_THRESHOLD
                    ),
                    "conditionPassed": stagnant_heavy_flow,
                },
                "fakePressure": {
                    "observedPressureDifference": pressure_difference,
                    "thresholdPressureDifference": self.FAKE_PRESSURE_DIFFERENCE_THRESHOLD,
                    "pressureDifferenceOperator": ">",
                    "pressureDifferenceConditionPassed": (
                        pressure_difference
                        > self.FAKE_PRESSURE_DIFFERENCE_THRESHOLD
                    ),
                    "observedAbsPriceDelta": abs(price_delta),
                    "thresholdAbsPriceDelta": self.FAKE_PRESSURE_ABS_PRICE_DELTA_THRESHOLD,
                    "absPriceDeltaOperator": "<",
                    "absPriceDeltaConditionPassed": (
                        abs(price_delta)
                        < self.FAKE_PRESSURE_ABS_PRICE_DELTA_THRESHOLD
                    ),
                    "conditionPassed": fake_pressure_detected,
                },
            }

        # The current observation is added only after its causal threshold was
        # calculated, preventing look-ahead in the rolling percentile.
        self.total_volume_history.append(total_volume)

        # Debug-only snapshot of the exact values used by the liquidity
        # detectors above. Strategy, governance, and execution logic do not
        # consume this structure.
        liquidity_instability_debug = {
            "absorptionDetected": absorption_detected,
            "fakePressureDetected": fake_pressure_detected,
            "stagnantHeavyFlow": stagnant_heavy_flow,
            "liquidityCalibrationReady": liquidity_calibration_ready,
            "liquiditySafe": None,
            "priceDelta": price_delta,
            "absPriceDelta": abs(price_delta),
            "priceDeltaPct": price_delta_pct,
            "bestBid": best_bid,
            "bestAsk": best_ask,
            "midPrice": mid_price,
            "spreadPct": spread_pct,
            "buyVolume": buy_volume,
            "sellVolume": sell_volume,
            "totalVolume": total_volume,
            "buyPressure": buy_pressure,
            "sellPressure": sell_pressure,
            "pressureDiff": pressure_difference,
            "orderbookAggregationMode": (
                orderbook_aggregation_mode
            ),
            "orderbookAggregationDepth": (
                self.ORDERBOOK_AGGREGATION_DEPTH
            ),
            "rawFullBidTotal": raw_full_bid_total,
            "rawFullAskTotal": raw_full_ask_total,
            "rawFullTotalVolume": raw_full_total_volume,
            "rawFullPressureDiff": raw_full_pressure_diff,
            "strategyBidTotal": strategy_bid_total,
            "strategyAskTotal": strategy_ask_total,
            "strategyTotalVolume": total_volume,
            "strategyPressureDiff": abs(
                buy_pressure - sell_pressure
            ),
            "excludedBidLevels": excluded_bid_levels,
            "excludedAskLevels": excluded_ask_levels,
            "excludedBidVolume": (
                raw_full_bid_total - strategy_bid_total
            ),
            "excludedAskVolume": (
                raw_full_ask_total - strategy_ask_total
            ),
            "minIncludedBid": min_included_bid,
            "maxIncludedAsk": max_included_ask,
            "minRawBid": min_raw_bid,
            "maxRawBid": max_raw_bid,
            "minRawAsk": min_raw_ask,
            "maxRawAsk": max_raw_ask,
            "spread": spread,
            "triggeredReasons": [],
            "parameterAuthority": parameter_authority,
            "detectorDetails": detector_details,
            "strategyMomentumFeatures": strategy_momentum_features,
            "normalizedSpreadQuality": normalized_spread_quality,
            "normalizedLiquidityQuality": normalized_liquidity_quality,
        }

        # ----------------------------------------------------
        # Final State
        # ----------------------------------------------------

        microstructure_state = {

            "imbalanceStrength":
                imbalance_strength,

            "momentumPersistence":
                momentum_persistence,

            "strategyMomentumFeatures":
                dict(strategy_momentum_features),

            "normalizedMomentum":
                strategy_momentum_features.get(
                    "normalizedMomentum",
                    momentum_persistence,
                ),

            "momentumDirection":
                strategy_momentum_features.get(
                    "momentumDirection",
                    "FLAT",
                ),

            "directionPurity":
                strategy_momentum_features.get("directionPurity", 0.0),

            "activityRatio":
                strategy_momentum_features.get("activityRatio", 0.0),

            "momentumWarmupReady":
                strategy_momentum_features.get("warmupReady", True),

            "momentumPersistenceDebug":
                dict(
                    self.momentum_persistence_debug
                    or {}
                ),

            "priceHistoryGenerationDebug":
                dict(
                    self.price_history_generation_debug
                    or {}
                ),

            "spread":
                round(spread, 6),

            "spreadVolatility":
                spread_volatility,

            "spreadQuality":
                spread_quality,

            "normalizedSpreadQuality":
                normalized_spread_quality,

            "liquidityQuality":
                liquidity_quality,

            "normalizedLiquidityQuality":
                normalized_liquidity_quality,

            "buyPressure":
                round(
                    buy_pressure,
                    4,
                ),

            "sellPressure":
                round(
                    sell_pressure,
                    4,
                ),

            "absorptionDetected":
                absorption_detected,

            "stagnantHeavyFlow":
                stagnant_heavy_flow,

            "fakePressureDetected":
                fake_pressure_detected,

            "liquidityCalibrationReady":
                liquidity_calibration_ready,

            "parameterAuthority":
                parameter_authority,

            "liquidityInstabilityDebug":
                liquidity_instability_debug,

            "timestamp":
                datetime.utcnow().isoformat(),
        }

        return microstructure_state
