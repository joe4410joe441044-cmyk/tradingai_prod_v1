import unittest
from datetime import datetime, timezone
from decimal import Decimal
from backend.money_management import *
def D(v): return Decimal(str(v))
class MoneyManagementModelTests(unittest.TestCase):
    def config(self,**kw):
        b=dict(profile=MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,mode=TradingMode.PAPER,initial_reference_equity=D("1000"),risk_per_trade_pct=D(".50"),maximum_position_notional=D("100"),maximum_drawdown_pct=D("5"),total_exposure_pct=D("20"),single_symbol_exposure_pct=D("10"),maximum_leverage=D("5"),multi_bot_enabled=False); b.update(kw); return MoneyManagementConfig(**b)
    def test_baseline(self):
        c=self.config(); self.assertEqual(c.to_dict()["mode"],"PAPER"); self.assertEqual(c.to_dict()["initial_reference_equity"],"1000")
    def test_strict_types(self):
        with self.assertRaises(TypeError): self.config(multi_bot_enabled=1)
        with self.assertRaises(TypeError): self.config(risk_per_trade_pct="0.5")
        with self.assertRaises(TypeError): self.config(maximum_leverage=float("inf"))
    def test_cross_fields(self):
        with self.assertRaises(ValueError): self.config(single_symbol_exposure_pct=D("30"))
        with self.assertRaises(ValueError): self.config(maximum_position_notional=D("101"))
    def test_input_and_direction(self):
        x=MoneyManagementDecisionInput("r1",datetime.now(timezone.utc),"XRPUSDTM",D("1"),D("10"),D("1"),D(".9"),D("1000"),D("1000"),True,side="BUY"); self.assertEqual(x.side,"BUY")
        with self.assertRaises(ValueError): MoneyManagementDecisionInput("r1",datetime.now(timezone.utc),"X",D("1"),D("1"),D("1"),D("1"),D("1"),D("1"),True)
    def test_output_invariants(self):
        with self.assertRaises(ValueError): MoneyManagementDecisionOutput("v1","d","r",datetime.now(timezone.utc),D("1"),D("0"),D("1"),False,RiskBlockReason.MAXIMUM_POSITION,RiskState.LOCKED)
        o=MoneyManagementDecisionOutput("v1","d","r",datetime.now(timezone.utc),D("0"),D("0"),D("0"),False,RiskBlockReason.MAXIMUM_POSITION,RiskState.LOCKED); self.assertEqual(o.to_dict()["risk_block_reason"],"MAXIMUM_POSITION")
    def test_runtime_timestamp(self):
        s=MoneyManagementRuntimeState("money-management-runtime-state/v1",MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,D("1000"),D("1000"),D("0"),RiskState.NORMAL,datetime.now(timezone.utc)); self.assertTrue(s.to_dict()["updated_at"].endswith("Z"))
        with self.assertRaises(TypeError): MoneyManagementRuntimeState("v1",MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,D("1"),D("1"),D("0"),RiskState.NORMAL,datetime.now())
    def test_validation_error(self):
        with self.assertRaises(ValidationError): validate_model(MoneyManagementConfig,{"mode":"PAPER"})
if __name__=="__main__": unittest.main()
