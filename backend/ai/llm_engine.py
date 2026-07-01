from backend.utils.log_buffer import runtime_debug


class LLMEngine:

    RUNTIME_RULE_THRESHOLDS = {
        "buy_bias_gt": 0.15,
        "sell_bias_lt": -0.15,
        "momentum_gte": 0.50,
        "imbalance_gt": 0,
    }

    LEGACY_RULE_THRESHOLDS = {
        "volatility_hold_gt": 0.8,
    }

    def __init__(self):

        self.latest_debug = None

    def _record_debug(
        self,
        *,
        decision,
        source,
        rule_reason,
        rule_input,
        rule_thresholds,
        fallback_used,
        fallback_reason,
    ):

        hold_reason = (
            rule_reason
            if decision == "HOLD"
            else None
        )

        self.latest_debug = {
            "llmDecisionSource": source,
            "llmRuleReason": rule_reason,
            "llmHoldReason": hold_reason,
            "llmRejectReason": None,
            "llmRuleInput": rule_input,
            "llmRuleThresholds": rule_thresholds,
            "llmFallbackUsed": fallback_used,
            "llmFallbackReason": fallback_reason,
            "llmPromptSummary": "NOT_APPLICABLE_RULE_ENGINE",
            "llmRawOutput": decision,
            "llmParsedOutput": decision,
            "llmParserResult": "NOT_APPLICABLE_RULE_ENGINE",
        }

        return decision

    def analyze(self, market):

        self.latest_debug = None

        runtime_state = market.get("runtime_state")

        if runtime_state is not None:

            bias = float(
                runtime_state.directional_bias
            )

            momentum = float(
                runtime_state.momentum_score
            )

            imbalance = float(
                runtime_state.imbalance_score
            )

            runtime_debug(
                "AI runtime bias=%s momentum=%s orderflow_delta=%s "
                "imbalance=%s",
                bias,
                momentum,
                runtime_state.orderflow_delta,
                imbalance,
            )

            # ==================================
            # MICROSTRUCTURE EDGE DECISION
            # ==================================

            if (
                bias > 0.15
                and momentum >= 0.50
                and imbalance > 0
            ):
                return self._record_debug(
                    decision="BUY",
                    source="runtime_state_rule",
                    rule_reason=(
                        "BUY because directional_bias > 0.15, "
                        "momentum_score >= 0.50, and "
                        "imbalance_score > 0"
                    ),
                    rule_input={
                        "directional_bias": bias,
                        "momentum_score": momentum,
                        "imbalance_score": imbalance,
                    },
                    rule_thresholds=dict(
                        self.RUNTIME_RULE_THRESHOLDS
                    ),
                    fallback_used=False,
                    fallback_reason=None,
                )

            if (
                bias < -0.15
                and momentum >= 0.50
                and imbalance > 0
            ):
                return self._record_debug(
                    decision="SELL",
                    source="runtime_state_rule",
                    rule_reason=(
                        "SELL because directional_bias < -0.15, "
                        "momentum_score >= 0.50, and "
                        "imbalance_score > 0"
                    ),
                    rule_input={
                        "directional_bias": bias,
                        "momentum_score": momentum,
                        "imbalance_score": imbalance,
                    },
                    rule_thresholds=dict(
                        self.RUNTIME_RULE_THRESHOLDS
                    ),
                    fallback_used=False,
                    fallback_reason=None,
                )

            failed_conditions = []

            if not bias > 0.15 and not bias < -0.15:
                failed_conditions.append(
                    "directional_bias <= 0.15 for BUY and "
                    "directional_bias >= -0.15 for SELL"
                )

            if not momentum >= 0.50:
                failed_conditions.append(
                    "momentum_score < 0.50"
                )

            if not imbalance > 0:
                failed_conditions.append(
                    "imbalance_score <= 0"
                )

            hold_reason = (
                "HOLD because "
                + "; ".join(failed_conditions)
            )

            return self._record_debug(
                decision="HOLD",
                source="runtime_state_rule",
                rule_reason=hold_reason,
                rule_input={
                    "directional_bias": bias,
                    "momentum_score": momentum,
                    "imbalance_score": imbalance,
                },
                rule_thresholds=dict(
                    self.RUNTIME_RULE_THRESHOLDS
                ),
                fallback_used=False,
                fallback_reason=None,
            )

        if market.get("trend") == "up":
            return self._record_debug(
                decision="BUY",
                source="legacy_market_rule",
                rule_reason="BUY because legacy trend is up",
                rule_input={
                    "trend": market.get("trend"),
                    "volatility": market.get("volatility"),
                },
                rule_thresholds=dict(
                    self.LEGACY_RULE_THRESHOLDS
                ),
                fallback_used=True,
                fallback_reason=(
                    "runtime_state missing; used legacy "
                    "market_data rule"
                ),
            )

        volatility = market.get("volatility")

        if volatility is None:
            volatility = 0.0

        if volatility > 0.8:
            return self._record_debug(
                decision="HOLD",
                source="legacy_market_rule",
                rule_reason=(
                    "HOLD because legacy volatility > 0.8 "
                    "and trend is not up"
                ),
                rule_input={
                    "trend": market.get("trend"),
                    "volatility": volatility,
                },
                rule_thresholds=dict(
                    self.LEGACY_RULE_THRESHOLDS
                ),
                fallback_used=True,
                fallback_reason=(
                    "runtime_state missing; used legacy "
                    "market_data rule"
                ),
            )

        return self._record_debug(
            decision="SELL",
            source="legacy_market_rule",
            rule_reason=(
                "SELL because legacy trend is not up and "
                "volatility <= 0.8"
            ),
            rule_input={
                "trend": market.get("trend"),
                "volatility": volatility,
            },
            rule_thresholds=dict(
                self.LEGACY_RULE_THRESHOLDS
            ),
            fallback_used=True,
            fallback_reason=(
                "runtime_state missing; used legacy "
                "market_data rule"
            ),
        )
