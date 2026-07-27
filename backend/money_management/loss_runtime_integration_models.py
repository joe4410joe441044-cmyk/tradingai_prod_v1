"""Pure MM-4A runtime integration contracts."""
from dataclasses import dataclass,fields
from datetime import datetime,timezone
from enum import Enum
from typing import Optional,Tuple
from .enums import RiskState
from .loss_persistence_models import PersistedLossState
from .loss_persistence_adapter import LossPersistenceLoadResult,LoadStatus
from .loss_reason_models import RecommendedAction
class RuntimeLifecycle(str,Enum): UNINITIALIZED="UNINITIALIZED"; LOADING="LOADING"; RECONCILING="RECONCILING"; READY="READY"; RESTRICTED="RESTRICTED"; RECOVERY_REQUIRED="RECOVERY_REQUIRED"; FAILED="FAILED"; STOPPED="STOPPED"
class StartupMode(str,Enum): STARTUP="STARTUP"; RESTART="RESTART"; MANUAL="MANUAL"
class RecoveryStatus(str,Enum): NOT_REQUIRED="NOT_REQUIRED"; REQUIRED="REQUIRED"; COMPLETED="COMPLETED"; UNKNOWN="UNKNOWN"
class StateSource(str,Enum): PERSISTED_STATE="PERSISTED_STATE"; INITIAL_STATE="INITIAL_STATE"; CURRENT_RUNTIME_STATE="CURRENT_RUNTIME_STATE"; RESTRICTIVE_MERGE="RESTRICTIVE_MERGE"; NONE="NONE"
class LoadClassification(str,Enum): LOADED="LOADED"; NOT_FOUND="NOT_FOUND"; INVALID="INVALID"; CORRUPTED="CORRUPTED"; UNSAFE_PATH="UNSAFE_PATH"; IO_FAILURE="IO_FAILURE"; TEMP_FILE_EXISTS="TEMP_FILE_EXISTS"; DIGEST_MISMATCH="DIGEST_MISMATCH"; VERSION_UNSUPPORTED="VERSION_UNSUPPORTED"; UNKNOWN_FAILURE="UNKNOWN_FAILURE"
class ReconciliationStatus(str,Enum): MATCHED="MATCHED"; PERSISTED_MORE_RESTRICTIVE="PERSISTED_MORE_RESTRICTIVE"; RUNTIME_MORE_RESTRICTIVE="RUNTIME_MORE_RESTRICTIVE"; CONFLICT="CONFLICT"; INCOMPARABLE="INCOMPARABLE"; MISSING_STATE="MISSING_STATE"; INVALID_STATE="INVALID_STATE"
class GovernanceProjection(str,Enum): CONTINUE="CONTINUE"; HOLD_NEW_ENTRIES="HOLD_NEW_ENTRIES"; BLOCK_EXECUTION="BLOCK_EXECUTION"; RECOVERY_REQUIRED="RECOVERY_REQUIRED"
class RuntimeDecisionStatus(str,Enum): READY="READY"; RESTRICTED="RESTRICTED"; RECOVERY_REQUIRED="RECOVERY_REQUIRED"; FAILED="FAILED"
class SaveTrigger(str,Enum): INITIAL_STATE_CREATED="INITIAL_STATE_CREATED"; STATE_TRANSITION="STATE_TRANSITION"; REASON_CHANGED="REASON_CHANGED"; METRIC_CHANGED="METRIC_CHANGED"; PERIOD_ROLLOVER="PERIOD_ROLLOVER"; LOCKED="LOCKED"; RECOVERY_COMPLETED="RECOVERY_COMPLETED"; RUNTIME_SHUTDOWN="RUNTIME_SHUTDOWN"; MANUAL_CHECKPOINT="MANUAL_CHECKPOINT"; NONE="NONE"
class RecoveryReason(str,Enum): PERSISTENCE_CORRUPTED="PERSISTENCE_CORRUPTED"; DIGEST_MISMATCH="DIGEST_MISMATCH"; TEMPORARY_FILE_EXISTS="TEMPORARY_FILE_EXISTS"; UNSUPPORTED_VERSION="UNSUPPORTED_VERSION"; STATE_CONFLICT="STATE_CONFLICT"; STATE_UNAVAILABLE="STATE_UNAVAILABLE"; UNSAFE_STORAGE="UNSAFE_STORAGE"; IO_FAILURE="IO_FAILURE"; MANUAL_REVIEW_REQUIRED="MANUAL_REVIEW_REQUIRED"
def _dt(v):
 if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None: raise TypeError("timezone-aware datetime required")
 return v.astimezone(timezone.utc)
