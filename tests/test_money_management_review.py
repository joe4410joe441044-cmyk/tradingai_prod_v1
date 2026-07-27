import unittest
from datetime import datetime, timezone
from decimal import Decimal
from backend.money_management.enums import MoneyManagementProfile, TradingMode, RiskBlockReason, RiskState
from backend.money_management.models import MoneyManagementConfig, MoneyManagementDecisionInput
from backend.money_management.engine import evaluate_money_management
D=Decimal
class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.c=MoneyManagementConfig(MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,TradingMode.PAPER,D("1000"),D(".50"),D("100"),D("5"),D("20"),D("10"),D("5"),False)
    def i(self,side="BUY",entry="2",stop="1.99",**kw):
        b=dict(request_id="review",evaluated_at=datetime(2026,1,1,tzinfo=timezone.utc),symbol="X",requested_size=D("10000"),requested_notional=D("10000"),entry_price=D(entry),stop_loss_price=D(stop),account_equity=D("1000"),eligible_equity=D("1000"),governance_allowed=True,side=side); b.update(kw); return MoneyManagementDecisionInput(**b)
    def test_percent_and_stop_symmetry(self):
        buy=evaluate_money_management(self.i(),self.c); sell=evaluate_money_management(self.i("SELL","2","2.01"),self.c)
        self.assertEqual(buy.risk_amount,D("5")); self.assertEqual(buy.approved_notional,sell.approved_notional); self.assertEqual(buy.approved_size,sell.approved_size)
    def test_limit_winners(self):
        self.assertEqual(evaluate_money_management(self.i(stop="1.999"),self.c).approved_notional,D("100"))
        self.assertEqual(evaluate_money_management(self.i(current_symbol_exposure=D("99")),self.c).approved_notional,D("1"))
        self.assertEqual(evaluate_money_management(self.i(current_total_exposure=D("199")),self.c).approved_notional,D("1"))
    def test_boundaries_and_leverage(self):
        for lev in ("0","5.0"):
            o=evaluate_money_management(self.i(requested_leverage=D(lev)),self.c)
            self.assertEqual(o.risk_allowed,lev=="5.0")
        o=evaluate_money_management(self.i(requested_leverage=D("5.0001")),self.c); self.assertFalse(o.risk_allowed)
    def test_priority_and_immutability(self):
        inp=self.i(current_symbol_exposure=D("100"),requested_leverage=D("6")); before=inp.to_dict()
        o=evaluate_money_management(inp,self.c); self.assertEqual(o.risk_block_reason,RiskBlockReason.MAXIMUM_LEVERAGE); self.assertEqual(inp.to_dict(),before)
    def test_determinism(self):
        x=self.i(); self.assertEqual(evaluate_money_management(x,self.c).to_dict(),evaluate_money_management(x,self.c).to_dict())
if __name__=="__main__": unittest.main()
