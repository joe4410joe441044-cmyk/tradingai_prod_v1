"""MM-4C startup coordination contracts."""
from dataclasses import dataclass,fields
from datetime import datetime,timezone
from enum import Enum
from typing import Optional,Tuple
from .loss_persistence_adapter import LossPersistenceLoadResult,LoadStatus
from .loss_persistence_models import PersistedLossState
from .loss_runtime_integration_models import *
from .loss_runtime_store_models import StoreResultStatus,LossLimitRuntimeStoreResult,LossLimitRuntimeSnapshot
def _ser(v):
 if isinstance(v,Enum): return v.value
 if isinstance(v,datetime): return v.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
 if isinstance(v,tuple): return [_ser(x) for x in v]
 if hasattr(v,"to_dict"): return v.to_dict()
 return v
class StartupCoordinationStatus(str,Enum): SUCCEEDED="SUCCEEDED"; FAILED="FAILED"; IDEMPOTENT="IDEMPOTENT"; RECOVERY_REQUIRED="RECOVERY_REQUIRED"
class StartupFailureCode(str,Enum):
 LOSS_STARTUP_REQUEST_INVALID="LOSS_STARTUP_REQUEST_INVALID"; LOSS_STARTUP_LOAD_FAILED="LOSS_STARTUP_LOAD_FAILED"; LOSS_STARTUP_LOAD_RESULT_INVALID="LOSS_STARTUP_LOAD_RESULT_INVALID"; LOSS_STARTUP_DECISION_FAILED="LOSS_STARTUP_DECISION_FAILED"; LOSS_STARTUP_DECISION_INVALID="LOSS_STARTUP_DECISION_INVALID"; LOSS_STARTUP_STORE_INITIALIZATION_FAILED="LOSS_STARTUP_STORE_INITIALIZATION_FAILED"; LOSS_STARTUP_ALREADY_INITIALIZED_CONFLICT="LOSS_STARTUP_ALREADY_INITIALIZED_CONFLICT"; LOSS_STARTUP_INTERNAL_FAILURE="LOSS_STARTUP_INTERNAL_FAILURE"
@dataclass(frozen=True)
class LossLimitRuntimeStartupRequest:
 initial_state: Optional[PersistedLossState]
 startup_mode: StartupMode
 recovery_status: RecoveryStatus
 occurred_at: datetime
 received_at: datetime
 def __post_init__(self):
  if self.initial_state is not None and not isinstance(self.initial_state,PersistedLossState): raise TypeError("initial_state invalid")
  object.__setattr__(self,"startup_mode",StartupMode(self.startup_mode)); object.__setattr__(self,"recovery_status",RecoveryStatus(self.recovery_status))
  for n in ("occurred_at","received_at"):
   v=getattr(self,n)
   if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None: raise TypeError(n+" must be timezone-aware")
   object.__setattr__(self,n,v.astimezone(timezone.utc))
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
@dataclass(frozen=True)
class LossLimitStartupFailure:
 code: StartupFailureCode
 safe_message: str
 def __post_init__(self):
  object.__setattr__(self,"code",StartupFailureCode(self.code))
  if not self.safe_message: raise ValueError("safe message required")
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
@dataclass(frozen=True)
class LossLimitRuntimeStartupCoordinationResult:
 status: StartupCoordinationStatus
 snapshot: Optional[LossLimitRuntimeSnapshot]
 load_classification: Optional[LoadClassification]
 startup_decision: Optional[LossLimitRuntimeStartupDecision]
 store_result_status: Optional[StoreResultStatus]
 normal_operation_ready: bool
 new_entry_allowed: bool
 recovery_required: bool
 save_required: bool
 save_triggers: Tuple[SaveTrigger,...]
 failure: Optional[LossLimitStartupFailure]=None
 def __post_init__(self):
  object.__setattr__(self,"status",StartupCoordinationStatus(self.status))
  if self.snapshot is not None and not isinstance(self.snapshot,LossLimitRuntimeSnapshot): raise TypeError("snapshot invalid")
  if self.startup_decision is not None and not isinstance(self.startup_decision,LossLimitRuntimeStartupDecision): raise TypeError("decision invalid")
  if self.store_result_status is not None: object.__setattr__(self,"store_result_status",StoreResultStatus(self.store_result_status))
  if self.load_classification is not None: object.__setattr__(self,"load_classification",LoadClassification(self.load_classification))
  object.__setattr__(self,"save_triggers",tuple(SaveTrigger(x) for x in self.save_triggers))
  for n in ("normal_operation_ready","new_entry_allowed","recovery_required","save_required"):
   if type(getattr(self,n)) is not bool: raise TypeError("boolean required")
  if self.status is StartupCoordinationStatus.FAILED and self.failure is None: raise ValueError("failure required")
  if self.status is not StartupCoordinationStatus.FAILED and self.failure is not None: raise ValueError("success cannot have failure")
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
