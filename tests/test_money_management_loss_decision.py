import unittest
from datetime import datetime, timezone
from decimal import Decimal
from backend.money_management.loss_models import *
from backend.money_management.loss_decision import evaluate_loss_decision
from backend.money_management.period_models import *
from backend.money_management.period_aggregation import period_for, build_period_aggregate
D=Decimal; NOW=datetime(2026,7,26,12,tzinfo=timezone.utc)
def aggregate(net,typ=PeriodType.DAILY):
    p=period_for(NOW,typ)
    e=MoneyManagementPnlEvent(PERIOD_SCHEMA_VERSION,"e-"+typ.value,NOW,NOW,PnlEventType.REALIZED_PNL,"X",D(net),D("0"),D("0"),"USDT",PnlEventSource.EXECUTION_NORMALIZED,1)
    return build_period_aggregate((e,),p)
def snapshot(current="1000",peak="1000"):
    c=D(current); p=D(peak); dd=max(D("0"),p-c); pct=None if p==0 else dd/p*100
    return MoneyManagementEquitySnapshot(PERIOD_SCHEMA_VERSION,NOW,"USDT",D("1000"),c,p,dd,pct,EquitySource.NORMALIZED_EQUITY)
def inp(d="0",w="0",m="0",**kw):
    b=dict(schema_version=PERIOD_SCHEMA_VERSION,evaluated_at=NOW,currency="USDT",daily_aggregate=aggregate(d,PeriodType.DAILY),weekly_aggregate=aggregate(w,PeriodType.WEEKLY),monthly_aggregate=aggregate(m,PeriodType.MONTHLY),daily_starting_equity=D("1000"),weekly_starting_equity=D("1000"),monthly_starting_equity=D("1000"),equity_snapshot=snapshot(),config=LossLimitConfig()); b.update(kw); return MoneyManagementLossDecisionInput(**b)
class LossDecisionTests(unittest.TestCase):
    def test_normal_warning_block_boundaries(self):
        self.assertEqual(evaluate_loss_decision(inp()).risk_state,RiskState.NORMAL)
        self.assertEqual(evaluate_loss_decision(inp(d="-10")).risk_state,RiskState.CAUTION)
        self.assertEqual(evaluate_loss_decision(inp(d="-15")).action,ActionDecision.BLOCK)
        self.assertEqual(evaluate_loss_decision(inp(d="-15")).primary_reason,LossReason.DAILY_LOSS_BLOCK)
    def test_net_loss_not_loss_total_and_multiple_warning(self):
        o=evaluate_loss_decision(inp(d="-10",w="-20")); self.assertEqual(o.risk_state,RiskState.DEFENSIVE); self.assertEqual(o.primary_reason,LossReason.MULTIPLE_WARNINGS)
    def test_drawdown_negative_and_cashflow_priority(self):
        o=evaluate_loss_decision(inp(d="0",equity_snapshot=snapshot("-1","1000"))); self.assertEqual(o.primary_reason,LossReason.NEGATIVE_EQUITY); self.assertEqual(o.risk_state,RiskState.LOCKED)
        o=evaluate_loss_decision(inp(cash_flow_adjustment_state=CashFlowAdjustmentState.DEPOSIT)); self.assertEqual(o.primary_reason,LossReason.CASH_FLOW_ADJUSTMENT_UNRESOLVED)
    def test_drawdown_and_unknown_zero_peak(self):
        o=evaluate_loss_decision(inp(equity_snapshot=snapshot("950","1000"))); self.assertEqual(o.primary_reason,LossReason.MAX_DRAWDOWN_BLOCK)
        o=evaluate_loss_decision(inp(equity_snapshot=snapshot("0","0"))); self.assertEqual(o.primary_reason,LossReason.DRAWDOWN_PERCENT_UNKNOWN)
    def test_determinism_and_serialization(self):
        a=evaluate_loss_decision(inp(d="-10")); b=evaluate_loss_decision(inp(d="-10")); self.assertEqual(a.to_dict(),b.to_dict()); self.assertEqual(a.to_dict()["risk_state"],"CAUTION")
if __name__=="__main__": unittest.main()
