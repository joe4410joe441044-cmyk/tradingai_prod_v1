import unittest
from datetime import datetime, timezone
from backend.money_management.loss_runtime_startup_models import *
from backend.money_management.loss_runtime_startup_coordinator import LossLimitRuntimeStartupCoordinator
from backend.money_management.loss_runtime_store import LossLimitRuntimeStateStore
from backend.money_management.loss_persistence_adapter import LossPersistenceLoadResult, LoadStatus
from tests.test_money_management_loss_persistence_contract import state

NOW=datetime(2026,1,5,12,tzinfo=timezone.utc)
class Adapter:
    def __init__(self,result=None,error=False): self.result=result; self.error=error; self.calls=0
    def load(self):
        self.calls+=1
        if self.error: raise RuntimeError("/private/secret")
        return self.result
def request(initial=None):
    return LossLimitRuntimeStartupRequest(initial,StartupMode.STARTUP,RecoveryStatus.NOT_REQUIRED,NOW,NOW)
class CoordinatorTests(unittest.TestCase):
    def test_loaded_startup_calls_load_and_initialize_once(self):
        s=state(); a=Adapter(LossPersistenceLoadResult(LoadStatus.VALID,s)); c=LossLimitRuntimeStartupCoordinator(a,LossLimitRuntimeStateStore())
        r=c.start(request()); self.assertEqual(r.status,StartupCoordinationStatus.SUCCEEDED); self.assertTrue(r.normal_operation_ready); self.assertTrue(r.new_entry_allowed); self.assertEqual(a.calls,1)
    def test_not_found_initial_requires_save_but_no_save_call(self):
        a=Adapter(LossPersistenceLoadResult(LoadStatus.MISSING,None,"MISSING","missing")); c=LossLimitRuntimeStartupCoordinator(a,LossLimitRuntimeStateStore())
        r=c.start(request(state())); self.assertEqual(r.status,StartupCoordinationStatus.SUCCEEDED); self.assertTrue(r.save_required); self.assertIn(SaveTrigger.INITIAL_STATE_CREATED,r.save_triggers); self.assertEqual(a.calls,1)
    def test_corrupt_never_falls_back(self):
        a=Adapter(LossPersistenceLoadResult(LoadStatus.CORRUPT,None,"CORRUPT","bad")); c=LossLimitRuntimeStartupCoordinator(a,LossLimitRuntimeStateStore())
        r=c.start(request(state())); self.assertEqual(r.status,StartupCoordinationStatus.RECOVERY_REQUIRED); self.assertFalse(r.new_entry_allowed); self.assertFalse(r.normal_operation_ready); self.assertFalse(r.save_required); self.assertIsNotNone(r.snapshot)
    def test_adapter_exception_is_safe_failure(self):
        a=Adapter(error=True); c=LossLimitRuntimeStartupCoordinator(a,LossLimitRuntimeStateStore())
        r=c.start(request()); self.assertEqual(r.status,StartupCoordinationStatus.FAILED); self.assertEqual(r.failure.code,StartupFailureCode.LOSS_STARTUP_LOAD_FAILED); self.assertNotIn("private",r.failure.safe_message)
    def test_duplicate_startup_is_idempotent_without_second_load(self):
        s=state(); a=Adapter(LossPersistenceLoadResult(LoadStatus.VALID,s)); c=LossLimitRuntimeStartupCoordinator(a,LossLimitRuntimeStateStore())
        first=c.start(request()); second=c.start(request()); self.assertEqual(first.status,StartupCoordinationStatus.SUCCEEDED); self.assertEqual(second.status,StartupCoordinationStatus.IDEMPOTENT); self.assertEqual(a.calls,1); self.assertEqual(first.snapshot.to_dict(),second.snapshot.to_dict())
    def test_different_initial_conflicts(self):
        s=state(); a=Adapter(LossPersistenceLoadResult(LoadStatus.VALID,s)); c=LossLimitRuntimeStartupCoordinator(a,LossLimitRuntimeStateStore())
        c.start(request()); other=state(account_scope="other"); r=c.start(request(other)); self.assertEqual(r.status,StartupCoordinationStatus.FAILED); self.assertEqual(r.failure.code,StartupFailureCode.LOSS_STARTUP_ALREADY_INITIALIZED_CONFLICT)
if __name__=="__main__": unittest.main()
