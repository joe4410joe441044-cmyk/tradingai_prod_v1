"""Pure MM-1B decision function."""
from .models import MoneyManagementConfig, MoneyManagementDecisionInput, MoneyManagementDecisionOutput
from .enums import DecisionResult, RiskBlockReason, RiskState
from .sizing import evaluate_sizing
def evaluate_money_management(decision_input, config, runtime_state=None):
    """Evaluate basic sizing only; runtime_state is read-only and currently unused."""
    risk,size,notional,allowed,reason,state=evaluate_sizing(decision_input,config)
    result=DecisionResult.APPROVED if allowed and state is RiskState.NORMAL else DecisionResult.SIZE_REDUCED if allowed else DecisionResult.RISK_BLOCKED
    return MoneyManagementDecisionOutput(
        schema_version="money-management-decision-output/v1",
        decision_id=f"mm1b:{decision_input.request_id}",
        request_id=decision_input.request_id,
        evaluated_at=decision_input.evaluated_at,
        approved_size=size,
        approved_notional=notional,
        risk_amount=risk,
        risk_allowed=allowed,
        risk_block_reason=reason,
        risk_state=state,
    )
