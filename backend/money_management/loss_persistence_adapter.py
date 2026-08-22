"""MM-3B safe atomic filesystem adapter."""
import errno
import json
import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional
import hmac
from datetime import datetime, timezone
from decimal import Decimal, DecimalException

from .loss_persistence_models import *
from .loss_persistence_serialization import (
    MAX_FILE_SIZE, ENVELOPE_VERSION, INTEGRITY_ALGORITHM,
    build_canonical_loss_state_json, build_integrity_digest,
    serialize_loss_persistence_envelope,
)
from .loss_reason_models import (
    LossReasonContract, RecommendedAction, ReasonCode, WarningReason,
    HoldReason, BlockReason, DiagnosticReason, PeriodCode as ReasonPeriodCode, LossMetric,
)
from .enums import RiskState

TARGET_FILENAME = "loss_limit_state.json"
TEMP_FILENAME = ".loss_limit_state.json.tmp"

class LoadStatus(str, Enum):
    VALID="VALID"; MISSING="MISSING"; CORRUPT="CORRUPT"; INCOMPATIBLE_VERSION="INCOMPATIBLE_VERSION"; UNSAFE_PATH="UNSAFE_PATH"; UNSAFE_FILE="UNSAFE_FILE"; TOO_LARGE="TOO_LARGE"; IO_ERROR="IO_ERROR"
class SaveStatus(str, Enum):
    SAVED="SAVED"; FAILED="FAILED"
class SaveFailureCode(str, Enum):
    INVALID_STATE="INVALID_STATE"; UNSAFE_PATH="UNSAFE_PATH"; UNSAFE_FILE="UNSAFE_FILE"; TEMPORARY_FILE_EXISTS="TEMPORARY_FILE_EXISTS"; TOO_LARGE="TOO_LARGE"; SERIALIZATION_FAILED="SERIALIZATION_FAILED"; WRITE_FAILED="WRITE_FAILED"; FSYNC_FAILED="FSYNC_FAILED"; REPLACE_FAILED="REPLACE_FAILED"; DIRECTORY_FSYNC_FAILED="DIRECTORY_FSYNC_FAILED"; CLEANUP_FAILED="CLEANUP_FAILED"
@dataclass(frozen=True)
class LossPersistenceLoadResult:
    status: LoadStatus
    state: Optional[PersistedLossState] = None
    failure_code: Optional[str] = None
    safe_message: Optional[str] = None
    def __post_init__(self):
        object.__setattr__(self,"status",LoadStatus(self.status))
        if self.status is LoadStatus.VALID and (self.state is None or self.failure_code is not None): raise ValueError("invalid valid result")
        if self.status is not LoadStatus.VALID and (self.state is not None or not self.failure_code): raise ValueError("invalid failure result")
    def to_dict(self): return {"status":self.status.value,"state":self.state.to_dict() if self.state else None,"failure_code":self.failure_code,"safe_message":self.safe_message}
@dataclass(frozen=True)
class LossPersistenceSaveResult:
    status: SaveStatus
    failure_code: Optional[SaveFailureCode] = None
    safe_message: Optional[str] = None
    def __post_init__(self):
        object.__setattr__(self,"status",SaveStatus(self.status))
        if self.status is SaveStatus.SAVED and self.failure_code is not None: raise ValueError("saved result cannot fail")
        if self.status is SaveStatus.FAILED and self.failure_code is None: raise ValueError("failed result requires code")
    def to_dict(self): return {"status":self.status.value,"failure_code":self.failure_code.value if self.failure_code else None,"safe_message":self.safe_message}

def _dt(v):
    if not isinstance(v,str): raise ValueError("invalid datetime")
    return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)
def _dec(v):
    if not isinstance(v,str): raise ValueError("invalid decimal")
    return Decimal(v)
def _period(d):
    return PersistedLossPeriodState(PeriodCode(d["period_code"]),d["period_id"],_dt(d["period_start"]),_dt(d["period_end"]),_dec(d["starting_equity"]),_dec(d["net_realized_pnl"]),_dec(d["net_loss"]),_dec(d["loss_percent"]),_dec(d["cash_flow_amount"]),_dt(d["last_updated_at"]),LossBaselineType(d.get("baseline_type",LossBaselineType.PERIOD_BOUNDARY_BASELINE.value)),_dt(d["baseline_observed_at"]) if d.get("baseline_observed_at") else None)
