# ============================================================
# MicrostructureEdgeStrategy.py
# ============================================================
#
# Production Execution Cognition Layer
#
# PURPOSE:
# ------------------------------------------------------------
# This layer DOES NOT predict the market.
#
# This layer determines:
#
#     "Is this market safe enough to execute?"
#
# Core Philosophy:
#
#     survival > execution
#
# The strategy suppresses execution during:
#
# - spread instability
# - liquidity degradation
# - absorption traps
# - conflicting momentum
# - fake directional pressure
#
# ============================================================

from datetime import datetime

from backend.utils.log_buffer import runtime_debug


class MicrostructureEdgeStrategy:

    # ============================================================
    # INIT
    # ============================================================

    def __init__(self):

        self.MIN_EDGE_SCORE = 0.55
        self.MIN_CONFIDENCE = 0.60

        self.MAX_SPREAD = 0.0005

        self.MIN_LIQUIDITY_SCORE = 0.40

        self.MIN_MOMENTUM_SCORE = 0.50

    # ============================================================
    # EDGE SCORE
    # ============================================================

    def compute_edge_score(self, microstructure_state):

        imbalance = float(
            microstructure_state.get("imbalanceStrength", 0.0)
        )

        momentum = float(
            microstructure_state.get("momentumPersistence", 0.0)
        )

        spread_quality = float(
            microstructure_state.get("spreadQuality", 0.0)
        )

        liquidity_quality = float(
            microstructure_state.get("liquidityQuality", 0.0)
        )

        # --------------------------------------------------------
        # Weighted Edge Model
        # --------------------------------------------------------

        edge_score = (
            (imbalance * 0.35)
            + (momentum * 0.30)
            + (spread_quality * 0.15)
            + (liquidity_quality * 0.20)
        )

        edge_score = max(0.0, min(edge_score, 1.0))

        # --------------------------------------------------------
        # Confidence
        # --------------------------------------------------------

        confidence = (
            edge_score
            * (
                0.5
                + (
                    momentum * 0.5
                )
            )
        )

        confidence = max(0.0, min(confidence, 1.0))

        return {
            "edgeScore": round(edge_score, 4),
            "confidence": round(confidence, 4),
        }

    # ============================================================
    # SPREAD SAFETY
    # ============================================================

    def evaluate_spread_safety(self, microstructure_state):

        spread = float(
            microstructure_state.get("spread", 0.0)
        )

        spread_volatility = float(
            microstructure_state.get(
                "spreadVolatility",
                0.0
            )
        )

        liquidity_quality = float(
            microstructure_state.get(
                "liquidityQuality",
                0.0
            )
        )

        spread_safe = True
        spread_risk = None

        # --------------------------------------------------------
        # Widening Spread
        # --------------------------------------------------------

        if spread > self.MAX_SPREAD:

            spread_safe = False
            spread_risk = "ABNORMAL_SPREAD"

        # --------------------------------------------------------
        # Spread Instability
        # --------------------------------------------------------

        elif spread_volatility > 0.65:

            spread_safe = False
            spread_risk = "SPREAD_VOLATILITY"

        # --------------------------------------------------------
        # Liquidity Deterioration
        # --------------------------------------------------------

        elif liquidity_quality < 0.35:

            spread_safe = False
            spread_risk = "LIQUIDITY_DETERIORATION"

        return {
            "spreadSafe": spread_safe,
            "spreadRisk": spread_risk,
        }

    # ============================================================
    # LIQUIDITY SAFETY
    # ============================================================

    def evaluate_liquidity_safety(self, microstructure_state):

        absorption = bool(
            microstructure_state.get(
                "absorptionDetected",
                False
            )
        )

        stagnant_flow = bool(
            microstructure_state.get(
                "stagnantHeavyFlow",
                False
            )
        )

        fake_pressure = bool(
            microstructure_state.get(
                "fakePressureDetected",
                False
            )
        )

        liquidity_safe = True

        # --------------------------------------------------------
        # Aggressive Absorption
        # --------------------------------------------------------

        if absorption:
            liquidity_safe = False

        # --------------------------------------------------------
        # Stagnant Heavy Flow
        # --------------------------------------------------------

        if stagnant_flow:
            liquidity_safe = False

        # --------------------------------------------------------
        # Fake Pressure
        # --------------------------------------------------------

        if fake_pressure:
            liquidity_safe = False

        triggered_reasons = []

        if absorption:
            triggered_reasons.append(
                "absorptionDetected"
            )

        if fake_pressure:
            triggered_reasons.append(
                "fakePressureDetected"
            )

        if stagnant_flow:
            triggered_reasons.append(
                "stagnantHeavyFlow"
            )

        liquidity_instability_debug = dict(
            microstructure_state.get(
                "liquidityInstabilityDebug",
                {},
            )
            or {}
        )
        liquidity_instability_debug.setdefault(
            "priceDelta",
            None,
        )
        liquidity_instability_debug.setdefault(
            "buyVolume",
            None,
        )
        liquidity_instability_debug.setdefault(
            "sellVolume",
            None,
        )
        liquidity_instability_debug.setdefault(
            "totalVolume",
            None,
        )
        liquidity_instability_debug.setdefault(
            "buyPressure",
            float(
                microstructure_state.get(
                    "buyPressure",
                    0.0,
                )
            ),
        )
        liquidity_instability_debug.setdefault(
            "sellPressure",
            float(
                microstructure_state.get(
                    "sellPressure",
                    0.0,
                )
            ),
        )
        liquidity_instability_debug.setdefault(
            "pressureDiff",
            abs(
                liquidity_instability_debug["buyPressure"]
                - liquidity_instability_debug["sellPressure"]
            ),
        )
        liquidity_instability_debug.setdefault(
            "spread",
            float(
                microstructure_state.get(
                    "spread",
                    0.0,
                )
            ),
        )
        liquidity_instability_debug.update({
            "absorptionDetected": absorption,
            "fakePressureDetected": fake_pressure,
            "stagnantHeavyFlow": stagnant_flow,
            "liquiditySafe": liquidity_safe,
            "triggeredReasons": triggered_reasons,
        })

        return {
            "liquiditySafe": liquidity_safe,
            "absorptionDetected": absorption,
            "liquidityInstabilityDebug": (
                liquidity_instability_debug
            ),
        }

    # ============================================================
    # MOMENTUM CONTINUATION
    # ============================================================

    def evaluate_momentum_continuation(
        self,
        microstructure_state,
    ):

        momentum_score = float(
            microstructure_state.get(
                "momentumPersistence",
                0.0
            )
        )

        buy_pressure = float(
            microstructure_state.get(
                "buyPressure",
                0.0
            )
        )

        sell_pressure = float(
            microstructure_state.get(
                "sellPressure",
                0.0
            )
        )

        direction = "NEUTRAL"

        if buy_pressure > sell_pressure:
            direction = "LONG"

        elif sell_pressure > buy_pressure:
            direction = "SHORT"

        directional_alignment = abs(
            buy_pressure - sell_pressure
        )

        momentum_valid = (
            momentum_score >= self.MIN_MOMENTUM_SCORE
            and directional_alignment >= 0.15
        )

        return {
            "momentumValid": momentum_valid,
            "direction": direction,
        }

    # ============================================================
    # EXECUTION SUPPRESSION
    # ============================================================

    def evaluate_execution_suppression(
        self,
        edge_result,
        spread_result,
        liquidity_result,
        momentum_result,
    ):

        # --------------------------------------------------------
        # Spread Danger
        # --------------------------------------------------------

        if not spread_result["spreadSafe"]:

            return {
                "executionAllowed": False,
                "suppressionReason": (
                    spread_result["spreadRisk"]
                ),
            }

        # --------------------------------------------------------
        # Liquidity Instability
        # --------------------------------------------------------

        if not liquidity_result["liquiditySafe"]:

            return {
                "executionAllowed": False,
                "suppressionReason": (
                    "LIQUIDITY_INSTABILITY"
                ),
            }

        # --------------------------------------------------------
        # Conflicting Momentum
        # --------------------------------------------------------

        if not momentum_result["momentumValid"]:

            return {
                "executionAllowed": False,
                "suppressionReason": (
                    "CONFLICTING_MOMENTUM"
                ),
            }

        # --------------------------------------------------------
        # Weak Edge
        # --------------------------------------------------------

        if (
            edge_result["edgeScore"]
            < self.MIN_EDGE_SCORE
        ):

            return {
                "executionAllowed": False,
                "suppressionReason": (
                    "WEAK_EDGE"
                ),
            }

        # --------------------------------------------------------
        # Weak Confidence
        # --------------------------------------------------------

        if (
            edge_result["confidence"]
            < self.MIN_CONFIDENCE
        ):

            return {
                "executionAllowed": False,
                "suppressionReason": (
                    "LOW_CONFIDENCE"
                ),
            }

        # --------------------------------------------------------
        # EXECUTION APPROVED
        # --------------------------------------------------------

        return {
            "executionAllowed": True,
            "suppressionReason": None,
        }

    # ============================================================
    # FINAL STRATEGY STATE
    # ============================================================

    def build_strategy_state(
        self,
        edge_result,
        spread_result,
        liquidity_result,
        momentum_result,
        suppression_result,
    ):

        risk = "LOW"

        if not suppression_result["executionAllowed"]:
            risk = "HIGH"

        strategy_state = {

            "valid": (
                suppression_result[
                    "executionAllowed"
                ]
            ),

            "edge": edge_result["edgeScore"],

            "confidence": (
                edge_result["confidence"]
            ),

            "executionAllowed": (
                suppression_result[
                    "executionAllowed"
                ]
            ),

            "direction": (
                momentum_result["direction"]
            ),

            "risk": risk,

            "suppressionReason": (
                suppression_result[
                    "suppressionReason"
                ]
            ),

            "liquidityInstabilityDebug": (
                liquidity_result[
                    "liquidityInstabilityDebug"
                ]
            ),

            "timestamp": (
                datetime.utcnow().isoformat()
            ),
        }

        return strategy_state

    # ============================================================
    # MAIN STRATEGY PIPELINE
    # ============================================================

    def process_microstructure_strategy(
        self,
        microstructure_state,
    ):

        try:

            # ----------------------------------------------------
            # EDGE
            # ----------------------------------------------------

            edge_result = self.compute_edge_score(
                microstructure_state
            )

            # ----------------------------------------------------
            # SPREAD SAFETY
            # ----------------------------------------------------

            spread_result = (
                self.evaluate_spread_safety(
                    microstructure_state
                )
            )

            # ----------------------------------------------------
            # LIQUIDITY SAFETY
            # ----------------------------------------------------

            liquidity_result = (
                self.evaluate_liquidity_safety(
                    microstructure_state
                )
            )

            # ----------------------------------------------------
            # MOMENTUM
            # ----------------------------------------------------

            momentum_result = (
                self.evaluate_momentum_continuation(
                    microstructure_state
                )
            )

            # ----------------------------------------------------
            # EXECUTION SUPPRESSION
            # ----------------------------------------------------

            suppression_result = (
                self.evaluate_execution_suppression(
                    edge_result,
                    spread_result,
                    liquidity_result,
                    momentum_result,
                )
            )

            runtime_debug(
                "Strategy audit edge=%s spread=%s liquidity=%s "
                "momentum=%s suppression=%s",
                edge_result,
                spread_result,
                liquidity_result,
                momentum_result,
                suppression_result,
            )

            # ----------------------------------------------------
            # FINAL STRATEGY STATE
            # ----------------------------------------------------

            strategy_state = (
                self.build_strategy_state(
                    edge_result,
                    spread_result,
                    liquidity_result,
                    momentum_result,
                    suppression_result,
                )
            )

            return {
                "valid": True,
                "strategy": strategy_state,
            }

        except Exception as e:

            return {
                "valid": False,
                "error": str(e),
            }
