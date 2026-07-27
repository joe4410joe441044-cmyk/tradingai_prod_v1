"""MM-4B immutable runtime store contracts."""
from dataclasses import dataclass,fields
from datetime import datetime,timezone
from enum import Enum
from typing import Optional,Tuple
from .loss_persistence_models import PersistedLossState
from .loss_runtime_integration_models import (RuntimeLifecycle,StateSource,GovernanceProjection,SaveTrigger,LossLimitRecoveryRequirement,LossLimitRuntimeStartupDecision)
class StoreResultStatus(str,Enum): SUCCEEDED="SUCCEEDED"; FAILED="FAILED"; IDEMPOTENT="IDEMPOTENT"
class StoreFailureCode(str,Enum):
 LOSS_RUNTIME_STORE_INPUT_INVALID="LOSS_RUNTIME_STORE_INPUT_INVALID"; LOSS_RUNTIME_STORE_NOT_INITIALIZED="LOSS_RUNTIME_STORE_NOT_INITIALIZED"; LOSS_RUNTIME_STORE_ALREADY_INITIALIZED="LOSS_RUNTIME_STORE_ALREADY_INITIALIZED"; LOSS_RUNTIME_STORE_STOPPED="LOSS_RUNTIME_STORE_STOPPED"; LOSS_RUNTIME_STORE_REVISION_CONFLICT="LOSS_RUNTIME_STORE_REVISION_CONFLICT"; LOSS_RUNTIME_STORE_STALE_SEQUENCE="LOSS_RUNTIME_STORE_STALE_SEQUENCE"; LOSS_RUNTIME_STORE_SEQUENCE_GAP="LOSS_RUNTIME_STORE_SEQUENCE_GAP"; LOSS_RUNTIME_STORE_EVENT_CONFLICT="LOSS_RUNTIME_STORE_EVENT_CONFLICT"; LOSS_RUNTIME_STORE_INVALID_TRANSITION="LOSS_RUNTIME_STORE_INVALID_TRANSITION"; LOSS_RUNTIME_STORE_STATE_CONFLICT="LOSS_RUNTIME_STORE_STATE_CONFLICT"; LOSS_RUNTIME_STORE_RECOVERY_REQUIRED="LOSS_RUNTIME_STORE_RECOVERY_REQUIRED"; LOSS_RUNTIME_STORE_INTERNAL_FAILURE="LOSS_RUNTIME_STORE_INTERNAL_FAILURE"
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
class LossLimitRuntimeSnapshot:
 lifecycle: RuntimeLifecycle
 state: Optional[PersistedLossState]
 state_source: StateSource
 governance_projection: GovernanceProjection
 recovery_requirement: LossLimitRecoveryRequirement
 save_triggers: Tuple[SaveTrigger,...]
 revision: int
 sequence: int
 initialized_at: datetime
 updated_at: datetime
 last_transition: str
 def __post_init__(self):
  for n,c in (("lifecycle",RuntimeLifecycle),("state_source",StateSource),("governance_projection",GovernanceProjection)): object.__setattr__(self,n,c(getattr(self,n)))
  if self.state is not None and not isinstance(self.state,PersistedLossState): raise TypeError("state invalid")
  vals=tuple(SaveTrigger(x) for x in self.save_triggers)
  if len(vals)!=len(set(vals)): raise ValueError("duplicate save trigger")
  object.__setattr__(self,"save_triggers",vals)
  if type(self.revision) is not int or self.revision<1 or type(self.sequence) is not int or self.sequence<1: raise ValueError("revision and sequence must be positive integers")
  object.__setattr__(self,"initialized_at",_dt(self.initialized_at)); object.__setattr__(self,"updated_at",_dt(self.updated_at))
  if self.updated_at<self.initialized_at: raise ValueError("updated_at before initialized_at")
  if not isinstance(self.last_transition,str) or not self.last_transition: raise ValueError("transition required")
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
@dataclass(frozen=True)
class LossLimitRuntimeUpdate:
 next_state: Optional[PersistedLossState]
 governance_projection: GovernanceProjection
 recovery_requirement: LossLimitRecoveryRequirement
 save_triggers: Tuple[SaveTrigger,...]
 expected_revision: int
 event_sequence: int
 occurred_at: datetime
 transition_reason: str
 def __post_init__(self):
  if self.next_state is not None and not isinstance(self.next_state,PersistedLossState): raise TypeError("next_state invalid")
  object.__setattr__(self,"governance_projection",GovernanceProjection(self.governance_projection))
  vals=tuple(SaveTrigger(x) for x in self.save_triggers)
  if len(vals)!=len(set(vals)): raise ValueError("duplicate save trigger")
  object.__setattr__(self,"save_triggers",vals)
  if type(self.expected_revision) is not int or self.expected_revision<1 or type(self.event_sequence) is not int or self.event_sequence<1: raise ValueError("revision and sequence must be positive integers")
  object.__setattr__(self,"occurred_at",_dt(self.occurred_at))
  if not isinstance(self.transition_reason,str) or not self.transition_reason: raise ValueError("transition reason required")
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
@dataclass(frozen=True)
class LossLimitRuntimeStoreFailure:
 code: StoreFailureCode
 safe_message: str
 def __post_init__(self):
  object.__setattr__(self,"code",StoreFailureCode(self.code))
  if not self.safe_message: raise ValueError("safe message required")
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
@dataclass(frozen=True)
class LossLimitRuntimeStoreResult:
 status: StoreResultStatus
 snapshot: Optional[LossLimitRuntimeSnapshot]
 failure: Optional[LossLimitRuntimeStoreFailure]
 state_changed: bool
 save_required: bool
 def __post_init__(self):
  object.__setattr__(self,"status",StoreResultStatus(self.status))
  if self.snapshot is not None and not isinstance(self.snapshot,LossLimitRuntimeSnapshot): raise TypeError("snapshot invalid")
  if type(self.state_changed) is not bool or type(self.save_required) is not bool: raise TypeError("boolean required")
  if self.status is StoreResultStatus.FAILED and self.failure is None: raise ValueError("failure required")
  if self.status is not StoreResultStatus.FAILED and self.failure is not None: raise ValueError("success cannot have failure")
 def to_dict(self): return {f.name:_ser(getattr(self,f.name)) for f in fields(self)}
