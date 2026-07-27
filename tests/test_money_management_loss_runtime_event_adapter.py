import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from backend.money_management.loss_runtime_event_adapter import *
from backend.money_management.loss_runtime_event_models import *
from backend.money_management.loss_runtime_integration_models import *
from tests.test_money_management_loss_persistence_contract import NOW, state
from tests.test_money_management_loss_runtime_checkpoint_coordinator import snapshot


D = Decimal


def event(**changes):
    values = dict(
        event_id="event-2",
        sequence=2,
        occurred_at=NOW + timedelta(seconds=1),
        event_type=LossRuntimeEventType.EQUITY_UPDATE,
        equity=D("1000"),
        balance=D("1000"),
        available_balance=D("900"),
        realized_pnl=D("-10"),
        unrealized_pnl=D("5"),
        daily_pnl=D("-5"),
        weekly_pnl=D("-10"),
        monthly_pnl=D("20"),
        peak_equity=D("1100"),
        drawdown=D("9.090909"),
        open_exposure=D("100"),
        position_count=1,
        trade_count=4,
        source="trading-runtime",
        symbol="BTCUSDT",
        exchange="example",
        account_id="account",
    )
    values.update(changes)
    return LossRuntimeEvent(**values)


def context(**changes):
    values = dict(
        event_id="event-2",
        next_state=state(),
        governance_projection=GovernanceProjection.CONTINUE,
        recovery_requirement=LossLimitRecoveryRequirement(
            False, (), False, False, False, "not required"
        ),
        save_triggers=(SaveTrigger.METRIC_CHANGED,),
        transition_reason="RUNTIME_METRICS_PROJECTED",
    )
    values.update(changes)
    return LossRuntimeUpdateBuildContext(**values)


