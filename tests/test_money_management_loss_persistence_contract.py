import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from backend.money_management.loss_persistence_models import (
    PERSISTENCE_SCHEMA_VERSION, CONFIG_SCHEMA_VERSION, PeriodCode, CashFlowType,
    FreshnessStatus, PersistedLossPeriodState, PersistedDrawdownState,
    PersistedCashFlowState, PersistedLossState)
from backend.money_management.loss_reason_models import LossReasonContract, RecommendedAction, ReasonCode
from backend.money_management.enums import RiskState
D=Decimal
NOW=datetime(2026,1,5,12,tzinfo=timezone.utc)
def period(code,start,end,pnl=D("0"),cash=D("0"),updated=NOW):
    loss=max(D("0"),-pnl)
    return PersistedLossPeriodState(code,code.value+"-1",start,end,D("1000"),pnl,loss,loss/D("1000")*D("100"),cash,updated)
def decision(at=NOW):
    return LossReasonContract("money-management-loss-reason/v1",at,RiskState.NORMAL,RecommendedAction.CONTINUE,ReasonCode.NONE,(),(),(),(),(),(),False)
def state(**kw):
    day=period(PeriodCode.DAILY,datetime(2026,1,5,tzinfo=timezone.utc),datetime(2026,1,6,tzinfo=timezone.utc))
    week=period(PeriodCode.WEEKLY,datetime(2026,1,5,tzinfo=timezone.utc),datetime(2026,1,12,tzinfo=timezone.utc))
    month=period(PeriodCode.MONTHLY,datetime(2026,1,1,tzinfo=timezone.utc),datetime(2026,2,1,tzinfo=timezone.utc))
    draw=PersistedDrawdownState(D("1100"),D("1000"),D("100"),D("100")/D("1100")*D("100"),NOW)
    values=dict(schema_version=PERSISTENCE_SCHEMA_VERSION,account_scope="primary",valuation_currency="USDT",daily_state=day,weekly_state=week,monthly_state=month,drawdown_state=draw,cash_flow_state=PersistedCashFlowState(False,(),D("0")),last_decision=decision(),captured_at=NOW)
    values.update(kw)
    return PersistedLossState(**values)
class PersistenceContractTests(unittest.TestCase):
    def test_valid_top_level_and_nested_contract(self):
        s=state(); self.assertEqual(s.schema_version,PERSISTENCE_SCHEMA_VERSION); self.assertEqual(s.risk_state,RiskState.NORMAL); self.assertEqual(s.to_dict(),s.to_dict())
    def test_period_identity_and_derived_values(self):
        p=period(PeriodCode.DAILY,NOW,NOW+timedelta(hours=1),D("-25")); self.assertEqual(p.net_loss,D("25")); self.assertEqual(p.loss_percent,D("2.5"))
        with self.assertRaises(ValueError): period(PeriodCode.DAILY,NOW,NOW,D("0"))
        with self.assertRaises(ValueError): PersistedLossPeriodState(PeriodCode.DAILY,"x",NOW,NOW+timedelta(hours=1),D("1000"),D("-1"),D("0"),D("0"),D("0"),NOW)
    def test_starting_equity_and_strict_decimal(self):
        with self.assertRaises(ValueError): PersistedLossPeriodState(PeriodCode.DAILY,"x",NOW,NOW+timedelta(hours=1),D("0"),D("0"),D("0"),D("0"),D("0"),NOW)
        with self.assertRaises(TypeError): PersistedLossPeriodState(PeriodCode.DAILY,"x",NOW,NOW+timedelta(hours=1),1000,D("0"),D("0"),D("0"),D("0"),NOW)
        with self.assertRaises(ValueError): PersistedDrawdownState(D("0"),D("0"),D("0"),D("0"),NOW)
    def test_drawdown_and_negative_equity_fail_closed(self):
        with self.assertRaises(ValueError): PersistedDrawdownState(D("100"),D("-1"),D("101"),D("101"),NOW)
        with self.assertRaises(ValueError): PersistedDrawdownState(D("100"),D("80"),D("1"),D("1"),NOW)
    def test_cash_flow_types_are_typed_unique_and_minimal(self):
        c=PersistedCashFlowState(True,(CashFlowType.DEPOSIT,CashFlowType.TRANSFER),D("20"),NOW); self.assertEqual(c.to_dict()["cash_flow_types"],["DEPOSIT","TRANSFER"])
        with self.assertRaises(ValueError): PersistedCashFlowState(True,(CashFlowType.DEPOSIT,CashFlowType.DEPOSIT),D("1"))
        with self.assertRaises(ValueError): PersistedCashFlowState(False,(CashFlowType.DEPOSIT,),D("1"))
    def test_timestamp_order_and_version(self):
        with self.assertRaises(ValueError): state(captured_at=NOW-timedelta(seconds=1))
        with self.assertRaises(ValueError): state(schema_version="money-management-loss-state/v2")
        with self.assertRaises(ValueError): state(config_schema_version="money-management-config/v2")
    def test_timezone_and_freshness(self):
        with self.assertRaises(TypeError): state(captured_at=datetime(2026,1,5,12))
        self.assertEqual(state(freshness=FreshnessStatus.STALE).freshness,FreshnessStatus.STALE)
    def test_deep_immutability_and_no_runtime_fallback(self):
        s=state()
        with self.assertRaises(FrozenInstanceError): s.daily_state=s.daily_state
        with self.assertRaises(FrozenInstanceError): s.daily_state.net_loss=D("1")
        before=s.to_dict(); self.assertEqual(s.to_dict(),before); self.assertNotEqual(s.risk_state,RiskState.LOCKED)
if __name__=="__main__": unittest.main()
