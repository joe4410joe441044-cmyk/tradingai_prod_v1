"""Deterministic human guidance for safely unavailable Advisor information."""

from backend.ai_advisor.conversation_models import AdvisorSourceType
from backend.ai_advisor.response_models import (
    AdvisorActionableUnknown,
    AdvisorUnknown,
    AdvisorUnknownReason,
)


_REASON = {
    AdvisorUnknownReason.SOURCE_MISSING: (
        "AI Advisorに、この内容を確認できる承認済み情報が提供されていません。"
    ),
    AdvisorUnknownReason.SOURCE_STALE: (
        "提供された情報が古いため、現在の状態として確認できません。"
    ),
    AdvisorUnknownReason.SOURCE_EXPIRED: (
        "提供された情報の有効期間が終了しているため、現在の判断には使用できません。"
    ),
    AdvisorUnknownReason.SOURCE_UNKNOWN: (
        "情報源または更新時刻を確認できず、信頼できる現在値として扱えません。"
    ),
    AdvisorUnknownReason.CONTRACT_NOT_DEFINED: (
        "この内容は現在の承認済みTradingAI仕様に定義されていません。"
    ),
    AdvisorUnknownReason.INSUFFICIENT_CONTEXT: (
        "正確に判断するための情報がAI AdvisorのContextに不足しています。"
    ),
}

_MISSING = {
    AdvisorSourceType.RUNTIME: "対象項目の現在の権威あるRuntime / Safety値と更新時刻",
    AdvisorSourceType.SPECIFICATION: "対象項目を定義する承認済みTradingAI仕様",
    AdvisorSourceType.MARKET_INTELLIGENCE: (
        "Market Intelligenceの対象データ、Data Quality、記録時刻"
    ),
    AdvisorSourceType.TRADING_DECISION: (
        "記録済みTrading Decision、根拠、Decision Railwayの状態"
    ),
    AdvisorSourceType.MONEY_MANAGEMENT: (
        "Money Managementの現在のRisk State、判定理由、評価時刻"
    ),
    AdvisorSourceType.GOVERNANCE: "現在のGovernance / Safety状態と理由",
    AdvisorSourceType.EXECUTION_RESULT: "記録済みExecution Outcomeと更新時刻",
    AdvisorSourceType.CONVERSATION: "質問対象を特定できる追加情報",
}

_NEXT_STEP = {
    AdvisorSourceType.RUNTIME: (
        "TradingAIの読み取り専用Runtime / Safety表示で現在値と更新時刻を確認してください。"
    ),
    AdvisorSourceType.SPECIFICATION: (
        "承認済みTradingAI仕様を確認し、見つからない場合はシステム管理者に確認してください。"
    ),
    AdvisorSourceType.MARKET_INTELLIGENCE: (
        "Market Intelligence画面で対象データ、Data Quality、記録時刻を確認してください。"
    ),
    AdvisorSourceType.TRADING_DECISION: (
        "Market IntelligenceのDecision RailwayとDecision Summaryを読み取り専用で確認してください。"
    ),
    AdvisorSourceType.MONEY_MANAGEMENT: (
        "Money Managementの正式なRuntime / Status表示で現在のRisk Stateと評価時刻を確認してください。"
    ),
    AdvisorSourceType.GOVERNANCE: (
        "TradingAIのRuntime / Safety表示でGovernance状態と理由を確認してください。"
    ),
    AdvisorSourceType.EXECUTION_RESULT: (
        "Market IntelligenceのExecution Outcomeまたは正式な実行履歴を読み取り専用で確認してください。"
    ),
    AdvisorSourceType.CONVERSATION: (
        "対象、期間、確認したい状態を追記して、読み取り専用の説明として再確認してください。"
    ),
}

_DEFAULT_MISSING = "対象を正確に確認できる承認済み仕様または読み取り専用の現在情報"
_DEFAULT_NEXT_STEP = (
    "対象コンポーネントの正式な読み取り専用画面または承認済み仕様を確認してください。"
)
_DECISION_IMPACT = (
    "必要な情報を確認できるまで、その情報を前提とする取引判断や運用判断は見送ってください。"
)


def project_actionable_unknown(value: AdvisorUnknown) -> AdvisorActionableUnknown:
    if not isinstance(value, AdvisorUnknown):
        raise TypeError("typed AdvisorUnknown required")
    source_type = value.requiredSourceType
    return AdvisorActionableUnknown(
        unknownId=value.unknownId,
        subject=value.topic,
        reason=_REASON[value.reason],
        missingInformation=_MISSING.get(source_type, _DEFAULT_MISSING),
        safeNextStep=_NEXT_STEP.get(source_type, _DEFAULT_NEXT_STEP),
        decisionImpact=_DECISION_IMPACT,
        operationalEffect="NONE",
    )