def _ser(v):
 if isinstance(v,Enum): return v.value
 if isinstance(v,datetime): return v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
 if isinstance(v,tuple): return [_ser(x) for x in v]
 if hasattr(v,"to_dict"): return v.to_dict()
 return v
@dataclass(frozen=True)
class LossLimitRuntimeIntegrationInput:
 persistence_load_result: LossPersistenceLoadResult
 configured_initial_state: Optional[PersistedLossState]
 current_runtime_state: Optional[PersistedLossState]
 runtime_lifecycle: RuntimeLifecycle
 startup_mode: StartupMode
 recovery_status: RecoveryStatus
 received_at: datetime
 def __post_init__(self):
  if not isinstance(self.persistence_load_result,LossPersistenceLoadResult): raise TypeError("persistence_load_result required")
  for n in ("configured_initial_state","current_runtime_state"):
   if getattr(self,n) is not None and not isinstance(getattr(self,n),PersistedLossState): raise TypeError(n+" invalid")
  object.__setattr__(self,"runtime_lifecycle",RuntimeLifecycle(self.runtime_lifecycle)); object.__setattr__(self,"startup_mode",StartupMode(self.startup_mode)); object.__setattr__(self,"recovery_status",RecoveryStatus(self.recovery_status)); object.__setattr__(self,"received_at",_dt(self.received_at))
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
@dataclass(frozen=True)
class LossLimitReconciliationResult:
 status: ReconciliationStatus
 selected_state: Optional[PersistedLossState]
 state_source: StateSource
 save_required: bool
 recovery_required: bool
 reason_codes: Tuple[str,...]=()
 def __post_init__(self):
  object.__setattr__(self,"status",ReconciliationStatus(self.status)); object.__setattr__(self,"state_source",StateSource(self.state_source))
  if self.selected_state is not None and not isinstance(self.selected_state,PersistedLossState): raise TypeError("selected_state invalid")
  if type(self.save_required) is not bool or type(self.recovery_required) is not bool: raise TypeError("boolean required")
  object.__setattr__(self,"reason_codes",tuple(str(x) for x in self.reason_codes))
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
@dataclass(frozen=True)
class LossLimitRecoveryRequirement:
 required: bool
 reason_codes: Tuple[RecoveryReason,...]
 new_entry_allowed: bool
 automatic_overwrite_allowed: bool
 manual_review_required: bool
 safe_message: str
 def __post_init__(self):
  for n in ("required","new_entry_allowed","automatic_overwrite_allowed","manual_review_required"):
   if type(getattr(self,n)) is not bool: raise TypeError("boolean required")
  vals=tuple(RecoveryReason(x) for x in self.reason_codes)
  if len(vals)!=len(set(vals)): raise ValueError("duplicate recovery reason")
  object.__setattr__(self,"reason_codes",vals)
  if not self.safe_message: raise ValueError("safe_message required")
  if self.required and (self.new_entry_allowed or self.automatic_overwrite_allowed or not self.manual_review_required): raise ValueError("recovery must be restrictive")
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
@dataclass(frozen=True)
class LossLimitRuntimeStartupDecision:
 decision_status: RuntimeDecisionStatus
 runtime_lifecycle: RuntimeLifecycle
 selected_state: Optional[PersistedLossState]
 state_source: StateSource
 runtime_start_allowed: bool
 new_entry_allowed: bool
 recovery_required: bool
 save_required: bool
 governance_projection: GovernanceProjection
 reason_codes: Tuple[str,...]
 diagnostic_codes: Tuple[str,...]
 safe_message: str
 def __post_init__(self):
  for n,c in (("decision_status",RuntimeDecisionStatus),("runtime_lifecycle",RuntimeLifecycle),("state_source",StateSource),("governance_projection",GovernanceProjection)): object.__setattr__(self,n,c(getattr(self,n)))
  if self.selected_state is not None and not isinstance(self.selected_state,PersistedLossState): raise TypeError("selected_state invalid")
  for n in ("runtime_start_allowed","new_entry_allowed","recovery_required","save_required"):
   if type(getattr(self,n)) is not bool: raise TypeError("boolean required")
  object.__setattr__(self,"reason_codes",tuple(str(x) for x in self.reason_codes)); object.__setattr__(self,"diagnostic_codes",tuple(str(x) for x in self.diagnostic_codes))
  if not self.safe_message: raise ValueError("safe_message required")
  if self.recovery_required and (self.new_entry_allowed or self.governance_projection is not GovernanceProjection.RECOVERY_REQUIRED): raise ValueError("recovery must be restrictive")
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
def classify_load_result(r):
 if not isinstance(r,LossPersistenceLoadResult): raise TypeError("load result required")
 return {LoadStatus.VALID:LoadClassification.LOADED,LoadStatus.MISSING:LoadClassification.NOT_FOUND,LoadStatus.CORRUPT:LoadClassification.CORRUPTED,LoadStatus.UNSAFE_PATH:LoadClassification.UNSAFE_PATH,LoadStatus.UNSAFE_FILE:LoadClassification.INVALID,LoadStatus.TOO_LARGE:LoadClassification.INVALID,LoadStatus.IO_ERROR:LoadClassification.IO_FAILURE}.get(r.status,LoadClassification.UNKNOWN_FAILURE)
