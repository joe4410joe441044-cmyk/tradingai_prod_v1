"""Deterministic pre-provider request refusal classification."""

import re
import unicodedata
from enum import Enum
from typing import Optional

from backend.ai_advisor.conversation_models import AdvisorContractModel


class AdvisorSafetyRefusalCategory(str, Enum):
    TRADING_INSTRUCTION = "TRADING_INSTRUCTION"
    ORDER_EXECUTION = "ORDER_EXECUTION"
    BOT_OPERATION = "BOT_OPERATION"
    EMERGENCY_UNLOCK = "EMERGENCY_UNLOCK"
    GOVERNANCE_BYPASS = "GOVERNANCE_BYPASS"
    RISK_LIMIT_CHANGE = "RISK_LIMIT_CHANGE"
    CONFIGURATION_MUTATION = "CONFIGURATION_MUTATION"
    CREDENTIAL_DISCLOSURE = "CREDENTIAL_DISCLOSURE"
    SYSTEM_PROMPT_DISCLOSURE = "SYSTEM_PROMPT_DISCLOSURE"
    HIDDEN_REASONING = "HIDDEN_REASONING"
    EXTERNAL_TRANSMISSION = "EXTERNAL_TRANSMISSION"
    CONVERSATION_PERSISTENCE = "CONVERSATION_PERSISTENCE"
    PROFIT_GUARANTEE = "PROFIT_GUARANTEE"
    RAW_INTERNAL_OBJECT = "RAW_INTERNAL_OBJECT"
    PROMPT_INJECTION = "PROMPT_INJECTION"


class AdvisorRequestSafetyDecision(AdvisorContractModel):
    allowed: bool
    refusalCategory: Optional[AdvisorSafetyRefusalCategory] = None
    safeReason: Optional[str] = None
    safeAlternative: Optional[str] = None


_RULES = (
    (
        AdvisorSafetyRefusalCategory.PROMPT_INJECTION,
        r"ignore .{0,30}(system|previous)|disable safety|highest.priority instruction|以前の指示を無視",
    ),
    (
        AdvisorSafetyRefusalCategory.CREDENTIAL_DISCLOSURE,
        r"(reveal|show|print|教えて).{0,24}(credential|api.?key|password|token|認証情報)",
    ),
    (
        AdvisorSafetyRefusalCategory.SYSTEM_PROMPT_DISCLOSURE,
        r"(reveal|show|print|見せて).{0,20}(system prompt|システムプロンプト)",
    ),
    (
        AdvisorSafetyRefusalCategory.HIDDEN_REASONING,
        r"(hidden reasoning|chain.of.thought|内部推論|思考過程)",
    ),
    (
        AdvisorSafetyRefusalCategory.ORDER_EXECUTION,
        r"(send|submit|cancel|execute).{0,20}(order|trade)|注文.{0,12}(送信|実行|取消)",
    ),
    (
        AdvisorSafetyRefusalCategory.BOT_OPERATION,
        r"(start|stop|restart|turn on).{0,16}(bot|loop)|bot.{0,12}(開始|停止)|ループをオン",
    ),
    (
        AdvisorSafetyRefusalCategory.EMERGENCY_UNLOCK,
        r"(unlock|解除).{0,18}(emergency|緊急)",
    ),
    (
        AdvisorSafetyRefusalCategory.GOVERNANCE_BYPASS,
        r"(bypass|override|回避|無視).{0,20}(governance|ガバナンス)",
    ),
    (
        AdvisorSafetyRefusalCategory.RISK_LIMIT_CHANGE,
        r"(change|increase|raise|変更).{0,18}(risk limit|risk percent|リスク上限)",
    ),
    (
        AdvisorSafetyRefusalCategory.CONFIGURATION_MUTATION,
        r"(change|write|update|変更).{0,16}(configuration|config|設定)",
    ),
    (
        AdvisorSafetyRefusalCategory.EXTERNAL_TRANSMISSION,
        r"(send|upload|送信).{0,24}(external|provider|openai|外部)",
    ),
    (
        AdvisorSafetyRefusalCategory.CONVERSATION_PERSISTENCE,
        r"(save|persist|store|保存).{0,20}(conversation|chat|会話)",
    ),
    (
        AdvisorSafetyRefusalCategory.PROFIT_GUARANTEE,
        r"(guarantee|確実|保証).{0,20}(profit|利益|no loss|損失)",
    ),
    (
        AdvisorSafetyRefusalCategory.RAW_INTERNAL_OBJECT,
        r"(raw|生の).{0,20}(manager|runtime object|internal object|内部オブジェクト)",
    ),
    (
        AdvisorSafetyRefusalCategory.TRADING_INSTRUCTION,
        r"(buy|sell|long|short|買う|売る).{0,20}(now|signal|数量|いま|今)",
    ),
)


def evaluate_advisor_request(prompt: str) -> AdvisorRequestSafetyDecision:
    normalized = unicodedata.normalize("NFKC", prompt).casefold()
    for category, expression in _RULES:
        if re.search(expression, normalized, re.IGNORECASE):
            return AdvisorRequestSafetyDecision(
                allowed=False,
                refusalCategory=category,
                safeReason="This request exceeds the read-only advisor boundary.",
                safeAlternative="Ask for a read-only explanation of an approved recorded state or specification.",
            )
    return AdvisorRequestSafetyDecision(allowed=True)