def _rebase(d):
    expected={"rebase_id","observed_at","authoritative_equity","authority_source","account_scope","runtime_instance_id","affected_periods","previous_period_ids","new_period_ids","observed_period_pnl","reason","continuity_status","authorization_state","audit_marker"}
    if set(d)!=expected: raise ValueError("rebase payload shape invalid")
    return PersistedAccountingRebaseRecord(d["rebase_id"],_dt(d["observed_at"]),_dec(d["authoritative_equity"]),AccountingRebaseAuthoritySource(d["authority_source"]),d["account_scope"],d["runtime_instance_id"],tuple(PeriodCode(x) for x in d["affected_periods"]),tuple(d["previous_period_ids"]),tuple(d["new_period_ids"]),tuple(_dec(x) for x in d["observed_period_pnl"]),AccountingRebaseReason(d["reason"]),AccountingContinuityStatus(d["continuity_status"]),AccountingRebaseAuthorizationState(d["authorization_state"]),AccountingRebaseAuditMarker(d["audit_marker"]))
def _reason(d):
    metrics=tuple(LossMetric(ReasonPeriodCode(x["period"]),_dec(x["net_loss"]),_dec(x["loss_percent"])) for x in d["metrics"])
    return LossReasonContract(d["schema_version"],_dt(d["evaluated_at"]),RiskState(d["decision_state"]),RecommendedAction(d["recommended_action"]),ReasonCode(d["primary_reason"]),tuple(WarningReason(x) for x in d["warning_reasons"]),tuple(HoldReason(x) for x in d["hold_reasons"]),tuple(BlockReason(x) for x in d["block_reasons"]),tuple(DiagnosticReason(x) for x in d["diagnostic_reasons"]),tuple(ReasonPeriodCode(x) for x in d["triggered_periods"]),metrics,bool(d["fail_closed"]))
def _state(d):
    expected={"schema_version","config_schema_version","account_scope","valuation_currency","daily_state","weekly_state","monthly_state","drawdown_state","cash_flow_state","last_decision","captured_at","freshness"}
    if set(d) not in (expected, expected|{"accounting_rebases"}): raise ValueError("payload shape invalid")
    dd=d["drawdown_state"]; cf=d["cash_flow_state"]
    return PersistedLossState(d["schema_version"],d["account_scope"],d["valuation_currency"],_period(d["daily_state"]),_period(d["weekly_state"]),_period(d["monthly_state"]),PersistedDrawdownState(_dec(dd["high_water_mark"]),_dec(dd["current_equity"]),_dec(dd["drawdown_amount"]),_dec(dd["drawdown_percent"]),_dt(dd["last_updated_at"])),PersistedCashFlowState(bool(cf["has_unresolved_cash_flow"]),tuple(CashFlowType(x) for x in cf["cash_flow_types"]),_dec(cf["net_cash_flow_amount"]),_dt(cf["last_cash_flow_at"]) if cf["last_cash_flow_at"] else None),_reason(d["last_decision"]),_dt(d["captured_at"]),d["config_schema_version"],FreshnessStatus(d["freshness"]),tuple(_rebase(x) for x in d.get("accounting_rebases",())))

def _strict_pairs(pairs):
    def hook(obj):
        keys=[x[0] for x in obj]
        if len(keys)!=len(set(keys)): raise ValueError("duplicate JSON key")
        return dict(obj)
    return json.loads(pairs, object_pairs_hook=hook, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("invalid constant")))

def _safe_base(base):
    if not isinstance(base,Path) or not base.is_absolute(): raise ValueError("base directory required")
    if not base.exists() or not base.is_dir() or base.is_symlink(): raise OSError("unsafe base directory")
    current=Path(base.anchor)
    for part in base.parts[1:]:
        current=current/part
        if current.is_symlink(): raise OSError("unsafe parent directory")
    return base