class RuntimeEventAdapterTests(unittest.TestCase):
    def test_valid_event_builds_existing_runtime_update_contract(self):
        result = LossRuntimeEventAdapter().adapt(event(), snapshot(), context())
        self.assertEqual(result.status, LossRuntimeEventAdapterStatus.SUCCEEDED)
        request = result.update_request
        self.assertEqual(request.expected_revision, 1)
        self.assertEqual(request.event_sequence, 2)
        self.assertEqual(request.occurred_at, NOW + timedelta(seconds=1))
        self.assertEqual(request.save_triggers, (SaveTrigger.METRIC_CHANGED,))

    def test_snapshot_projection_is_minimal(self):
        result = LossRuntimeEventAdapter().adapt(event(), snapshot(), context())
        projected = result.snapshot_projection.to_dict()
        self.assertEqual(projected["equity"], "1000")
        self.assertEqual(projected["daily_pnl"], "-5")
        self.assertNotIn("account_id", projected)
        self.assertNotIn("symbol", projected)
        self.assertNotIn("exchange", projected)
        self.assertNotIn("balance", projected)

    def test_exact_duplicate_is_idempotent_without_new_request(self):
        adapter = LossRuntimeEventAdapter()
        first = adapter.adapt(event(), snapshot(), context())
        second = adapter.adapt(event(), snapshot(), context())
        self.assertEqual(first.status, LossRuntimeEventAdapterStatus.SUCCEEDED)
        self.assertEqual(second.status, LossRuntimeEventAdapterStatus.IDEMPOTENT)
        self.assertIs(second.update_request, first.update_request)

    def test_same_identity_with_different_payload_conflicts(self):
        adapter = LossRuntimeEventAdapter()
        adapter.adapt(event(), snapshot(), context())
        result = adapter.adapt(
            event(realized_pnl=D("-11")), snapshot(), context()
        )
        self.assertEqual(
            result.failure.code,
            LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_CONFLICT,
        )

    def test_event_id_alone_does_not_define_duplicate(self):
        adapter = LossRuntimeEventAdapter()
        first_event = event()
        adapter.adapt(first_event, snapshot(), context())
        advanced_snapshot = replace(
            snapshot(),
            revision=2,
            sequence=2,
            updated_at=first_event.occurred_at,
            save_triggers=(),
        )
        next_event = event(
            sequence=3, occurred_at=NOW + timedelta(seconds=2)
        )
        result = adapter.adapt(next_event, advanced_snapshot, context())
        self.assertEqual(result.status, LossRuntimeEventAdapterStatus.SUCCEEDED)

    def test_stale_sequence_is_rejected(self):
        stale = event(event_id="event-1", sequence=1)
        result = LossRuntimeEventAdapter().adapt(stale, snapshot(), context(event_id="event-1"))
        self.assertEqual(
            result.failure.code, LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_STALE
        )

    def test_sequence_gap_is_rejected(self):
        future = event(event_id="event-3", sequence=3)
        result = LossRuntimeEventAdapter().adapt(
            future, snapshot(), context(event_id="event-3")
        )
        self.assertEqual(
            result.failure.code,
            LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_SEQUENCE_GAP,
        )

    def test_past_or_equal_timestamp_is_rejected(self):
        result = LossRuntimeEventAdapter().adapt(
            event(occurred_at=NOW), snapshot(), context()
        )
        self.assertEqual(
            result.failure.code,
            LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_TIMESTAMP_INVALID,
        )

    def test_strict_numeric_validation(self):
        for changes in (
            {"equity": D("-1")},
            {"balance": D("-1")},
            {"drawdown": D("100.1")},
            {"position_count": -1},
            {"trade_count": True},
            {"equity": 1000},
        ):
            with self.assertRaises((TypeError, ValueError)):
                event(**changes)

    def test_unknown_event_and_naive_timestamp_are_rejected(self):
        with self.assertRaises(ValueError):
            event(event_type="UNKNOWN")
        with self.assertRaises(TypeError):
            event(occurred_at=NOW.replace(tzinfo=None))

    def test_context_must_match_event(self):
        result = LossRuntimeEventAdapter().adapt(
            event(), snapshot(), context(event_id="other")
        )
        self.assertEqual(
            result.failure.code,
            LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_CONTEXT_INVALID,
        )

    def test_event_context_and_inputs_are_not_mutated(self):
        source_event = event()
        source_context = context()
        source_snapshot = snapshot()
        before = (
            source_event.to_dict(),
            source_context.to_dict(),
            source_snapshot.to_dict(),
        )
        LossRuntimeEventAdapter().adapt(source_event, source_snapshot, source_context)
        self.assertEqual(
            before,
            (
                source_event.to_dict(),
                source_context.to_dict(),
                source_snapshot.to_dict(),
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            source_event.sequence = 9

    def test_exception_is_normalized_without_secret(self):
        with patch(
            "backend.money_management.loss_runtime_event_adapter._signature",
            side_effect=RuntimeError(
                "/home/private raw-payload-secret digest-secret"
            ),
        ):
            result = LossRuntimeEventAdapter().adapt(
                event(), snapshot(), context()
            )
        rendered = str(result.to_dict())
        self.assertEqual(
            result.failure.code,
            LossRuntimeEventFailureCode.LOSS_RUNTIME_EVENT_INTERNAL_FAILURE,
        )
        self.assertNotIn("private", rendered)
        self.assertNotIn("secret", rendered)

    def test_concurrent_same_event_has_one_success(self):
        adapter = LossRuntimeEventAdapter()
        source_event = event()
        source_snapshot = snapshot()
        source_context = context()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda _: adapter.adapt(
                        source_event, source_snapshot, source_context
                    ),
                    range(8),
                )
            )
        self.assertEqual(
            sum(
                item.status is LossRuntimeEventAdapterStatus.SUCCEEDED
                for item in results
            ),
            1,
        )
        self.assertEqual(
            sum(
                item.status is LossRuntimeEventAdapterStatus.IDEMPOTENT
                for item in results
            ),
            7,
        )

    def test_determinism_across_adapter_instances(self):
        first = LossRuntimeEventAdapter().adapt(event(), snapshot(), context())
        second = LossRuntimeEventAdapter().adapt(event(), snapshot(), context())
        self.assertEqual(first.to_dict(), second.to_dict())


if __name__ == "__main__":
    unittest.main()
