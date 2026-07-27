"""Pure MM-2C Daily/Weekly/Monthly loss decision engine."""
from decimal import Decimal
from .enums import RiskState
from .period_models import PeriodType
from .loss_models import *
_PRIORITY=(LossReason.NEGATIVE_EQUITY,LossReason.CASH_FLOW_ADJUSTMENT_UNRESOLVED,LossReason.DRAWDOWN_PERCENT_UNKNOWN,LossReason.INPUT_UNKNOWN,LossReason.CONFIG_INVALID,LossReason.CURRENCY_MISMATCH,LossReason.PERIOD_DATA_MISMATCH,LossReason.MAX_DRAWDOWN_BLOCK,LossReason.DAILY_LOSS_BLOCK,LossReason.WEEKLY_LOSS_BLOCK,LossReason.MONTHLY_LOSS_BLOCK,LossReason.MULTIPLE_WARNINGS,LossReason.DAILY_LOSS_WARNING,LossReason.WEEKLY_LOSS_WARNING,LossReason.MONTHLY_LOSS_WARNING,LossReason.NONE)
def _eval(period_type, aggregate, starting, warning, block, at):
    loss=max(Decimal("0"),-aggregate.net_realized_pnl); pct=loss/starting*Decimal("100")
    if pct>=block: state=ThresholdState.BLOCK; action=ActionDecision.BLOCK
    elif pct>=warning: state=ThresholdState.WARNING; action=ActionDecision.WARN
    else: state=ThresholdState.BELOW_WARNING; action=ActionDecision.ALLOW
    reason={PeriodType.DAILY:(LossReason.DAILY_LOSS_BLOCK,LossReason.DAILY_LOSS_WARNING,LossReason.NONE),PeriodType.WEEKLY:(LossReason.WEEKLY_LOSS_BLOCK,LossReason.WEEKLY_LOSS_WARNING,LossReason.NONE),PeriodType.MONTHLY:(LossReason.MONTHLY_LOSS_BLOCK,LossReason.MONTHLY_LOSS_WARNING,LossReason.NONE)}[period_type][0 if state is ThresholdState.BLOCK else 1 if state is ThresholdState.WARNING else 2]
    return MoneyManagementPeriodLossEvaluation(period_type,aggregate.period.period_key,starting,aggregate.net_realized_pnl,loss,pct,warning,block,state,action,reason,at)
def evaluate_loss_decision(inp):
    if not isinstance(inp,MoneyManagementLossDecisionInput): raise TypeError("typed input required")
    ev=( _eval(PeriodType.DAILY,inp.daily_aggregate,inp.daily_starting_equity,inp.config.daily_warning_pct,inp.config.daily_block_pct,inp.evaluated_at), _eval(PeriodType.WEEKLY,inp.weekly_aggregate,inp.weekly_starting_equity,inp.config.weekly_warning_pct,inp.config.weekly_block_pct,inp.evaluated_at), _eval(PeriodType.MONTHLY,inp.monthly_aggregate,inp.monthly_starting_equity,inp.config.monthly_warning_pct,inp.config.monthly_block_pct,inp.evaluated_at))
    reasons=[]
    if inp.equity_snapshot.current_equity<0: reasons.append(LossReason.NEGATIVE_EQUITY)
    if inp.cash_flow_adjustment_state is not CashFlowAdjustmentState.NONE: reasons.append(LossReason.CASH_FLOW_ADJUSTMENT_UNRESOLVED)
    if inp.equity_snapshot.drawdown_percent is None: reasons.append(LossReason.DRAWDOWN_PERCENT_UNKNOWN)
    elif inp.equity_snapshot.drawdown_percent>=inp.config.maximum_drawdown_pct: reasons.append(LossReason.MAX_DRAWDOWN_BLOCK)
    reasons.extend(x.reason for x in ev if x.threshold_state is ThresholdState.BLOCK)
    warns=[x for x in ev if x.threshold_state is ThresholdState.WARNING]
    if len(warns)>=2: reasons.append(LossReason.MULTIPLE_WARNINGS)
    else: reasons.extend(x.reason for x in warns)
    unique=tuple(r for r in _PRIORITY if r in reasons) or (LossReason.NONE,)
    primary=unique[0] if unique else LossReason.NONE
    locked=bool(unique and primary is not LossReason.NONE and primary not in (LossReason.DAILY_LOSS_WARNING,LossReason.WEEKLY_LOSS_WARNING,LossReason.MONTHLY_LOSS_WARNING,LossReason.MULTIPLE_WARNINGS))
    if locked: state=RiskState.LOCKED; action=ActionDecision.BLOCK
    elif LossReason.MULTIPLE_WARNINGS in unique: state=RiskState.DEFENSIVE; action=ActionDecision.WARN
    elif warns: state=RiskState.CAUTION; action=ActionDecision.WARN
    else: state=RiskState.NORMAL; action=ActionDecision.ALLOW
    return MoneyManagementLossDecision("money-management-loss-decision/v1",inp.evaluated_at,inp.currency,state,action,primary,unique,ev[0],ev[1],ev[2],inp.equity_snapshot.drawdown_percent,inp.equity_snapshot.current_equity<0,inp.cash_flow_adjustment_state,state is RiskState.LOCKED,primary.value)
