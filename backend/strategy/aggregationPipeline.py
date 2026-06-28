from collections import deque
from statistics import mean
import time

# ============================================================
# MICROSTRUCTURE STATE BUILDER
# ============================================================

from backend.aggregation.MicrostructureStateBuilder import (
    MicrostructureStateBuilder
)

# ============================================================
# WEBSOCKET MANAGER
# ============================================================

from backend.websocket.ws_manager import (
    manager
)


class AggregationPipeline:

    def __init__(self):

        # ============================================
        # ROLLING HISTORIES
        # ============================================

        self.spread_history = deque(maxlen=100)

        self.imbalance_history = deque(maxlen=100)

        self.momentum_history = deque(maxlen=100)

        # ============================================
        # MOMENTUM STATE
        # ============================================

        self.last_mid_price = None

        self.last_direction = 0

        self.consecutive_moves = 0

        # ============================================
        # MICROSTRUCTURE BUILDER
        # ============================================

        self.microstructure_builder = (
            MicrostructureStateBuilder()
        )

    # =========================================================
    # ORDERFLOW IMBALANCE
    # =========================================================

    def compute_orderflow_imbalance(self, packet):

        bid_volume = packet.get("bidVolume", 0)

        ask_volume = packet.get("askVolume", 0)

        total_volume = bid_volume + ask_volume

        if total_volume <= 0:

            imbalance_ratio = 0.0

        else:

            imbalance_ratio = (
                bid_volume - ask_volume
            ) / total_volume

        self.imbalance_history.append(
            imbalance_ratio
        )

        return {

            "totalBidVolume": bid_volume,

            "totalAskVolume": ask_volume,

            "imbalanceRatio": imbalance_ratio,

        }

    # =========================================================
    # SPREAD METRICS
    # =========================================================

    def compute_spread_metrics(self, packet):

        best_bid = packet.get("bestBid")

        best_ask = packet.get("bestAsk")

        if best_bid is None or best_ask is None:

            return {

                "spread": None,

                "spreadAverage": None,

                "spreadWidening": False,

                "spreadCompression": False,

            }

        current_spread = best_ask - best_bid

        self.spread_history.append(
            current_spread
        )

        rolling_average = mean(
            self.spread_history
        )

        spread_widening = (
            current_spread >
            (rolling_average * 1.5)
        )

        spread_compression = (
            current_spread <
            (rolling_average * 0.7)
        )

        return {

            "spread": current_spread,

            "spreadAverage": rolling_average,

            "spreadWidening": spread_widening,

            "spreadCompression": spread_compression,

        }

    # =========================================================
    # MOMENTUM PERSISTENCE
    # =========================================================

    def compute_momentum_persistence(self, packet):

        best_bid = packet.get("bestBid")

        best_ask = packet.get("bestAsk")

        if best_bid is None or best_ask is None:

            return {

                "tickDirection": 0,

                "consecutiveMoveCount": 0,

                "velocity": 0.0,

                "microtrendPersistence": False,

            }

        mid_price = (
            best_bid + best_ask
        ) / 2

        # ============================================
        # INITIALIZATION
        # ============================================

        if self.last_mid_price is None:

            self.last_mid_price = mid_price

        delta = (
            mid_price - self.last_mid_price
        )

        direction = 0

        if delta > 0:

            direction = 1

        elif delta < 0:

            direction = -1

        # ============================================
        # CONSECUTIVE MOVES
        # ============================================

        if direction == self.last_direction:

            self.consecutive_moves += 1

        else:

            self.consecutive_moves = 1

        velocity = abs(delta)

        self.momentum_history.append(
            direction
        )

        self.last_direction = direction

        self.last_mid_price = mid_price

        return {

            "tickDirection": direction,

            "consecutiveMoveCount":
                self.consecutive_moves,

            "velocity": velocity,

            "microtrendPersistence":
                self.consecutive_moves >= 3,

        }

    # =========================================================
    # LIQUIDITY ABSORPTION
    # =========================================================

    def compute_liquidity_absorption(

        self,

        packet,

        imbalance_data,

        momentum_data,

    ):

        imbalance_ratio = (
            imbalance_data.get(
                "imbalanceRatio",
                0,
            )
        )

        velocity = momentum_data.get(
            "velocity",
            0,
        )

        heavy_flow = (
            abs(imbalance_ratio) > 0.4
        )

        stagnant_price = (
            velocity < 0.000001
        )

        aggressive_buying_absorbed = (

            imbalance_ratio > 0.4

            and stagnant_price

        )

        aggressive_selling_absorbed = (

            imbalance_ratio < -0.4

            and stagnant_price

        )

        return {

            "heavyFlow": heavy_flow,

            "stagnantPrice":
                stagnant_price,

            "aggressiveBuyingAbsorbed":
                aggressive_buying_absorbed,

            "aggressiveSellingAbsorbed":
                aggressive_selling_absorbed,

        }

    # =========================================================
    # MICROSTRUCTURE STATE
    # =========================================================

    def build_microstructure_state(

        self,

        packet,

        imbalance_data,

        spread_data,

        momentum_data,

        liquidity_data,

    ):

        best_bid = packet.get("bestBid")

        best_ask = packet.get("bestAsk")

        mid_price = None

        if (
            best_bid is not None
            and
            best_ask is not None
        ):

            mid_price = (
                best_bid + best_ask
            ) / 2

        return {

            "midPrice": mid_price,

            "spread": spread_data,

            "imbalance": imbalance_data,

            "momentum": momentum_data,

            "liquidity": liquidity_data,

            "volatility": abs(

                momentum_data.get(
                    "velocity",
                    0,
                )

            ),

            "timestamp": time.time(),

        }

    # =========================================================
    # PIPELINE ENTRY
    # =========================================================

    async def process_aggregation_pipeline(

        self,

        normalized_packet,

    ):

        try:

            # ========================================
            # ORDERFLOW
            # ========================================

            imbalance_data = (

                self.compute_orderflow_imbalance(
                    normalized_packet
                )

            )

            # ========================================
            # SPREAD
            # ========================================

            spread_data = (

                self.compute_spread_metrics(
                    normalized_packet
                )

            )

            # ========================================
            # MOMENTUM
            # ========================================

            momentum_data = (

                self.compute_momentum_persistence(
                    normalized_packet
                )

            )

            # ========================================
            # LIQUIDITY ABSORPTION
            # ========================================

            liquidity_data = (

                self.compute_liquidity_absorption(

                    normalized_packet,

                    imbalance_data,

                    momentum_data,

                )

            )

            # ========================================
            # BUILD STATE
            # ========================================

            microstructure_state = (

                self.build_microstructure_state(

                    normalized_packet,

                    imbalance_data,

                    spread_data,

                    momentum_data,

                    liquidity_data,

                )

            )

            # ========================================
            # MARKET DATA
            # ========================================

            market_data = {

                "buyVolume":
                    normalized_packet.get(
                        "bidVolume",
                        0.0,
                    ),

                "sellVolume":
                    normalized_packet.get(
                        "askVolume",
                        0.0,
                    ),

                "bestBid":
                    normalized_packet.get(
                        "bestBid",
                        0.0,
                    ),

                "bestAsk":
                    normalized_packet.get(
                        "bestAsk",
                        0.0,
                    ),

                "lastPrice":
                    microstructure_state.get(
                        "midPrice",
                        0.0,
                    ),
            }

            # ========================================
            # BUILD EXECUTION COGNITION STATE
            # ========================================

            execution_microstructure_state = (

                self.microstructure_builder
                .build_microstructure_state(
                    market_data
                )

            )

            # ========================================
            # LIVE EXECUTION COGNITION
            # ========================================

            print(
                "[AGGREGATION] before process_microstructure_runtime"
            )

            await manager.process_microstructure_runtime(
                execution_microstructure_state
            )

            return {

                "valid": True,

                "microstructure":
                    microstructure_state,

                "executionMicrostructure":
                    execution_microstructure_state,

            }

        except Exception as e:

            return {

                "valid": False,

                "error": str(e),

            }