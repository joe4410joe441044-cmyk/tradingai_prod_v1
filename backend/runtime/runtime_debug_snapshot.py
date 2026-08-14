from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
import math


def build_runtime_debug_result():
    """Return a fresh, JSON-safe telemetry skeleton for one runtime cycle."""
    return {
        "runtimeStageTrace": {},
        "tradingAiMode": "OFF",
        "tradingAiStatus": "NOT_INSTALLED",
        "runtimeAdapterReached": False,
        "runtimeStateReached": False,
        "strategyRuntimeReached": False,
        "strategyOutput": None,
        "strategySignal": None,
        "strategyDirection": None,
        "strategyConfidence": None,
        "momentumTrace": None,
        "momentumPipelineTrace": None,
        "priceHistoryTrace": None,
        "aiMomentumTrace": None,
        "liquidityInstabilityDebug": None,
        "liquidityDeteriorationDebug": None,
        "aiRuntimeReached": False,
        "aiInput": None,
        "aiOutput": None,
        "aiConfidence": None,
        "aiScore": None,
        "aiDecision": None,
        "aiDirection": None,
        "aiHoldReason": None,
        "aiLongCandidate": None,
        "aiShortCandidate": None,
        "aiRawSignal": None,
        "llmInput": None,
        "llmOutput": None,
        "llmDecision": None,
        "llmDecisionSource": None,
        "llmRuleReason": None,
        "llmHoldReason": None,
        "llmRejectReason": None,
        "llmRuleInput": None,
        "llmRuleThresholds": None,
        "llmFallbackUsed": None,
        "llmFallbackReason": None,
        "llmPromptSummary": None,
        "llmRawOutput": None,
        "llmParsedOutput": None,
        "llmParserResult": None,
        "llmRejectBuyReason": None,
        "llmRejectSellReason": None,
        "llmConfidence": None,
        "llmScore": None,
        "llmProbability": None,
        "consensusInput": None,
        "consensusReason": None,
        "moneyManagementReached": False,
        "moneyManagementDecision": None,
        "governanceInput": None,
        "governanceRuntimeReached": False,
        "governanceOutput": None,
        "governanceDecision": None,
        "governanceAllowed": None,
        "governanceBlockedReason": None,
    }


def safe_debug(value, _seen=None):
    """Convert runtime telemetry to values accepted by JSON encoders."""
    try:
        if value is None or isinstance(value, (str, bool, int)):
            return value

        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)

        if isinstance(value, Enum):
            return safe_debug(value.value, _seen)

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")

        if _seen is None:
            _seen = set()

        value_id = id(value)
        if value_id in _seen:
            return "<recursive-reference>"

        _seen.add(value_id)
        try:
            if isinstance(value, Mapping):
                return {
                    str(key): safe_debug(item, _seen)
                    for key, item in value.items()
                }

            if isinstance(value, (list, tuple, set, frozenset)):
                return [safe_debug(item, _seen) for item in value]

            if is_dataclass(value) and not isinstance(value, type):
                return {
                    field.name: safe_debug(
                        getattr(value, field.name),
                        _seen,
                    )
                    for field in fields(value)
                }

            if hasattr(value, "__dict__"):
                return {
                    str(key): safe_debug(item, _seen)
                    for key, item in vars(value).items()
                    if not str(key).startswith("_")
                }

            return str(value)
        finally:
            _seen.remove(value_id)

    except Exception as error:
        return {
            "debugSerializationError": str(error),
            "type": str(type(value)),
        }


def extract_value(source, key, default=None):
    """Read a telemetry value from either a mapping or an object."""
    try:
        if source is None:
            return default

        if isinstance(source, Mapping):
            return source.get(key, default)

        return getattr(source, key, default)

    except Exception:
        return default
