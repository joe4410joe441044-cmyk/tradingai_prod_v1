"""MM-4B in-memory runtime state store; no persistence or external I/O."""
from threading import RLock
from .enums import RiskState
from .loss_reason_models import RecommendedAction
from .loss_runtime_integration_models import RuntimeLifecycle,StateSource,GovernanceProjection,SaveTrigger,RecoveryReason,LossLimitRecoveryRequirement,LossLimitRuntimeStartupDecision
from .loss_runtime_store_models import *
def _dt(v):
 if not isinstance(v,__import__("datetime").datetime) or v.tzinfo is None or v.utcoffset() is None: raise TypeError("timezone-aware datetime required")
 return v.astimezone(__import__("datetime").timezone.utc)
def _projection(state):
 if state is None: return GovernanceProjection.RECOVERY_REQUIRED
 a=state.last_decision.recommended_action
 if a is RecommendedAction.BLOCK_EXECUTION: return GovernanceProjection.BLOCK_EXECUTION
 if a is RecommendedAction.HOLD_NEW_ENTRIES: return GovernanceProjection.HOLD_NEW_ENTRIES
 return GovernanceProjection.CONTINUE
def _rank(state): return {RiskState.NORMAL:0,RiskState.CAUTION:1,RiskState.DEFENSIVE:2,RiskState.LOCKED:3}[state.last_decision.decision_state]
_ALLOWED={(RuntimeLifecycle.UNINITIALIZED,RuntimeLifecycle.READY),(RuntimeLifecycle.UNINITIALIZED,RuntimeLifecycle.RESTRICTED),(RuntimeLifecycle.UNINITIALIZED,RuntimeLifecycle.RECOVERY_REQUIRED),(RuntimeLifecycle.READY,RuntimeLifecycle.READY),(RuntimeLifecycle.READY,RuntimeLifecycle.RESTRICTED),(RuntimeLifecycle.READY,RuntimeLifecycle.RECOVERY_REQUIRED),(RuntimeLifecycle.READY,RuntimeLifecycle.STOPPED),(RuntimeLifecycle.RESTRICTED,RuntimeLifecycle.RESTRICTED),(RuntimeLifecycle.RESTRICTED,RuntimeLifecycle.RECOVERY_REQUIRED),(RuntimeLifecycle.RESTRICTED,RuntimeLifecycle.STOPPED),(RuntimeLifecycle.RECOVERY_REQUIRED,RuntimeLifecycle.RECOVERY_REQUIRED),(RuntimeLifecycle.RECOVERY_REQUIRED,RuntimeLifecycle.STOPPED),(RuntimeLifecycle.STOPPED,RuntimeLifecycle.STOPPED)}
def _failure(code,msg): return LossLimitRuntimeStoreResult(StoreResultStatus.FAILED,None,LossLimitRuntimeStoreFailure(code,msg),False,False)
class LossLimitRuntimeStateStore:
 def __init__(self):
  self._lock=RLock(); self._snapshot=None; self._last_event=None
 def get_snapshot(self):
  with self._lock:
   if self._snapshot is None: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_NOT_INITIALIZED,"store not initialized")
   return LossLimitRuntimeStoreResult(StoreResultStatus.SUCCEEDED,self._snapshot,None,False,False)
 def _recovery(self,required):
  return required
 def initialize(self,startup_decision,occurred_at,initial_revision=1,initial_sequence=1):
  with self._lock:
   try:
    if type(initial_revision) is not int or initial_revision<1 or type(initial_sequence) is not int or initial_sequence<1: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"invalid initial checkpoint metadata")
    if not isinstance(startup_decision,LossLimitRuntimeStartupDecision): return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"invalid startup decision")
    if self._snapshot is not None:
     same=(self._snapshot.lifecycle is startup_decision.runtime_lifecycle and self._snapshot.state_source is startup_decision.state_source and ((self._snapshot.state is None and startup_decision.selected_state is None) or (self._snapshot.state is not None and startup_decision.selected_state is not None and self._snapshot.state.to_dict()==startup_decision.selected_state.to_dict())))
     if same: return LossLimitRuntimeStoreResult(StoreResultStatus.IDEMPOTENT,self._snapshot,None,False,False)
     return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_ALREADY_INITIALIZED,"store already initialized")
    if startup_decision.runtime_lifecycle not in (RuntimeLifecycle.READY,RuntimeLifecycle.RESTRICTED,RuntimeLifecycle.RECOVERY_REQUIRED): return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"invalid startup lifecycle")
    if startup_decision.recovery_required and startup_decision.runtime_lifecycle is not RuntimeLifecycle.RECOVERY_REQUIRED: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_STATE_CONFLICT,"recovery lifecycle mismatch")
    if not startup_decision.recovery_required and startup_decision.selected_state is None: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"selected state required")
    if startup_decision.selected_state is not None and _projection(startup_decision.selected_state) is not startup_decision.governance_projection: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_STATE_CONFLICT,"projection mismatch")
    expected_lifecycle = RuntimeLifecycle.RESTRICTED if startup_decision.governance_projection in (GovernanceProjection.HOLD_NEW_ENTRIES,GovernanceProjection.BLOCK_EXECUTION) else RuntimeLifecycle.READY
    if not startup_decision.recovery_required and startup_decision.runtime_lifecycle is not expected_lifecycle: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_STATE_CONFLICT,"lifecycle mismatch")
    if startup_decision.recovery_required and (startup_decision.runtime_start_allowed or startup_decision.new_entry_allowed): return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_RECOVERY_REQUIRED,"recovery policy mismatch")
    at=_dt(occurred_at); rr=LossLimitRecoveryRequirement(startup_decision.recovery_required,(RecoveryReason.STATE_UNAVAILABLE,) if startup_decision.recovery_required else (),False,False,startup_decision.recovery_required,"recovery required" if startup_decision.recovery_required else "no recovery required")
    self._snapshot=LossLimitRuntimeSnapshot(startup_decision.runtime_lifecycle,startup_decision.selected_state,startup_decision.state_source,startup_decision.governance_projection,rr,(SaveTrigger.INITIAL_STATE_CREATED,) if startup_decision.save_required else (),initial_revision,initial_sequence,at,at,"INITIALIZE")
    return LossLimitRuntimeStoreResult(StoreResultStatus.SUCCEEDED,self._snapshot,None,True,startup_decision.save_required)
   except (TypeError,ValueError): return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"invalid initialization")
 def _event_signature(self,u):
  return (u.next_state.to_dict() if u.next_state else None,u.governance_projection.value,u.recovery_requirement.to_dict(),tuple(x.value for x in u.save_triggers),u.transition_reason)
 def apply_update(self,update):
  with self._lock:
   try:
    if not isinstance(update,LossLimitRuntimeUpdate): return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"invalid update")
    if self._snapshot is None: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_NOT_INITIALIZED,"store not initialized")
    cur=self._snapshot
    if cur.lifecycle is RuntimeLifecycle.STOPPED: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_STOPPED,"store stopped")
    if update.expected_revision!=cur.revision: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_REVISION_CONFLICT,"revision conflict")
    sig=self._event_signature(update)
    if update.event_sequence==cur.sequence and sig==self._last_event: return LossLimitRuntimeStoreResult(StoreResultStatus.IDEMPOTENT,cur,None,False,False)
    if update.event_sequence<cur.sequence: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_STALE_SEQUENCE,"stale sequence")
    if update.event_sequence>cur.sequence+1: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_SEQUENCE_GAP,"sequence gap")
    if update.event_sequence==cur.sequence: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_EVENT_CONFLICT,"event conflict")
    if cur.lifecycle is RuntimeLifecycle.RECOVERY_REQUIRED and not update.recovery_requirement.required: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_RECOVERY_REQUIRED,"recovery required")
    next_l=RuntimeLifecycle.RECOVERY_REQUIRED if update.recovery_requirement.required else (RuntimeLifecycle.RESTRICTED if update.governance_projection in (GovernanceProjection.HOLD_NEW_ENTRIES,GovernanceProjection.BLOCK_EXECUTION) else RuntimeLifecycle.READY)
    if (cur.lifecycle,next_l) not in _ALLOWED: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INVALID_TRANSITION,"invalid lifecycle transition")
    if update.next_state is not None and _projection(update.next_state) is not update.governance_projection: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_STATE_CONFLICT,"projection mismatch")
    if cur.state is not None and update.next_state is not None and _rank(update.next_state)<_rank(cur.state): return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INVALID_TRANSITION,"automatic relaxation forbidden")
    at=_dt(update.occurred_at)
    if at<cur.updated_at: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"event timestamp is stale")
    self._snapshot=LossLimitRuntimeSnapshot(next_l,update.next_state,StateSource.CURRENT_RUNTIME_STATE,update.governance_projection,update.recovery_requirement,update.save_triggers,cur.revision+1,update.event_sequence,cur.initialized_at,at,update.transition_reason)
    self._last_event=sig
    return LossLimitRuntimeStoreResult(StoreResultStatus.SUCCEEDED,self._snapshot, None, True,bool(update.save_triggers))
   except (TypeError,ValueError): return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"invalid update")
 def stop(self,occurred_at,expected_revision):
  with self._lock:
   if self._snapshot is None: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_NOT_INITIALIZED,"store not initialized")
   if type(expected_revision) is not int: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"invalid revision")
   if self._snapshot.lifecycle is RuntimeLifecycle.STOPPED: return LossLimitRuntimeStoreResult(StoreResultStatus.IDEMPOTENT,self._snapshot,None,False,False)
   if expected_revision!=self._snapshot.revision: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_REVISION_CONFLICT,"revision conflict")
   try: at=_dt(occurred_at)
   except TypeError: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"invalid timestamp")
   if at<self._snapshot.updated_at: return _failure(StoreFailureCode.LOSS_RUNTIME_STORE_INPUT_INVALID,"event timestamp is stale")
   cur=self._snapshot
   self._snapshot=LossLimitRuntimeSnapshot(RuntimeLifecycle.STOPPED,cur.state,cur.state_source,cur.governance_projection,cur.recovery_requirement,(SaveTrigger.RUNTIME_SHUTDOWN,),cur.revision+1,cur.sequence+1,cur.initialized_at,at,"STOP")
   return LossLimitRuntimeStoreResult(StoreResultStatus.SUCCEEDED,self._snapshot,None,True,True)
