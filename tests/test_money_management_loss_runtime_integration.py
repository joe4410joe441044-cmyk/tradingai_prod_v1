import unittest
from datetime import datetime, timezone
from dataclasses import FrozenInstanceError
from backend.money_management.loss_runtime_integration import *
from backend.money_management.loss_persistence_adapter import LossPersistenceLoadResult, LoadStatus
from tests.test_money_management_loss_persistence_contract import state

NOW=datetime(2026,1,5,12,tzinfo=timezone.utc)
def inp(load, initial=None, current=None):
    return LossLimitRuntimeIntegrationInput(load,initial,current,RuntimeLifecycle.UNINITIALIZED,StartupMode.STARTUP,RecoveryStatus.NOT_REQUIRED,NOW)

class RuntimeIntegrationTests(unittest.TestCase):
    def test_loaded_state_is_selected_without_io(self):
        s=state(); d=build_loss_limit_runtime_startup_decision(inp(LossPersistenceLoadResult(LoadStatus.VALID,s)))
        self.assertEqual(d.state_source,StateSource.PERSISTED_STATE)
        self.assertTrue(d.runtime_start_allowed); self.assertTrue(d.new_entry_allowed)
        self.assertEqual(d.runtime_lifecycle,RuntimeLifecycle.READY)
        self.assertFalse(d.recovery_required)

    def test_not_found_uses_valid_initial_and_requires_save(self):
        s=state(); d=build_loss_limit_runtime_startup_decision(inp(LossPersistenceLoadResult(LoadStatus.MISSING,None,"MISSING","missing"),s))
        self.assertEqual(d.state_source,StateSource.INITIAL_STATE); self.assertTrue(d.save_required); self.assertFalse(d.recovery_required)

    def test_not_found_without_initial_is_recovery_required(self):
        d=build_loss_limit_runtime_startup_decision(inp(LossPersistenceLoadResult(LoadStatus.MISSING,None,"MISSING","missing")))
        self.assertEqual(d.runtime_lifecycle,RuntimeLifecycle.RECOVERY_REQUIRED); self.assertFalse(d.new_entry_allowed); self.assertEqual(d.governance_projection,GovernanceProjection.RECOVERY_REQUIRED)

    def test_corrupt_persistence_never_falls_back(self):
        d=build_loss_limit_runtime_startup_decision(inp(LossPersistenceLoadResult(LoadStatus.CORRUPT,None,"CORRUPT","bad"),state()))
        self.assertIsNone(d.selected_state); self.assertTrue(d.recovery_required); self.assertFalse(d.runtime_start_allowed); self.assertFalse(d.save_required)

    def test_reconciliation_match_and_conflict(self):
        s=state(); self.assertEqual(reconcile_loss_limit_state(s,s).status,ReconciliationStatus.MATCHED)
        conflict=state(account_scope="other")
        r=reconcile_loss_limit_state(s,conflict)
        self.assertEqual(r.status,ReconciliationStatus.CONFLICT); self.assertTrue(r.recovery_required)

    def test_input_and_decision_are_frozen_and_deterministic(self):
        s=state(); i=inp(LossPersistenceLoadResult(LoadStatus.VALID,s))
        a=build_loss_limit_runtime_startup_decision(i)
        b=build_loss_limit_runtime_startup_decision(i)
        self.assertEqual(a.to_dict(),b.to_dict())
        with self.assertRaises(FrozenInstanceError): i.startup_mode=StartupMode.RESTART

    def test_save_trigger_is_pure_and_typed(self):
        self.assertTrue(build_save_trigger_decision(SaveTrigger.STATE_TRANSITION,True).save_required)
        self.assertFalse(build_save_trigger_decision(SaveTrigger.NONE,True).save_required)
        with self.assertRaises(TypeError): build_save_trigger_decision(SaveTrigger.STATE_TRANSITION,1)

if __name__=="__main__": unittest.main()
