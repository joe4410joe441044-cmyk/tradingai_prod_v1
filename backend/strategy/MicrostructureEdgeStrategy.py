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

from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from backend.utils.log_buffer import runtime_debug
from backend.strategy.normalized_parameters import parameter_value


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

        # --------------------------------------------------------
        # Microstructure Edge Exit holding-time contract.
        #
        # - MIN_HOLD_MS : minimum time a position must be held before a
        #                 "soft" microstructure exit (reversal / momentum
        #                 decay) may fire.  Safety exits (liquidity / spread)
        #                 and the ExecutionEngine SL/TP authority are never
        #                 gated by this floor.
        # - TARGET_HOLD_MS : design target for capturing the short-lived edge.
        # - MAX_HOLD_MS : hard bound.  Reaching it grants a formal MAX_HOLD
        #                 exit so a position is never held indefinitely.
        # --------------------------------------------------------
        self.MIN_HOLD_MS = 500
        self.TARGET_HOLD_MS = 2000
        self.MAX_HOLD_MS = 3000

        # Maximum acceptable age of a fresh feature snapshot used for a
        # profitable, deterministic exit decision.
        self.FEATURE_FRESHNESS_MAX_MS = 1000

        # Single source for the "deterioration" thresholds used by the exit
        # evaluator (stricter than the entry gates).
        self.EXIT_LIQUIDITY_QUALITY_MIN = 0.30
        self.EXIT_SPREAD_QUALITY_MIN = 0.30
        self.EXIT_MOMENTUM_MIN = 0.40

    @staticmethod
    def _uses_normalized_feature_contract(microstructure_state):
        return parameter_value(
            microstructure_state.get("parameterAuthority"),
            "strategyFeatureCalibrationId",
            None,
        ) == "TIME_SYMBOL_NORMALIZED_V1"

    # ============================================================
    # EDGE SCORE
    # ============================================================

    def compute_edge_score(self, microstructure_state):

        normalized_contract = self._uses_normalized_feature_contract(
            microstructure_state
        )

        imbalance = float(
            (
                abs(
                    float(microstructure_state.get("buyPressure", 0.0))
                    - float(microstructure_state.get("sellPressure", 0.0))
                )
                if normalized_contract
                else microstructure_state.get("imbalanceStrength", 0.0)
            )
        )

        momentum = float(
            microstructure_state.get(
                "normalizedMomentum" if normalized_contract else "momentumPersistence",
                0.0,
            )
        )

        spread_quality = float(
            microstructure_state.get(
                "normalizedSpreadQuality" if normalized_contract else "spreadQuality",
                0.0,
            )
        )

        liquidity_quality = float(
            microstructure_state.get(
                "normalizedLiquidityQuality" if normalized_contract else "liquidityQuality",
                0.0,
            )
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
            "normalizedContract": normalized_contract,
            "inputs": {
                "pressureAlignment": round(imbalance, 4),
                "momentum": round(momentum, 4),
                "spreadQuality": round(spread_quality, 4),
                "liquidityQuality": round(liquidity_quality, 4),
            },
        }

    # ============================================================
    # SPREAD SAFETY
    # ============================================================

    def evaluate_spread_safety(self, microstructure_state):

        normalized_contract = self._uses_normalized_feature_contract(
            microstructure_state
        )

        spread = float(
            microstructure_state.get("spread", 0.0)
        )

        liquidity_instability_debug = dict(
            microstructure_state.get(
                "liquidityInstabilityDebug",
                {},
            )
            or {}
        )
        maximum_spread_pct = parameter_value(
            microstructure_state.get("parameterAuthority"),
            "maximumStrategySpreadPct",
            None,
        )
        if maximum_spread_pct is None:
            spread_value = spread
            spread_threshold = self.MAX_SPREAD
            spread_unit = "absolute_price"
        else:
            spread_value = liquidity_instability_debug.get("spreadPct")
            spread_threshold = float(maximum_spread_pct)
            spread_unit = "percent"
        spread_ok = (
            spread_value is not None
            and float(spread_value) <= spread_threshold
        )

        spread_volatility = float(
            microstructure_state.get(
                "spreadVolatility",
                0.0
            )
        )

        liquidity_quality = float(
            microstructure_state.get(
                (
                    "normalizedLiquidityQuality"
                    if normalized_contract
                    else "liquidityQuality"
                ),
                0.0
            )
        )

        spread_safe = True
        spread_risk = None

        # --------------------------------------------------------
        # Widening Spread
        # --------------------------------------------------------

        if not spread_ok:

            spread_safe = False
            spread_risk = "ABNORMAL_SPREAD"

        # --------------------------------------------------------
        # Spread Instability
        # --------------------------------------------------------

        elif not normalized_contract and spread_volatility > 0.65:

            spread_safe = False
            spread_risk = "SPREAD_VOLATILITY"

        # --------------------------------------------------------
        # Liquidity Deterioration
        # --------------------------------------------------------

        elif not normalized_contract and liquidity_quality < 0.35:

            spread_safe = False
            spread_risk = "LIQUIDITY_DETERIORATION"

        total_volume = liquidity_instability_debug.get(
            "totalVolume"
        )
        pressure_diff = liquidity_instability_debug.get(
            "pressureDiff"
        )

        if pressure_diff is None:
            pressure_diff = abs(
                float(
                    microstructure_state.get(
                        "buyPressure",
                        0.0,
                    )
                )
                - float(
                    microstructure_state.get(
                        "sellPressure",
                        0.0,
                    )
                )
            )

        if spread_risk == "ABNORMAL_SPREAD":
            checked_fields = ["spread"]
        elif spread_risk == "SPREAD_VOLATILITY":
            checked_fields = ["spread", "volatility"]
        elif normalized_contract:
            checked_fields = ["spreadPct"]
        else:
            checked_fields = [
                "spread",
                "volatility",
                "liquidityQuality",
            ]

        triggered = (
            spread_risk == "LIQUIDITY_DETERIORATION"
        )
        total_volume_ok = None

        if normalized_contract:
            total_volume_ok = None
        elif total_volume is not None:
            total_volume_liquidity_quality = round(
                min(float(total_volume) / 100000, 1.0),
                4,
            )
            total_volume_ok = (
                total_volume_liquidity_quality >= 0.35
            )

        liquidity_deterioration_debug = {
            "reason": (
                "LIQUIDITY_DETERIORATION"
                if triggered
                else None
            ),
            "triggered": triggered,
            "checkedFields": checked_fields,
            "failedFields": (
                ["liquidityQuality"]
                if triggered
                else []
            ),
            "liquidityQuality": liquidity_quality,
            "marketStability": microstructure_state.get(
                "marketStability"
            ),
            "executionQuality": microstructure_state.get(
                "executionQuality"
            ),
            "spread": spread,
            "spreadOk": spread_ok,
            "totalVolume": total_volume,
            "totalVolumeOk": total_volume_ok,
            "pressureDiff": pressure_diff,
            # pressureDiff is diagnostic only; the current spread safety
            # decision does not apply a pressure threshold.
            "pressureDiffOk": None,
            "volatility": spread_volatility,
            "volatilityOk": spread_volatility <= 0.65,
            "orderbookAggregationMode": (
                liquidity_instability_debug.get(
                    "orderbookAggregationMode"
                )
            ),
            "orderbookAggregationDepth": (
                liquidity_instability_debug.get(
                    "orderbookAggregationDepth"
                )
            ),
        }
        if maximum_spread_pct is not None:
            liquidity_deterioration_debug.update({
                "spreadValue": spread_value,
                "spreadThreshold": spread_threshold,
                "spreadUnit": spread_unit,
            })

        return {
            "spreadSafe": spread_safe,
            "spreadRisk": spread_risk,
            "spreadValue": spread_value,
            "spreadThreshold": spread_threshold,
            "spreadUnit": spread_unit,
            "liquidityDeteriorationDebug": (
                liquidity_deterioration_debug
            ),
        }

    # ============================================================
    # LIQUIDITY SAFETY
    # ============================================================

    def evaluate_liquidity_safety(self, microstructure_state):

        calibration_ready = bool(
            microstructure_state.get(
                "liquidityCalibrationReady",
                True,
            )
        )

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

        # Normalized Paper volume detection is deliberately fail-closed while
        # its causal rolling history warms up.
        liquidity_safe = calibration_ready

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

        if not calibration_ready:
            triggered_reasons.append(
                "normalizedCalibrationWarmup"
            )

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
            "calibrationReady": calibration_ready,
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

        normalized_contract = self._uses_normalized_feature_contract(
            microstructure_state
        )

        momentum_score = float(
            microstructure_state.get(
                (
                    "normalizedMomentum"
                    if normalized_contract
                    else "momentumPersistence"
                ),
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

        if normalized_contract:
            momentum_direction = str(
                microstructure_state.get("momentumDirection", "FLAT")
            ).upper()
            candidate_direction = {
                "LONG": "BUY",
                "SHORT": "SELL",
            }.get(direction, "HOLD")
            direction_aligned = (
                (candidate_direction == "BUY" and momentum_direction == "UP")
                or (
                    candidate_direction == "SELL"
                    and momentum_direction == "DOWN"
                )
            )
            warmup_ready = bool(
                microstructure_state.get("momentumWarmupReady", False)
            )
            return {
                "momentumValid": warmup_ready and direction_aligned,
                "direction": direction,
                "candidateDirection": candidate_direction,
                "momentumDirection": momentum_direction,
                "directionAligned": direction_aligned,
                "warmupReady": warmup_ready,
                "directionPurity": float(
                    microstructure_state.get("directionPurity", 0.0)
                ),
                "activityRatio": float(
                    microstructure_state.get("activityRatio", 0.0)
                ),
                "normalizedMomentum": momentum_score,
                "pressureAlignment": round(directional_alignment, 4),
            }

        momentum_valid = (
            momentum_score >= self.MIN_MOMENTUM_SCORE
            and directional_alignment >= 0.15
        )

        return {
            "momentumValid": momentum_valid,
            "direction": direction,
            "candidateDirection": {
                "LONG": "BUY",
                "SHORT": "SELL",
            }.get(direction, "HOLD"),
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
        minimum_confidence=None,
        normalized_contract=False,
        minimum_composite_score=None,
    ):

        if minimum_confidence is None:
            minimum_confidence = self.MIN_CONFIDENCE

        if normalized_contract:
            if minimum_composite_score is None:
                minimum_composite_score = self.MIN_EDGE_SCORE
            direction_confirmed = momentum_result.get(
                "momentumDirection"
            ) in {"UP", "DOWN"}
            hard_gate_results = {
                "marketSpreadSafety": bool(spread_result["spreadSafe"]),
                "liquiditySafety": bool(liquidity_result["liquiditySafe"]),
                "momentumWarmup": bool(momentum_result.get("warmupReady")),
                "directionConsistency": bool(
                    momentum_result.get("directionAligned")
                ),
                "compositeDecisionScore": (
                    edge_result["edgeScore"] >= minimum_composite_score
                ),
            }
            if not hard_gate_results["marketSpreadSafety"]:
                reason = spread_result["spreadRisk"]
            elif not hard_gate_results["liquiditySafety"]:
                reason = "LIQUIDITY_INSTABILITY"
            elif not hard_gate_results["momentumWarmup"]:
                reason = "MOMENTUM_WARMUP"
            elif not hard_gate_results["directionConsistency"]:
                reason = (
                    "DIRECTION_CONFLICT"
                    if direction_confirmed
                    else "DIRECTION_NOT_CONFIRMED"
                )
            elif not hard_gate_results["compositeDecisionScore"]:
                reason = "LOW_COMPOSITE_SCORE"
            else:
                reason = None
            return {
                "executionAllowed": reason is None,
                "suppressionReason": reason,
                "hardGateResults": hard_gate_results,
            }

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
            < minimum_confidence
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
        microstructure_state,
        edge_result,
        spread_result,
        liquidity_result,
        momentum_result,
        suppression_result,
        minimum_confidence,
        minimum_composite_score,
        normalized_contract,
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

            "minimumConfidence": minimum_confidence,

            "minimumCompositeScore": minimum_composite_score,

            "featureContract": (
                "TIME_SYMBOL_NORMALIZED_V1"
                if normalized_contract
                else "LEGACY_CALLBACK_WINDOW"
            ),

            "parameterAuthority": dict(
                microstructure_state.get("parameterAuthority")
                or {}
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

            "momentumDirection": momentum_result.get("momentumDirection"),

            "directionPurity": momentum_result.get("directionPurity"),

            "activityRatio": momentum_result.get("activityRatio"),

            "normalizedMomentum": momentum_result.get(
                "normalizedMomentum"
            ),

            "directionAligned": momentum_result.get("directionAligned"),

            "normalizedSpreadQuality": edge_result.get("inputs", {}).get(
                "spreadQuality"
            ),

            "normalizedLiquidityQuality": edge_result.get("inputs", {}).get(
                "liquidityQuality"
            ),

            "edgeInputs": dict(edge_result.get("inputs") or {}),

            "hardGateResults": dict(
                suppression_result.get("hardGateResults") or {}
            ),

            "liquidityInstabilityDebug": (
                liquidity_result[
                    "liquidityInstabilityDebug"
                ]
            ),

            "liquidityDeteriorationDebug": (
                spread_result[
                    "liquidityDeteriorationDebug"
                ]
            ),

            "timestamp": (
                datetime.utcnow().isoformat()
            ),
        }

        strategy_state["entryReadiness"] = (
            self.build_entry_readiness(
                microstructure_state,
                edge_result,
                spread_result,
                liquidity_result,
                momentum_result,
                suppression_result,
                minimum_confidence,
                minimum_composite_score,
                normalized_contract,
            )
        )

        return strategy_state

    @staticmethod
    def _source_status(state, key, *, derived=False):
        if derived:
            return "DERIVED"
        return "MEASURED" if key in state and state.get(key) is not None else "DEFAULTED"

    @staticmethod
    def _condition(code, current, threshold=None, operator=None, *,
                   expected=None, source_status="MEASURED", delta=None):
        if source_status == "MISSING":
            status = "NOT AVAILABLE"
        elif current is None:
            status = "NOT EVALUATED"
        elif expected is not None:
            status = "PASS" if current == expected else "FAIL"
        elif operator == "<=":
            status = "PASS" if current <= threshold else "FAIL"
        elif operator == ">=":
            status = "PASS" if current >= threshold else "FAIL"
        else:
            status = "NOT EVALUATED"
        return {
            "code": code,
            "status": status,
            "currentValue": current,
            "threshold": threshold,
            "operator": operator,
            "expected": expected,
            "delta": delta,
            "sourceStatus": source_status,
        }

    def build_entry_readiness(
        self, state, edge, spread_result, liquidity_result,
        momentum_result, suppression, minimum_confidence,
        minimum_composite_score, normalized_contract,
    ):
        """Publish the values already used by this evaluation; never re-evaluate it."""
        if normalized_contract:
            direction = momentum_result["direction"]
            candidate = momentum_result.get("candidateDirection") or {
                "LONG": "BUY",
                "SHORT": "SELL",
            }.get(direction, "HOLD")
            decision = candidate if suppression["executionAllowed"] else "HOLD"
            hard_gates = dict(suppression.get("hardGateResults") or {})
            conditions = [
                self._condition(
                    "MARKET_SPREAD_SAFETY",
                    hard_gates.get("marketSpreadSafety"),
                    expected=True,
                    source_status="DERIVED",
                ),
                self._condition(
                    "LIQUIDITY_SAFETY",
                    hard_gates.get("liquiditySafety"),
                    expected=True,
                    source_status="DERIVED",
                ),
                self._condition(
                    "MOMENTUM_WARMUP",
                    hard_gates.get("momentumWarmup"),
                    expected=True,
                    source_status="DERIVED",
                ),
                self._condition(
                    "DIRECTION_CONSISTENCY",
                    hard_gates.get("directionConsistency"),
                    expected=True,
                    source_status="DERIVED",
                ),
                self._condition(
                    "COMPOSITE_SCORE",
                    edge["edgeScore"],
                    minimum_composite_score,
                    ">=",
                    source_status="DERIVED",
                    delta=round(
                        max(0.0, minimum_composite_score - edge["edgeScore"]),
                        4,
                    ),
                ),
                {
                    "code": "CONFIDENCE_DIAGNOSTIC",
                    "status": "DIAGNOSTIC",
                    "currentValue": edge["confidence"],
                    "threshold": None,
                    "operator": None,
                    "expected": None,
                    "delta": None,
                    "sourceStatus": "DERIVED",
                },
            ]
            blocker_by_reason = {
                "ABNORMAL_SPREAD": "MARKET_SPREAD_SAFETY",
                "SPREAD_VOLATILITY": "MARKET_SPREAD_SAFETY",
                "LIQUIDITY_DETERIORATION": "MARKET_SPREAD_SAFETY",
                "LIQUIDITY_INSTABILITY": "LIQUIDITY_SAFETY",
                "MOMENTUM_WARMUP": "MOMENTUM_WARMUP",
                "DIRECTION_CONFLICT": "DIRECTION_CONSISTENCY",
                "DIRECTION_NOT_CONFIRMED": "DIRECTION_CONSISTENCY",
                "LOW_COMPOSITE_SCORE": "COMPOSITE_SCORE",
            }
            return {
                "available": True,
                "schemaVersion": 2,
                "strategy": self.__class__.__name__,
                "featureContract": "TIME_SYMBOL_NORMALIZED_V1",
                "strategyDecision": decision,
                "candidateDirection": candidate,
                "rawDirection": direction,
                "executionAllowed": suppression["executionAllowed"],
                "edgeScore": edge["edgeScore"],
                "confidence": edge["confidence"],
                "confidenceSemantics": "DIAGNOSTIC_ONLY_AT_STRATEGY",
                "conditions": conditions,
                "hardGateResults": hard_gates,
                "blockingCondition": blocker_by_reason.get(
                    suppression["suppressionReason"]
                ),
                "suppressionReason": suppression["suppressionReason"],
            }

        spread = float(state.get("spread", 0.0))
        spread_value = spread_result.get("spreadValue", spread)
        spread_threshold = spread_result.get(
            "spreadThreshold",
            self.MAX_SPREAD,
        )
        spread_volatility = float(state.get("spreadVolatility", 0.0))
        liquidity = float(state.get("liquidityQuality", 0.0))
        momentum = float(state.get("momentumPersistence", 0.0))
        buy_pressure = float(state.get("buyPressure", 0.0))
        sell_pressure = float(state.get("sellPressure", 0.0))
        alignment = abs(buy_pressure - sell_pressure)
        absorption = bool(state.get("absorptionDetected", False))
        stagnant = bool(state.get("stagnantHeavyFlow", False))
        fake_pressure = bool(state.get("fakePressureDetected", False))
        volume = liquidity_result["liquidityInstabilityDebug"].get("totalVolume")

        def gap_ge(value, threshold):
            return round(max(0.0, threshold - value), 4)

        def gap_le(value, threshold):
            return round(max(0.0, value - threshold), 4)

        conditions = [
            self._condition("SPREAD", spread_value, spread_threshold, "<=",
                            source_status=self._source_status(state, "spread"), delta=gap_le(spread_value, spread_threshold)),
            self._condition("SPREAD_VOLATILITY", spread_volatility, 0.65, "<=",
                            source_status=self._source_status(state, "spreadVolatility"), delta=gap_le(spread_volatility, 0.65)),
            self._condition("LIQUIDITY_QUALITY", liquidity, 0.35, ">=",
                            source_status=self._source_status(state, "liquidityQuality"), delta=gap_ge(liquidity, 0.35)),
            self._condition("LIQUIDITY_VOLUME", float(volume) if volume is not None else None, 35000, ">=",
                            source_status="DERIVED" if volume is not None else "MISSING",
                            delta=gap_ge(float(volume), 35000) if volume is not None else None),
            self._condition("ABSORPTION", absorption, expected=False,
                            source_status=self._source_status(state, "absorptionDetected")),
            self._condition("STAGNANT_FLOW", stagnant, expected=False,
                            source_status=self._source_status(state, "stagnantHeavyFlow")),
            self._condition("FAKE_PRESSURE", fake_pressure, expected=False,
                            source_status=self._source_status(state, "fakePressureDetected")),
            self._condition("LIQUIDITY_SAFETY", liquidity_result["liquiditySafe"], expected=True,
                            source_status="DERIVED"),
            self._condition("MOMENTUM", momentum, 0.50, ">=",
                            source_status=self._source_status(state, "momentumPersistence"), delta=gap_ge(momentum, 0.50)),
            self._condition("PRESSURE_ALIGNMENT", round(alignment, 4), 0.15, ">=",
                            source_status="DERIVED", delta=gap_ge(alignment, 0.15)),
            self._condition("EDGE", edge["edgeScore"], 0.55, ">=", source_status="DERIVED"),
            self._condition("CONFIDENCE", edge["confidence"], minimum_confidence, ">=", source_status="DERIVED"),
        ]
        direction = momentum_result["direction"]
        candidate = {"LONG": "BUY", "SHORT": "SELL"}.get(direction, "HOLD")
        decision = candidate if suppression["executionAllowed"] else "HOLD"
        blocker_by_reason = {
            "ABNORMAL_SPREAD": "SPREAD",
            "SPREAD_VOLATILITY": "SPREAD_VOLATILITY",
            "LIQUIDITY_DETERIORATION": "LIQUIDITY_QUALITY",
            "LIQUIDITY_INSTABILITY": "LIQUIDITY_SAFETY",
            "CONFLICTING_MOMENTUM": (
                "MOMENTUM"
                if momentum < self.MIN_MOMENTUM_SCORE
                else "PRESSURE_ALIGNMENT"
            ),
            "WEAK_EDGE": "EDGE",
            "LOW_CONFIDENCE": "CONFIDENCE",
        }
        return {
            "available": True,
            "schemaVersion": 1,
            "strategy": self.__class__.__name__,
            "strategyDecision": decision,
            "candidateDirection": candidate,
            "rawDirection": direction,
            "executionAllowed": suppression["executionAllowed"],
            "edgeScore": edge["edgeScore"],
            "confidence": edge["confidence"],
            "conditions": conditions,
            "blockingCondition": blocker_by_reason.get(suppression["suppressionReason"]),
            "suppressionReason": suppression["suppressionReason"],
        }

    # ============================================================
    # EXIT REASONS
    # ============================================================

    class ExitReason(str, Enum):
        STOP_LOSS = "STOP_LOSS"
        TAKE_PROFIT = "TAKE_PROFIT"
        MAX_HOLD = "MAX_HOLD"
        MICROSTRUCTURE_REVERSAL = "MICROSTRUCTURE_REVERSAL"
        MOMENTUM_DECAY = "MOMENTUM_DECAY"
        LIQUIDITY_DETERIORATION = "LIQUIDITY_DETERIORATION"
        SPREAD_DIVERGENCE = "SPREAD_DIVERGENCE"

    # ============================================================
    # EXIT DECISION CONTRACT
    # ============================================================

    @dataclass(frozen=True)
    class ExitDecision:
        symbol: str
        position_side: str
        entry_price: float
        current_price: float
        opened_at: float
        evaluated_at: float
        holding_duration_ms: float
        decision: str  # "HOLD" or "EXIT"
        reason: Optional[str]
        feature_timestamp: float
        feature_fresh: bool
        trace_id: Optional[str]

        def to_dict(self):
            return {
                "symbol": self.symbol,
                "positionSide": self.position_side,
                "entryPrice": self.entry_price,
                "currentPrice": self.current_price,
                "openedAt": self.opened_at,
                "evaluatedAt": self.evaluated_at,
                "holdingDurationMs": self.holding_duration_ms,
                "decision": self.decision,
                "reason": self.reason,
                "featureTimestamp": self.feature_timestamp,
                "featureFresh": self.feature_fresh,
                "traceId": self.trace_id,
            }

    # ============================================================
    # EXIT EVALUATION
    # ============================================================

    @staticmethod
    def _parse_feature_timestamp(value):
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                parsed = datetime.fromisoformat(
                    text.replace("Z", "+00:00")
                )
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        return None

    @staticmethod
    def _position_field(position_info, key, default):
        try:
            value = position_info.get(key)
        except AttributeError:
            return default
        return default if value is None else value

    def evaluate_exit(
        self,
        microstructure_state,
        position_info,
    ):
        """
        Evaluate whether an OPEN position should be exited.

        This is a deterministic, side-aware, symbol-matched evaluator.  It
        never fabricates a profitable exit from stale / unknown / mismatched
        features: invalid inputs produce HOLD with an explicit reason.

        position_info fields:
            symbol, positionSide ("BUY"/"SELL"), entryPrice, currentPrice,
            openedAt (epoch seconds), optional traceId, optional evaluatedAt.
        """

        if not isinstance(microstructure_state, dict):
            return self._invalid_exit_decision(
                self._position_field(position_info, "symbol", "UNKNOWN"),
                self._position_field(position_info, "positionSide", "UNKNOWN"),
                self._position_field(position_info, "entryPrice", 0.0),
                self._position_field(position_info, "currentPrice", 0.0),
                self._position_field(position_info, "openedAt", 0.0),
                "INVALID_FEATURE_STATE",
            )

        position_info = dict(position_info or {})

        required_fields = [
            "symbol", "positionSide", "entryPrice", "currentPrice", "openedAt",
        ]
        for field in required_fields:
            if position_info.get(field) is None:
                return self._invalid_exit_decision(
                    position_info.get("symbol", "UNKNOWN"),
                    position_info.get("positionSide", "UNKNOWN"),
                    position_info.get("entryPrice", 0.0),
                    position_info.get("currentPrice", 0.0),
                    position_info.get("openedAt", 0.0),
                    "INVALID_POSITION_INFO",
                )

        symbol = str(position_info["symbol"]).strip().upper()
        position_side = str(position_info["positionSide"]).strip().upper()
        position_side = {
            "LONG": "BUY",
            "SHORT": "SELL",
        }.get(position_side, position_side)
        entry_price = float(position_info["entryPrice"])
        current_price = float(position_info["currentPrice"])
        opened_at = float(position_info["openedAt"])
        trace_id = position_info.get("traceId")

        evaluated_at = float(
            position_info.get("evaluatedAt")
            if position_info.get("evaluatedAt") is not None
            else datetime.now(timezone.utc).timestamp()
        )
        holding_duration_ms = (evaluated_at - opened_at) * 1000

        # --------------------------------------------------------
        # Symbol identity
        # --------------------------------------------------------
        state_symbol = str(
            microstructure_state.get("symbol") or ""
        ).strip().upper()
        if state_symbol and state_symbol != symbol:
            return self._invalid_exit_decision(
                symbol, position_side, entry_price, current_price,
                opened_at, "SYMBOL_MISMATCH", evaluated_at,
            )

        # --------------------------------------------------------
        # Feature freshness
        # --------------------------------------------------------
        feature_timestamp = self._parse_feature_timestamp(
            microstructure_state.get("timestamp")
        )
        if feature_timestamp is None:
            feature_timestamp = evaluated_at
        feature_age_ms = (evaluated_at - feature_timestamp) * 1000
        feature_fresh = feature_age_ms < self.FEATURE_FRESHNESS_MAX_MS

        if not feature_fresh:
            return self._invalid_exit_decision(
                symbol, position_side, entry_price, current_price,
                opened_at, "STALE_FEATURES", evaluated_at,
            )

        # --------------------------------------------------------
        # Deterministic exit evaluation
        # --------------------------------------------------------
        exit_reason = self._evaluate_exit_conditions(
            microstructure_state, position_side, holding_duration_ms,
        )
        if isinstance(exit_reason, self.ExitReason):
            exit_reason = exit_reason.value

        return self.ExitDecision(
            symbol=symbol,
            position_side=position_side,
            entry_price=entry_price,
            current_price=current_price,
            opened_at=opened_at,
            evaluated_at=evaluated_at,
            holding_duration_ms=holding_duration_ms,
            decision="EXIT" if exit_reason else "HOLD",
            reason=exit_reason,
            feature_timestamp=feature_timestamp,
            feature_fresh=feature_fresh,
            trace_id=trace_id,
        )

    def _invalid_exit_decision(
        self,
        symbol,
        position_side,
        entry_price,
        current_price,
        opened_at,
        reason,
        evaluated_at=None,
    ):
        """Fail-closed HOLD for invalid / unsafe feature evidence."""
        evaluated_at = (
            evaluated_at
            if evaluated_at is not None
            else datetime.now(timezone.utc).timestamp()
        )
        return self.ExitDecision(
            symbol=symbol,
            position_side=position_side,
            entry_price=entry_price,
            current_price=current_price,
            opened_at=opened_at,
            evaluated_at=evaluated_at,
            holding_duration_ms=0,
            decision="HOLD",
            reason=reason,
            feature_timestamp=evaluated_at,
            feature_fresh=False,
            trace_id=None,
        )

    def _evaluate_exit_conditions(
        self,
        microstructure_state,
        position_side,
        holding_duration_ms,
    ):
        """
        Deterministic exit priority (highest first).  Generic SL/TP remain
        the ExecutionEngine's authority and are intentionally not duplicated
        here:

        1. Microstructure reversal     (side-aware, immediate)
        2. Liquidity deterioration     (unsafe / weak liquidity)
        3. Spread deterioration        (unsafe / divergent spread)
        4. Momentum decay              (side-aware, gated by MIN_HOLD_MS)
        5. Max hold                    (hard holding-time bound)
        6. HOLD
        """

        normalized_contract = self._uses_normalized_feature_contract(
            microstructure_state
        )

        reversal_reason = self._evaluate_microstructure_reversal(
            microstructure_state, position_side, normalized_contract,
        )
        if reversal_reason:
            return reversal_reason

        liquidity_reason = self._evaluate_liquidity_deterioration(
            microstructure_state, normalized_contract,
        )
        if liquidity_reason:
            return liquidity_reason

        spread_reason = self._evaluate_spread_deterioration(
            microstructure_state, normalized_contract,
        )
        if spread_reason:
            return spread_reason

        if holding_duration_ms >= self.MIN_HOLD_MS:
            momentum_reason = self._evaluate_momentum_decay(
                microstructure_state, position_side, normalized_contract,
            )
            if momentum_reason:
                return momentum_reason

        if holding_duration_ms >= self.MAX_HOLD_MS:
            return self.ExitReason.MAX_HOLD

        return None

    def _evaluate_microstructure_reversal(
        self,
        microstructure_state,
        position_side,
        normalized_contract,
    ):
        """Side-aware directional reversal evidence."""

        if normalized_contract:
            momentum_direction = str(
                microstructure_state.get("momentumDirection", "FLAT")
            ).upper()
        else:
            direction = self.evaluate_momentum_continuation(
                microstructure_state
            )["direction"]
            momentum_direction = {
                "LONG": "UP",
                "SHORT": "DOWN",
            }.get(direction, "FLAT")

        if position_side == "BUY" and momentum_direction == "DOWN":
            return self.ExitReason.MICROSTRUCTURE_REVERSAL
        if position_side == "SELL" and momentum_direction == "UP":
            return self.ExitReason.MICROSTRUCTURE_REVERSAL

        return None

    def _evaluate_liquidity_deterioration(
        self,
        microstructure_state,
        normalized_contract,
    ):
        """Unsafe liquidity (formal authority) or weak liquidity quality."""

        liquidity_result = self.evaluate_liquidity_safety(
            microstructure_state
        )
        if not liquidity_result.get("liquiditySafe", False):
            return self.ExitReason.LIQUIDITY_DETERIORATION

        liquidity_quality = float(
            microstructure_state.get(
                "normalizedLiquidityQuality"
                if normalized_contract
                else "liquidityQuality",
                self.EXIT_LIQUIDITY_QUALITY_MIN,
            )
        )
        if liquidity_quality < self.EXIT_LIQUIDITY_QUALITY_MIN:
            return self.ExitReason.LIQUIDITY_DETERIORATION

        return None

    def _evaluate_spread_deterioration(
        self,
        microstructure_state,
        normalized_contract,
    ):
        """Unsafe spread (formal authority) or divergent spread quality."""

        spread_result = self.evaluate_spread_safety(
            microstructure_state
        )
        if not spread_result.get("spreadSafe", True):
            return self.ExitReason.SPREAD_DIVERGENCE

        spread_quality = float(
            microstructure_state.get(
                "normalizedSpreadQuality"
                if normalized_contract
                else "spreadQuality",
                self.EXIT_SPREAD_QUALITY_MIN,
            )
        )
        if spread_quality < self.EXIT_SPREAD_QUALITY_MIN:
            return self.ExitReason.SPREAD_DIVERGENCE

        return None

    def _evaluate_momentum_decay(
        self,
        microstructure_state,
        position_side,
        normalized_contract,
    ):
        """Side-aware loss of the formal momentum evidence present at entry."""

        momentum_score = float(
            microstructure_state.get(
                "normalizedMomentum"
                if normalized_contract
                else "momentumPersistence",
                0.0,
            )
        )

        if normalized_contract:
            momentum_direction = str(
                microstructure_state.get("momentumDirection", "FLAT")
            ).upper()
            if position_side == "BUY" and momentum_direction != "UP":
                return self.ExitReason.MOMENTUM_DECAY
            if position_side == "SELL" and momentum_direction != "DOWN":
                return self.ExitReason.MOMENTUM_DECAY
        else:
            momentum_result = self.evaluate_momentum_continuation(
                microstructure_state
            )
            if not momentum_result.get("momentumValid", False):
                return self.ExitReason.MOMENTUM_DECAY

        if momentum_score < self.EXIT_MOMENTUM_MIN:
            return self.ExitReason.MOMENTUM_DECAY

        return None

    # ============================================================
    # MAIN STRATEGY PIPELINE
    # ============================================================

    def process_microstructure_strategy(
        self,
        microstructure_state,
    ):

        try:

            normalized_contract = self._uses_normalized_feature_contract(
                microstructure_state
            )

            minimum_confidence = float(parameter_value(
                microstructure_state.get("parameterAuthority"),
                "minimumStrategyConfidence",
                self.MIN_CONFIDENCE,
            ))
            minimum_composite_score = float(parameter_value(
                microstructure_state.get("parameterAuthority"),
                "minimumCompositeScore",
                self.MIN_EDGE_SCORE,
            ))

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
                    minimum_confidence,
                    normalized_contract=normalized_contract,
                    minimum_composite_score=minimum_composite_score,
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
                    microstructure_state,
                    edge_result,
                    spread_result,
                    liquidity_result,
                    momentum_result,
                    suppression_result,
                    minimum_confidence,
                    minimum_composite_score,
                    normalized_contract,
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