def _rank(s): return {RiskState.NORMAL:0,RiskState.CAUTION:1,RiskState.DEFENSIVE:2,RiskState.LOCKED:3}[s.last_decision.decision_state]
def reconcile_loss_limit_state(persisted_state,runtime_state):
 if persisted_state is None and runtime_state is None: return LossLimitReconciliationResult(ReconciliationStatus.MISSING_STATE,None,StateSource.NONE,False,True,("STATE_UNAVAILABLE",))
 if persisted_state is None: return LossLimitReconciliationResult(ReconciliationStatus.MISSING_STATE,runtime_state,StateSource.CURRENT_RUNTIME_STATE,False,False)
 if runtime_state is None: return LossLimitReconciliationResult(ReconciliationStatus.MATCHED,persisted_state,StateSource.PERSISTED_STATE,False,False)
 if persisted_state.to_dict()==runtime_state.to_dict(): return LossLimitReconciliationResult(ReconciliationStatus.MATCHED,runtime_state,StateSource.CURRENT_RUNTIME_STATE,False,False)
 p,r=_rank(persisted_state),_rank(runtime_state)
 if p>r: return LossLimitReconciliationResult(ReconciliationStatus.PERSISTED_MORE_RESTRICTIVE,persisted_state,StateSource.PERSISTED_STATE,False,False,("PERSISTED_MORE_RESTRICTIVE",))
 if r>p: return LossLimitReconciliationResult(ReconciliationStatus.RUNTIME_MORE_RESTRICTIVE,runtime_state,StateSource.CURRENT_RUNTIME_STATE,True,False,("RUNTIME_MORE_RESTRICTIVE",))
 return LossLimitReconciliationResult(ReconciliationStatus.CONFLICT,None,StateSource.NONE,False,True,("STATE_CONFLICT",))
