import unittest
from datetime import timedelta
from decimal import Decimal
from types import MappingProxyType

from backend.money_management.loss_authoritative_runtime_metrics import (
    AuthoritativeLossRuntimeMetricsState,
)
from backend.money_management.loss_runtime_integration_models import StateSource
from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeMetricsReadRequest,
    LossRuntimeMetricsReadStatus,
)
from backend.money_management.loss_runtime_metrics_source import (
    BotManagerLossRuntimeMetricsSource,
)
from tests.test_money_management_loss_authoritative_runtime_metrics import (
    NOW,
    persisted,
    observe,
)


D = Decimal


class Reader:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get_runtime_metrics_snapshot(self):
        return MappingProxyType(self.snapshot.to_runtime_mapping(0))


def read(snapshot, at):
    return BotManagerLossRuntimeMetricsSource(
        Reader(snapshot), timestamp_source=lambda: at
    ).read_metrics(
        LossRuntimeMetricsReadRequest("test", at, timedelta(minutes=1))
    )


class RuntimeSessionRehydrationTests(unittest.TestCase):
    def test_unknown_close_delta_preserves_existing_period_authority(self):
        state = AuthoritativeLossRuntimeMetricsState("runtime-1")
        state.restore(
            persisted(at=NOW, pnl=D("-25")),
            StateSource.PERSISTED_STATE,
            NOW,
        )

        closed = observe(
            state,
            at=NOW + timedelta(seconds=1),
            session_id=1,
            realized_pnl=None,
            realized_pnl_before=None,
            daily_realized_pnl=D("-30"),
            daily_realized_pnl_authoritative=True,
            close_event_id="unverified-live-close",
        )

        self.assertEqual(closed.weekly_realized_pnl, D("-25"))
        self.assertEqual(closed.monthly_realized_pnl, D("-25"))
        self.assertEqual(closed.daily_realized_pnl, D("-30"))

    def test_new_paper_session_rehydrates_valid_persisted_period_authority(self):
        state = AuthoritativeLossRuntimeMetricsState("runtime-1")
        state.begin_runtime_session(1, NOW)
        previous = observe(
            state,
            at=NOW + timedelta(seconds=1),
            session_id=1,
        )
        self.assertIsNone(previous.weekly_realized_pnl)
        self.assertIsNone(previous.monthly_realized_pnl)

        state.begin_runtime_session(
            2,
            NOW + timedelta(seconds=2),
            period_state=persisted(at=NOW, pnl=D("-25")),
            period_state_source=StateSource.PERSISTED_STATE,
        )
        paper = observe(
            state,
            at=NOW + timedelta(seconds=3),
            session_id=2,
        )

        self.assertEqual(paper.weekly_realized_pnl, D("-25"))
        self.assertEqual(paper.monthly_realized_pnl, D("-25"))
        self.assertTrue(paper.is_complete)
        self.assertEqual(
            read(paper, NOW + timedelta(seconds=4)).status,
            LossRuntimeMetricsReadStatus.AVAILABLE,
        )

    def test_paper_first_trade_bootstrap_needs_no_close(self):
        state = AuthoritativeLossRuntimeMetricsState("runtime-1")
        state.restore(
            persisted(at=NOW, pnl=D("-5")),
            StateSource.INITIAL_STATE,
            NOW,
        )
        state.begin_paper_session(1, NOW + timedelta(seconds=1))

        paper = observe(
            state,
            at=NOW + timedelta(seconds=2),
            session_id=1,
        )

        self.assertEqual(paper.session_trade_count, 0)
        self.assertEqual(paper.weekly_realized_pnl, D("-5"))
        self.assertEqual(paper.monthly_realized_pnl, D("-5"))
        self.assertTrue(paper.is_complete)
        self.assertEqual(
            read(paper, NOW + timedelta(seconds=3)).status,
            LossRuntimeMetricsReadStatus.AVAILABLE,
        )

    def test_unavailable_period_authority_stays_fail_closed(self):
        state = AuthoritativeLossRuntimeMetricsState("runtime-1")
        state.begin_runtime_session(1, NOW)

        paper = observe(
            state,
            at=NOW + timedelta(seconds=1),
            session_id=1,
        )

        self.assertIsNone(paper.weekly_realized_pnl)
        self.assertIsNone(paper.monthly_realized_pnl)
        self.assertFalse(paper.is_complete)
        self.assertEqual(
            read(paper, NOW + timedelta(seconds=2)).status,
            LossRuntimeMetricsReadStatus.PARTIAL,
        )


if __name__ == "__main__":
    unittest.main()
