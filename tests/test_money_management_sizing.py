import unittest
from datetime import datetime, timezone
from decimal import Decimal
from backend.money_management.enums import MoneyManagementProfile, TradingMode, RiskBlockReason, RiskState
from backend.money_management.models import MoneyManagementConfig, MoneyManagementDecisionInput
from backend.money_management.engine import evaluate_money_management
def D(v): return Decimal(str(v))
class SizingTests(unittest.TestCase):
    def setUp(self):
        self.cfg=MoneyManagementConfig(MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,TradingMode.PAPER,D("1000"),D(".50"),D("100"),D("5"),D("20"),D("10"),D("5"),False)
    def inp(self,side="BUY",entry="100",stop="99",**kw):
        b=dict(request_id="r",evaluated_at=datetime(2026,1,1,tzinfo=timezone.utc),symbol="XRPUSDTM",requested_size=D("1000"),requested_notional=D("1000"),entry_price=D(entry),stop_loss_price=D(stop),account_equity=D("1000"),eligible_equity=D("1000"),governance_allowed=True,side=side); b.update(kw); return MoneyManagementDecisionInput(**b)
    def test_buy_risk_and_position_cap(self):
        o=evaluate_money_management(self.inp(),self.cfg); self.assertTrue(o.risk_allowed); self.assertEqual(o.risk_amount,D("5"),self.cfg); self.assertEqual(o.approved_notional,D("100"),self.cfg); self.assertEqual(o.risk_state,RiskState.DEFENSIVE)
    def test_sell_stop_distance(self):
        o=evaluate_money_management(self.inp("SELL","100","101"),self.cfg); self.assertTrue(o.risk_allowed); self.assertEqual(o.approved_notional,D("100"))
    def test_invalid_stop_fail_closed(self):
        o=evaluate_money_management(self.inp("BUY","100","101"),self.cfg); self.assertFalse(o.risk_allowed); self.assertEqual(o.risk_block_reason,RiskBlockReason.INVALID_STOP)
    def test_exposure_capacity(self):
        o=evaluate_money_management(self.inp(current_symbol_exposure=D("100")),self.cfg); self.assertFalse(o.risk_allowed); self.assertEqual(o.risk_block_reason,RiskBlockReason.SYMBOL_EXPOSURE_LIMIT)
        o=evaluate_money_management(self.inp(current_total_exposure=D("200")),self.cfg); self.assertFalse(o.risk_allowed); self.assertEqual(o.risk_block_reason,RiskBlockReason.TOTAL_EXPOSURE_LIMIT)
    def test_leverage_does_not_amplify_risk(self):
        o=evaluate_money_management(self.inp(requested_leverage=D("5")),self.cfg); self.assertEqual(o.risk_amount,D("5"))
        o=evaluate_money_management(self.inp(requested_leverage=D("6")),self.cfg); self.assertFalse(o.risk_allowed); self.assertEqual(o.risk_block_reason,RiskBlockReason.MAXIMUM_LEVERAGE)
    def test_hold_governance_and_determinism(self):
        o=evaluate_money_management(self.inp("HOLD"),self.cfg); self.assertFalse(o.risk_allowed); self.assertEqual(o.approved_size,D("0"))
        o1=evaluate_money_management(self.inp(),self.cfg); o2=evaluate_money_management(self.inp(),self.cfg); self.assertEqual(o1.to_dict(),o2.to_dict())
    def test_negative_equity(self):
        o=evaluate_money_management(self.inp(eligible_equity=D("-1")),self.cfg); self.assertFalse(o.risk_allowed); self.assertEqual(o.risk_block_reason,RiskBlockReason.INVALID_EQUITY)
if __name__=="__main__": unittest.main()
