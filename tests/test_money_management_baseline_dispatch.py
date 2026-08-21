#!/usr/bin/env python3
"""Test for baseline dispatch when metrics are unavailable."""

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeUpdateDispatcher,
    LossRuntimeDispatchStatus,
)
from backend.money_management.loss_runtime_metrics_source import LossRuntimeMetricsSource
from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeMetricsReadResult,
    LossRuntimeMetricsReadStatus,
    LossRuntimeMetrics,
)
from backend.money_management.loss_runtime_event_models import LossRuntimeEventType
from tests.test_money_management_loss_runtime_update_dispatcher import (
    app_with,
    Lifecycle,
    request,
    metrics,
)


class UnavailableMetricsSource(LossRuntimeMetricsSource):
    """A metrics source that always returns UNAVAILABLE status."""

    def read_metrics(self, request):
        return LossRuntimeMetricsReadResult(
            LossRuntimeMetricsReadStatus.UNAVAILABLE,
            None,
            ("runtime metrics unavailable",),
        )


class BaselineDispatchTests(unittest.TestCase):
    """Tests for baseline dispatch when metrics are unavailable."""

    def test_baseline_dispatch_with_unavailable_metrics(self):
        """Test that baseline dispatch works with unavailable metrics."""
        lifecycle = Lifecycle()
        dispatcher = LossRuntimeUpdateDispatcher(UnavailableMetricsSource())
        
        # First dispatch - should return IDEMPOTENT (baseline)
        result = dispatcher.dispatch(
            app_with(lifecycle),
            request(),
            LossRuntimeEventType.POSITION_UPDATE,
        )
        
        self.assertEqual(result.status, LossRuntimeDispatchStatus.IDEMPOTENT)
        self.assertIn("baseline dispatch - metrics unavailable", result.safe_reasons)
        self.assertIsNotNone(result.runtime_revision)
        self.assertIsNotNone(result.runtime_sequence)

    def test_baseline_dispatch_preserves_fail_safe(self):
        """Test that baseline dispatch preserves fail-safe behavior for other errors."""
        lifecycle = Lifecycle()
        # Create a dispatcher with a source that raises an exception
        class ExceptionSource(LossRuntimeMetricsSource):
            def read_metrics(self, request):
                raise RuntimeError("metrics source failure")
                
        dispatcher = LossRuntimeUpdateDispatcher(ExceptionSource())
        
        result = dispatcher.dispatch(
            app_with(lifecycle),
            request(),
            LossRuntimeEventType.POSITION_UPDATE,
        )
        
        self.assertEqual(result.status, LossRuntimeDispatchStatus.FAILED)


if __name__ == "__main__":
    unittest.main()