def save_loss_state(state: PersistedLossState, base_directory: Path) -> LossPersistenceSaveResult:
    temp = None
    phase = "write"
    try:
        if not isinstance(state,PersistedLossState): return LossPersistenceSaveResult(SaveStatus.FAILED,SaveFailureCode.INVALID_STATE,"invalid state")
        try:
            base=_safe_base(base_directory)
        except (ValueError,OSError):
            return LossPersistenceSaveResult(SaveStatus.FAILED,SaveFailureCode.UNSAFE_PATH,"unsafe path")
        target=base / TARGET_FILENAME; temp=base / TEMP_FILENAME
        if target.exists() and (target.is_symlink() or not stat.S_ISREG(target.stat().st_mode) or target.stat().st_mode & 0o077): return LossPersistenceSaveResult(SaveStatus.FAILED,SaveFailureCode.UNSAFE_FILE,"unsafe target")
        if temp.exists(): return LossPersistenceSaveResult(SaveStatus.FAILED,SaveFailureCode.TEMPORARY_FILE_EXISTS,"temporary file exists")
        raw=serialize_loss_persistence_envelope(state)
        if len(raw)>MAX_FILE_SIZE: return LossPersistenceSaveResult(SaveStatus.FAILED,SaveFailureCode.TOO_LARGE,"state too large")
        fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0),0o600)
        try:
            offset=0
            while offset<len(raw):
                n=os.write(fd,raw[offset:])
                if n<=0: raise OSError("short write")
                offset+=n
            phase = "file_fsync"
            os.fsync(fd)
        finally: os.close(fd)
        if temp.is_symlink() or not stat.S_ISREG(temp.stat().st_mode): raise OSError("unsafe temp")
        phase = "replace"
        os.replace(temp,target)
        fd=os.open(base,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try:
            phase = "directory_fsync"
            os.fsync(fd)
        finally: os.close(fd)
        return LossPersistenceSaveResult(SaveStatus.SAVED)
    except ValueError: return LossPersistenceSaveResult(SaveStatus.FAILED,SaveFailureCode.SERIALIZATION_FAILED,"serialization failed")
    except OSError as exc:
        code={"file_fsync":SaveFailureCode.FSYNC_FAILED,"directory_fsync":SaveFailureCode.DIRECTORY_FSYNC_FAILED,"replace":SaveFailureCode.REPLACE_FAILED}.get(phase,SaveFailureCode.WRITE_FAILED)
        return LossPersistenceSaveResult(SaveStatus.FAILED,code,"persistence failed")
    finally:
        if temp is not None and temp.exists() and not temp.is_symlink():
            try: temp.unlink()
            except OSError: pass

def load_loss_state(base_directory: Path) -> LossPersistenceLoadResult:
    if not isinstance(base_directory, Path) or not base_directory.is_absolute():
        return LossPersistenceLoadResult(LoadStatus.UNSAFE_PATH, None, "UNSAFE_PATH", "unsafe path")
    try:
        base=_safe_base(base_directory)
        target=base/TARGET_FILENAME
        if not target.exists(): return LossPersistenceLoadResult(LoadStatus.MISSING,None,"MISSING","state missing")
        if target.is_symlink() or not stat.S_ISREG(target.stat().st_mode): return LossPersistenceLoadResult(LoadStatus.UNSAFE_FILE,None,"UNSAFE_FILE","unsafe file")
        st=target.stat()
        if st.st_size>MAX_FILE_SIZE: return LossPersistenceLoadResult(LoadStatus.TOO_LARGE,None,"TOO_LARGE","state too large")
        if st.st_mode & 0o077: return LossPersistenceLoadResult(LoadStatus.UNSAFE_FILE,None,"UNSAFE_FILE","unsafe permissions")
        fd=os.open(target,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
        try: raw=os.read(fd,MAX_FILE_SIZE+1)
        finally: os.close(fd)
        if len(raw)>MAX_FILE_SIZE: return LossPersistenceLoadResult(LoadStatus.TOO_LARGE,None,"TOO_LARGE","state too large")
        obj=_strict_pairs(raw.decode("utf-8"))
        if not isinstance(obj,dict): raise ValueError("root must object")
        expected={"envelope_version","integrity_algorithm","integrity_digest","payload"}
        if set(obj)!=expected: raise ValueError("envelope shape invalid")
        if obj["envelope_version"]!=ENVELOPE_VERSION or obj["integrity_algorithm"]!=INTEGRITY_ALGORITHM: return LossPersistenceLoadResult(LoadStatus.INCOMPATIBLE_VERSION,None,"INCOMPATIBLE_VERSION","incompatible version")
        payload=obj["payload"]; canonical=json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode("utf-8")
        digest=build_integrity_digest(canonical)
        if not isinstance(obj["integrity_digest"],str) or len(obj["integrity_digest"])!=64 or not hmac.compare_digest(digest,obj["integrity_digest"]): raise ValueError("digest mismatch")
        return LossPersistenceLoadResult(LoadStatus.VALID,_state(payload))
    except UnicodeDecodeError: return LossPersistenceLoadResult(LoadStatus.CORRUPT,None,"CORRUPT","invalid encoding")
    except (ValueError,KeyError,TypeError,OverflowError,DecimalException): return LossPersistenceLoadResult(LoadStatus.CORRUPT,None,"CORRUPT","invalid state")
    except OSError: return LossPersistenceLoadResult(LoadStatus.IO_ERROR,None,"IO_ERROR","I/O failed")
