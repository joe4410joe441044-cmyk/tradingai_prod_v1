import unittest
from datetime import datetime, timezone, timedelta
from dataclasses import FrozenInstanceError
from backend.money_management.loss_runtime_store import LossLimitRuntimeStateStore
from backend.money_management.loss_runtime_store_models import *
from backend.money_management.loss_runtime_integration_models import *
from backend.money_management.loss_persistence_adapter import LossPersistenceLoadResult, LoadStatus
from tests.test_money_management_loss_persistence_contract import state

NOW=datetime(2026,1,5,12,tzinfo=timezone.utc)
def decision(s=None):
    s=s or state()
    return LossLimitRuntimeStartupDecision(RuntimeDecisionStatus.READY,RuntimeLifecycle.READY,s,StateSource.PERSISTED_STATE,True,True,False,False,GovernanceProjection.CONTINUE,(),(),"ok")
def recovery():
    return LossLimitRecoveryRequirement(False,(),False,False,False,"none")
def update(rev=1,seq=2,at=NOW+timedelta(seconds=1),next_state=None):
    return LossLimitRuntimeUpdate(next_state or state(),GovernanceProjection.CONTINUE,recovery(),(SaveTrigger.STATE_TRANSITION,),rev,seq,at,"EVALUATION")

class RuntimeStoreTests(unittest.TestCase):
    def test_initialize_snapshot_and_idempotency(self):
        st=LossLimitRuntimeStateStore()
        self.assertEqual(st.get_snapshot().failure.code,StoreFailureCode.LOSS_RUNTIME_STORE_NOT_INITIALIZED)
        r=st.initialize(decision(),NOW); self.assertEqual(r.status,StoreResultStatus.SUCCEEDED)
        self.assertEqual(r.snapshot.revision,1); self.assertEqual(r.snapshot.sequence,1)
        same=st.initialize(decision(),NOW); self.assertEqual(same.status,StoreResultStatus.IDEMPOTENT)
        self.assertIsInstance(st.get_snapshot().snapshot,LossLimitRuntimeSnapshot)

    def test_update_cas_sequence_and_atomic_failure(self):
        st=LossLimitRuntimeStateStore(); st.initialize(decision(),NOW)
        ok=st.apply_update(update()); self.assertEqual(ok.status,StoreResultStatus.SUCCEEDED); self.assertEqual(ok.snapshot.revision,2)
        before=st.get_snapshot().snapshot
        bad=st.apply_update(update(rev=1,seq=3)); self.assertEqual(bad.failure.code,StoreFailureCode.LOSS_RUNTIME_STORE_REVISION_CONFLICT)
        self.assertEqual(st.get_snapshot().snapshot.to_dict(),before.to_dict())
        self.assertEqual(st.apply_update(update(rev=2,seq=2)).status,StoreResultStatus.IDEMPOTENT)
        self.assertEqual(st.apply_update(update(rev=2,seq=1)).failure.code,StoreFailureCode.LOSS_RUNTIME_STORE_STALE_SEQUENCE)
        self.assertEqual(st.apply_update(update(rev=2,seq=4)).failure.code,StoreFailureCode.LOSS_RUNTIME_STORE_SEQUENCE_GAP)

    def test_stop_and_post_stop_rejection(self):
        st=LossLimitRuntimeStateStore(); st.initialize(decision(),NOW)
        r=st.stop(NOW+timedelta(seconds=1),1); self.assertEqual(r.status,StoreResultStatus.SUCCEEDED)
        self.assertEqual(r.snapshot.lifecycle,RuntimeLifecycle.STOPPED)
        self.assertEqual(st.stop(NOW+timedelta(seconds=2),2).status,StoreResultStatus.IDEMPOTENT)
        self.assertEqual(st.apply_update(update(rev=2,seq=3)).failure.code,StoreFailureCode.LOSS_RUNTIME_STORE_STOPPED)

    def test_automatic_relaxation_rejected(self):
        st=LossLimitRuntimeStateStore(); st.initialize(decision(),NOW)
        relaxed=st.apply_update(update(next_state=state()))
        self.assertEqual(relaxed.status,StoreResultStatus.SUCCEEDED)
        with self.assertRaises(FrozenInstanceError):
            st.get_snapshot().snapshot.revision=9

    def test_invalid_input_and_serialization(self):
        st=LossLimitRuntimeStateStore()
        self.assertEqual(st.initialize(object(),NOW).failure.code,StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID)
        self.assertEqual(st.get_snapshot().to_dict(),st.get_snapshot().to_dict())

if __name__=="__main__": unittest.main()
