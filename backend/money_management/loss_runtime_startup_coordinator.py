"""MM-4C pure startup coordinator; adapter and store are injected."""
from .loss_runtime_startup_models import *
from .loss_runtime_integration_models import LossLimitRuntimeIntegrationInput,build_loss_limit_runtime_startup_decision,classify_load_result,RuntimeLifecycle,StateSource,LoadClassification,SaveTrigger
from .loss_runtime_store_models import StoreResultStatus
class LossLimitRuntimeStartupCoordinator:
 def __init__(self,persistence_adapter,runtime_store,initial_revision=1,initial_sequence=1):
  if persistence_adapter is None or runtime_store is None: raise TypeError("adapter and store required")
  if type(initial_revision) is not int or initial_revision<1 or type(initial_sequence) is not int or initial_sequence<1: raise ValueError("invalid initial checkpoint metadata")
  self._adapter=persistence_adapter; self._store=runtime_store; self._initial_revision=initial_revision; self._initial_sequence=initial_sequence
 def _fail(self,code,msg,load=None):
  return LossLimitRuntimeStartupCoordinationResult(StartupCoordinationStatus.FAILED,None,load,None,None,False,False,True,False,(),LossLimitStartupFailure(code,msg))
 def start(self,request):
  if not isinstance(request,LossLimitRuntimeStartupRequest): return self._fail(StartupFailureCode.LOSS_STARTUP_REQUEST_INVALID,"invalid startup request")
  try:
   existing=self._store.get_snapshot()
   if existing.status is StoreResultStatus.SUCCEEDED:
    snap=existing.snapshot
    if request.initial_state is None or (snap.state is not None and request.initial_state.to_dict()==snap.state.to_dict()):
     return LossLimitRuntimeStartupCoordinationResult(StartupCoordinationStatus.IDEMPOTENT,snap,LoadClassification.LOADED,None,StoreResultStatus.IDEMPOTENT, snap.lifecycle in (RuntimeLifecycle.READY,RuntimeLifecycle.RESTRICTED),snap.governance_projection.value=="CONTINUE",snap.lifecycle is RuntimeLifecycle.RECOVERY_REQUIRED,False,snap.save_triggers)
    return self._fail(StartupFailureCode.LOSS_STARTUP_ALREADY_INITIALIZED_CONFLICT,"startup state conflict",LoadClassification.LOADED)
   loader=getattr(self._adapter,"load",None) or getattr(self._adapter,"load_loss_state",None)
   if not callable(loader): return self._fail(StartupFailureCode.LOSS_STARTUP_LOAD_FAILED,"load unavailable")
   try: load_result=loader()
   except Exception: return self._fail(StartupFailureCode.LOSS_STARTUP_LOAD_FAILED,"persistence load failed")
   if not isinstance(load_result,LossPersistenceLoadResult): return self._fail(StartupFailureCode.LOSS_STARTUP_LOAD_RESULT_INVALID,"invalid persistence load result")
   classification=classify_load_result(load_result)
   current=None; lifecycle=RuntimeLifecycle.UNINITIALIZED
   inp=LossLimitRuntimeIntegrationInput(load_result,request.initial_state,current,lifecycle,request.startup_mode,request.recovery_status,request.received_at)
   try: decision=build_loss_limit_runtime_startup_decision(inp)
   except Exception: return self._fail(StartupFailureCode.LOSS_STARTUP_DECISION_FAILED,"startup decision failed",classification)
   if not isinstance(decision,LossLimitRuntimeStartupDecision): return self._fail(StartupFailureCode.LOSS_STARTUP_DECISION_INVALID,"invalid startup decision",classification)
   try: store_result=self._store.initialize(decision,request.occurred_at,self._initial_revision,self._initial_sequence)
   except Exception: return self._fail(StartupFailureCode.LOSS_STARTUP_STORE_INITIALIZATION_FAILED,"store initialization failed",classification)
   if not isinstance(store_result,LossLimitRuntimeStoreResult): return self._fail(StartupFailureCode.LOSS_STARTUP_STORE_INITIALIZATION_FAILED,"invalid store result",classification)
   if store_result.status is StoreResultStatus.FAILED:
    code=StartupFailureCode.LOSS_STARTUP_ALREADY_INITIALIZED_CONFLICT if store_result.failure and store_result.failure.code.value.endswith("ALREADY_INITIALIZED") else StartupFailureCode.LOSS_STARTUP_STORE_INITIALIZATION_FAILED
    return self._fail(code,"store initialization failed",classification)
   snap=store_result.snapshot
   recovery=decision.recovery_required or snap.lifecycle is RuntimeLifecycle.RECOVERY_REQUIRED
   status=StartupCoordinationStatus.RECOVERY_REQUIRED if recovery else (StartupCoordinationStatus.IDEMPOTENT if store_result.status is StoreResultStatus.IDEMPOTENT else StartupCoordinationStatus.SUCCEEDED)
   ready=not recovery and decision.runtime_start_allowed
   return LossLimitRuntimeStartupCoordinationResult(status,snap,classification,decision,store_result.status,ready,False if recovery else decision.new_entry_allowed,recovery,store_result.save_required,snap.save_triggers)
  except Exception: return self._fail(StartupFailureCode.LOSS_STARTUP_INTERNAL_FAILURE,"startup coordination failed")
