import unittest
from backend.money_management.loss_decision import evaluate_loss_decision
from backend.money_management.loss_reason_models import *
from tests.test_money_management_loss_decision import inp
class ReasonContractTests(unittest.TestCase):
    def test_normal(self):
        c=build_reason_contract(evaluate_loss_decision(inp()))
        self.assertEqual(c.recommended_action,RecommendedAction.CONTINUE); self.assertFalse(c.warning_reasons); self.assertFalse(c.block_reasons)
    def test_caution_and_defensive(self):
        c=build_reason_contract(evaluate_loss_decision(inp(d="-10")))
        self.assertEqual(c.decision_state.value,"CAUTION"); self.assertEqual(c.recommended_action,RecommendedAction.CONTINUE); self.assertEqual(len(c.warning_reasons),1)
        c=build_reason_contract(evaluate_loss_decision(inp(d="-10",w="-20")))
        self.assertEqual(c.recommended_action,RecommendedAction.HOLD_NEW_ENTRIES); self.assertTrue(c.hold_reasons)
    def test_locked_is_block_not_hold(self):
        c=build_reason_contract(evaluate_loss_decision(inp(d="-15")))
        self.assertEqual(c.recommended_action,RecommendedAction.BLOCK_EXECUTION); self.assertTrue(c.block_reasons); self.assertFalse(c.hold_reasons)
    def test_roundtrip_determinism(self):
        a=build_reason_contract(evaluate_loss_decision(inp(d="-10"))); b=build_reason_contract(evaluate_loss_decision(inp(d="-10")))
        self.assertEqual(a.to_dict(),b.to_dict()); self.assertEqual(a.to_dict()["schema_version"],"money-management-loss-reason/v1")
if __name__=="__main__": unittest.main()