def _projection(s):
 if s is None: return GovernanceProjection.RECOVERY_REQUIRED
 a=s.last_decision.recommended_action
 if a is RecommendedAction.BLOCK_EXECUTION: return GovernanceProjection.BLOCK_EXECUTION
 if a is RecommendedAction.HOLD_NEW_ENTRIES: return GovernanceProjection.HOLD_NEW_ENTRIES
 return GovernanceProjection.CONTINUE
def build_loss_limit_runtime_startup_decision(inp):
 if not isinstance(inp,LossLimitRuntimeIntegrationInput): raise TypeError("integration input required")
 c=classify_load_result(inp.persistence_load_result); persisted=inp.persistence_load_result.state if c is LoadClassification.LOADED else None
 if c is LoadClassification.NOT_FOUND:
  if inp.configured_initial_state is None: return LossLimitRuntimeStartupDecision(RuntimeDecisionStatus.RECOVERY_REQUIRED,RuntimeLifecycle.RECOVERY_REQUIRED,None,StateSource.NONE,False,False,True,False,GovernanceProjection.RECOVERY_REQUIRED,("LOSS_RUNTIME_PERSISTENCE_NOT_FOUND",),("INITIAL_STATE_MISSING",),"initial state unavailable")
  s=inp.configured_initial_state; g=_projection(s); return LossLimitRuntimeStartupDecision(RuntimeDecisionStatus.READY,RuntimeLifecycle.READY,s,StateSource.INITIAL_STATE,True,g is GovernanceProjection.CONTINUE,False,True,g,("LOSS_RUNTIME_PERSISTENCE_NOT_FOUND",),("INITIAL_STATE_USED",),"initial state selected")
 if c is not LoadClassification.LOADED: return LossLimitRuntimeStartupDecision(RuntimeDecisionStatus.RECOVERY_REQUIRED,RuntimeLifecycle.RECOVERY_REQUIRED,None,StateSource.NONE,False,False,True,False,GovernanceProjection.RECOVERY_REQUIRED,("LOSS_RUNTIME_PERSISTENCE_INVALID",),(c.value,),"persistence unavailable; recovery required")
 rec=reconcile_loss_limit_state(persisted,inp.current_runtime_state)
 if rec.recovery_required: return LossLimitRuntimeStartupDecision(RuntimeDecisionStatus.RECOVERY_REQUIRED,RuntimeLifecycle.RECOVERY_REQUIRED,None,StateSource.NONE,False,False,True,False,GovernanceProjection.RECOVERY_REQUIRED,("LOSS_RUNTIME_STATE_CONFLICT",),rec.reason_codes,"state conflict; recovery required")
 s=rec.selected_state; g=_projection(s); restricted=g in (GovernanceProjection.HOLD_NEW_ENTRIES,GovernanceProjection.BLOCK_EXECUTION)
 return LossLimitRuntimeStartupDecision(RuntimeDecisionStatus.RESTRICTED if restricted else RuntimeDecisionStatus.READY,RuntimeLifecycle.RESTRICTED if restricted else RuntimeLifecycle.READY,s,rec.state_source,True,not restricted,False,rec.save_required,g,rec.reason_codes,(),"persisted state selected")
@dataclass(frozen=True)
class LossLimitSaveTriggerDecision:
 trigger: SaveTrigger
 save_required: bool
 reason_code: str
 def __post_init__(self): object.__setattr__(self,"trigger",SaveTrigger(self.trigger));
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
def build_save_trigger_decision(trigger,state_changed=False):
 t=SaveTrigger(trigger)
 if type(state_changed) is not bool: raise TypeError("state_changed must be bool")
 req=t is not SaveTrigger.NONE and (state_changed or t in (SaveTrigger.INITIAL_STATE_CREATED,SaveTrigger.PERIOD_ROLLOVER,SaveTrigger.LOCKED,SaveTrigger.RUNTIME_SHUTDOWN,SaveTrigger.MANUAL_CHECKPOINT))
 return LossLimitSaveTriggerDecision(t,req,t.value if req else "NONE")
