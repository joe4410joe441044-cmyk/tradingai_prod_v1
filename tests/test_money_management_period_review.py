import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from backend.money_management.period_models import PERIOD_SCHEMA_VERSION, MoneyManagementPnlEvent, PnlEventType, PnlEventSource
from backend.money_management.period_aggregation import period_for, build_period_aggregate
from backend.money_management.period_models import PeriodType
D=Decimal
NOW=datetime(2026,7,26,12,tzinfo=timezone.utc)
def make(**kw):
    b=dict(schema_version=PERIOD_SCHEMA_VERSION,event_id="e",occurred_at=NOW,recorded_at=NOW,event_type=PnlEventType.REALIZED_PNL,symbol="BTCUSDT",gross_realized_pnl=D("1"),fees=D("0"),funding=D("0"),currency="USDT",source=PnlEventSource.EXECUTION_NORMALIZED,sequence=1); b.update(kw); return MoneyManagementPnlEvent(**b)
class PeriodReviewTests(unittest.TestCase):
    def test_whitespace_identifier_rejected(self):
        for value in (" ","  \t  ","\n"):
            with self.assertRaises(ValueError): make(event_id=value)
    def test_event_id_length_boundaries(self):
        make(event_id="x"*128)
        with self.assertRaises(ValueError): make(event_id="x"*129)
    def test_recorded_at_only_difference_is_currently_conflict(self):
        p=period_for(NOW,PeriodType.DAILY); first=make(); replay=make(recorded_at=NOW+timedelta(seconds=1))
        with self.assertRaises(ValueError): build_period_aggregate((first,replay),p)
    def test_fee_funding_and_zero_net(self):
        e=make(gross_realized_pnl=D("0"),fees=D("1"),funding=D("1"))
        a=build_period_aggregate((e,),period_for(NOW,PeriodType.DAILY))
        self.assertEqual(a.net_realized_pnl,D("0")); self.assertEqual(a.winning_event_count,0); self.assertEqual(a.losing_event_count,0)
if __name__=="__main__": unittest.main()
