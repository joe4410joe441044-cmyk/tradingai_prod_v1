"""Deterministic explanation of missing/non-current Supervisor evidence only."""
from __future__ import annotations
from .contracts import Freshness, InputValueState, SupervisorAgentId
from .conversation_contracts import HumanActionableUnknown

_LABELS={"bot":"Bot runtime state","loop":"Runtime loop state","trade":"Trade safety state","governance":"Governance safety state","emergency":"Emergency safety state","execution":"Execution state","market":"Market state","decision":"Current trading decision","health":"System health state","moneyManagement":"Money Management state"}
_CRITICAL={"governance","emergency","execution","health","moneyManagement"}
_STEPS={
 "moneyManagement":"Money Managementの読み取り専用Runtime表示で現在の正式な状態を確認してください。",
 "market":"Market Intelligenceの読み取り専用表示で現在値と更新時刻を確認してください。",
 "emergency":"Emergencyの読み取り専用Safety表示で現在の正式な状態を確認してください。",
 "governance":"Governanceの読み取り専用状態で現在の実行許可と更新時刻を確認してください。",
 "execution":"Executionの読み取り専用Runtime表示で現在の状態を確認してください。",
 "health":"System Healthの読み取り専用診断で現在の状態を確認してください。",
 "bot":"Botの読み取り専用Runtime表示で現在の状態を確認してください。",
 "loop":"Runtime Loopの読み取り専用状態を確認してください。",
 "trade":"Trade Safetyの読み取り専用表示で現在のモードと安全ゲートを確認してください。",
 "decision":"最新の読み取り専用Decision表示と根拠の更新時刻を確認してください。"}

def _reason(freshness, state=None):
 if freshness is Freshness.STALE:return "STALE","取得済みの根拠がFreshness規則を満たさず、現在値として扱えません。"
 if freshness is Freshness.CONFLICTED:return "DEGRADED","複数の権威ソースが一致せず、現在の正式な値を確定できません。"
 if freshness is Freshness.MISSING or state is InputValueState.ABSENT:return "UNAVAILABLE","判断に必要な権威あるRuntime根拠を取得できていません。"
 if state is InputValueState.NULL:return "UNKNOWN","権威ソースは応答しましたが、この値を提供していません。"
 return "UNKNOWN","取得した根拠だけでは、現在の正式な値を確定できません。"

def _item(domain, subject, freshness, state=None, source=None, field=None):
 status,reason=_reason(freshness,state)
 impact=("必要なSafety情報を確認できるまで、実行可能とは判断せず、依存する判断を保留してください。" if domain in _CRITICAL else "現在値を確認できないため、この情報を前提とする判断は保留してください。")
 return HumanActionableUnknown(status=status,subject=subject,reason=reason,missingInformation=f"現在の正式な{subject}",safeNextStep=_STEPS[domain],decisionImpact=impact,source=source,evidenceField=field)

def build_actionable_unknowns(snapshot, agent_id):
 domains=("moneyManagement",) if agent_id is SupervisorAgentId.MM_SUPERVISOR else tuple(_LABELS)
 out=[]
 for name in domains:
  domain=getattr(snapshot,name); fresh=domain.freshness
  if fresh is not Freshness.FRESH:out.append(_item(name,_LABELS[name],fresh,source=getattr(domain,"source",None),field="freshness"))
  for observation in getattr(domain,"fieldStates",()):
   if observation.state is not InputValueState.PRESENT:out.append(_item(name,f"{_LABELS[name]} / {observation.field}",fresh,observation.state,getattr(domain,"source",None),observation.field))
 return tuple(out[:50])

def provider_failure_explanation(code):
 return HumanActionableUnknown(status="UNAVAILABLE",subject="Supervisor AI interpretation",reason=f"AI interpretation provider did not return a validated response ({code}).",missingInformation="権威あるRuntime根拠に基づく補助的な自然言語説明",safeNextStep="Supervisor Snapshotの読み取り専用表示を確認し、必要なら管理者へprovider状態の確認を依頼してください。",decisionImpact="AI説明がなくても決定論的Runtimeは独立しています。未確認事項を推測せず、依存する判断は保留してください。",source="SUPERVISOR_PROVIDER",evidenceField="availability")
