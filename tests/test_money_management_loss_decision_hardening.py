import unittest
from backend.money_management.loss_decision import evaluate_loss_decision
from tests.test_money_management_loss_decision import inp
from backend.money_management.loss_models import LossReason
from backend.money_management.enums import RiskState
class HardeningTests(unittest.TestCase):
    def test_block_wins_over_multiple_warnings(self):
        out=evaluate_loss_decision(inp(d="-15",w="-20",m="-30"))
        self.assertEqual(out.primary_reason,LossReason.DAILY_LOSS_BLOCK)
        self.assertEqual(out.risk_state,RiskState.LOCKED)
        self.assertEqual(out.action.value,"BLOCK")
if __name__=="__main__": unittest.main()
