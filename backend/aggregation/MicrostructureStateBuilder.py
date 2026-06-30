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

from datetime import datetime

from backend.utils.log_buffer import runtime_debug


class MicrostructureStateBuilder:

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self):

        self.previous_spread = None

        self.previous_price = None

        self.momentum_window = []

        self.max_window_size = 20

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

            self.previous_price = current_price

            return 0.0

        delta = (
            current_price
            - self.previous_price
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




        return round(persistence, 4)

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
        ) > 50000

        weak_price_move = (
            abs(price_delta) < 0.0001
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
            total_volume > 75000
            and spread > 0.0003
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
            imbalance > 0.70
            and abs(price_delta) < 0.0001
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

        buy_volume = float(
            market_data.get(
                "buyVolume",
                0.0,
            )
        )

        sell_volume = float(
            market_data.get(
                "sellVolume",
                0.0,
            )
        )

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

        # ----------------------------------------------------
        # Volume
        # ----------------------------------------------------

        total_volume = (
            buy_volume + sell_volume
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

        absorption_detected = (
            self.detect_absorption(
                buy_volume,
                sell_volume,
                price_delta,
            )
        )

        stagnant_heavy_flow = (
            self.detect_stagnant_heavy_flow(
                total_volume,
                spread,
            )
        )

        fake_pressure_detected = (
            self.detect_fake_pressure(
                buy_pressure,
                sell_pressure,
                price_delta,
            )
        )

        # ----------------------------------------------------
        # Final State
        # ----------------------------------------------------

        microstructure_state = {

            "imbalanceStrength":
                imbalance_strength,

            "momentumPersistence":
                momentum_persistence,

            "spread":
                round(spread, 6),

            "spreadVolatility":
                spread_volatility,

            "spreadQuality":
                spread_quality,

            "liquidityQuality":
                liquidity_quality,

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

            "timestamp":
                datetime.utcnow().isoformat(),
        }

        return microstructure_state
