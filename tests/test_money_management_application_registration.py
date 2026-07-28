import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from backend.money_management.loss_application_models import *
from backend.money_management.loss_application_registration import *
from backend.money_management.loss_application_settings import *
from backend.money_management.loss_models import LossLimitConfig


NOW = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)


def application():
    return SimpleNamespace(state=SimpleNamespace())


def readiness():
    return LossLimitCompositionReadiness(
        CompositionReadinessStatus.READY,
        True,
        True,
        True,
        False,
        True,
        False,
    )


def status(state=ApplicationLifecycleState.RUNNING, pending=False, revision=3):
    return LossLimitApplicationStatus(
        state,
        CompositionReadinessStatus.READY,
        state is ApplicationLifecycleState.RUNNING,
        RuntimeLifecycle.READY
        if state is ApplicationLifecycleState.RUNNING
        else RuntimeLifecycle.STOPPED,
        state is ApplicationLifecycleState.RUNNING,
        False,
        pending,
        revision,
        revision,
        LifecycleOperationStatus.SUCCEEDED.value,
        None,
    )


class Lifecycle:
    def __init__(self, startup_error=False, shutdown_error=False, pending=False):
        self.startup_error = startup_error
        self.shutdown_error = shutdown_error
        self.pending = pending
        self.startups = []
        self.shutdowns = []
        self.current = status()

    def startup(self, request):
        self.startups.append(request)
        if self.startup_error:
            raise RuntimeError("/home/private raw-state-secret fingerprint-secret")
        return SimpleNamespace(status=LifecycleOperationStatus.SUCCEEDED)

    def shutdown(self, request):
        self.shutdowns.append(request)
        if self.shutdown_error:
            raise RuntimeError("/home/private digest-secret os-error-secret")
        self.current = status(
            ApplicationLifecycleState.STOPPED, self.pending, request.expected_revision + 1
        )
        return SimpleNamespace(
            status=LifecycleOperationStatus.PARTIAL
            if self.pending
            else LifecycleOperationStatus.SUCCEEDED
        )

    def get_status(self):
        return self.current


def composition(adapter):
    ready = readiness()
    return LossLimitApplicationCompositionResult(
        CompositionReadinessStatus.READY, ready, adapter, None
    )


class ApplicationRegistrationTests(unittest.TestCase):
    def test_base_config_provider_is_application_scoped_and_read_only(self):
        app = application()
        configured = MoneyManagementConfig(
            MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,
            TradingMode.PAPER,
            Decimal("1000"),
            Decimal("0.50"),
            Decimal("100"),
            Decimal("5"),
            Decimal("25.00"),
            Decimal("10"),
            Decimal("5"),
            False,
        )
        registration = startup_money_management_application(
            app,
            configuration=LossLimitApplicationConfiguration(),
            base_configuration=configured,
        )

        first = get_money_management_config(app)
        second = get_money_management_config(app)
        self.assertIs(first, configured)
        self.assertIs(second, first)
        self.assertEqual(first.total_exposure_pct, Decimal("25.00"))
        self.assertNotIsInstance(first, LossLimitConfig)
        self.assertIs(registration.base_config_provider.get_config(), first)
        with self.assertRaises(AttributeError):
            registration.base_config_provider._config = configured
        updated = registration.base_config_provider.update_total_exposure_pct(
            Decimal("30.00")
        )
        self.assertEqual(updated.total_exposure_pct, Decimal("30.00"))
        self.assertIs(
            registration.base_config_provider,
            app.state.money_management.base_config_provider,
        )

    def test_base_config_provider_unregistered_and_invalid_states_are_explicit(self):
        app = application()
        self.assertIsNone(get_money_management_config(app))
        startup_money_management_application(
            app,
            configuration=LossLimitApplicationConfiguration(),
            base_configuration_factory=lambda: object(),
        )
        self.assertIsNone(get_money_management_config(app))
        first_app = application()
        second_app = application()
        startup_money_management_application(
            first_app,
            configuration=LossLimitApplicationConfiguration(),
        )
        startup_money_management_application(
            second_app,
            configuration=LossLimitApplicationConfiguration(),
        )
        self.assertIsNot(
            get_money_management_config(first_app),
            get_money_management_config(second_app),
        )

    def test_settings_default_disabled_and_strict_booleans(self):
        self.assertFalse(
            resolve_loss_limit_application_configuration(environ={}).enabled
        )
        root = Path("/srv/tradingai")
        configured = resolve_loss_limit_application_configuration(
            environ={
                "MONEY_MANAGEMENT_ENABLED": "1",
                "MONEY_MANAGEMENT_PERSISTENCE_ENABLED": "true",
                "MONEY_MANAGEMENT_PERSISTENCE_PATH": (
                    "/srv/tradingai/logs/runtime/mm"
                ),
            },
            repository_root=root,
        )
        self.assertTrue(configured.enabled)
        with self.assertRaises(LossLimitApplicationSettingsError):
            resolve_loss_limit_application_configuration(
                environ={"MONEY_MANAGEMENT_ENABLED": "yes"}
            )

    def test_settings_reject_implicit_and_unsafe_paths(self):
        base = {
            "MONEY_MANAGEMENT_ENABLED": "true",
            "MONEY_MANAGEMENT_PERSISTENCE_ENABLED": "true",
        }
        for path in ("relative/mm", "/tmp/mm", "/home/user/mm"):
            with self.assertRaises(LossLimitApplicationSettingsError):
                resolve_loss_limit_application_configuration(
                    environ={**base, "MONEY_MANAGEMENT_PERSISTENCE_PATH": path},
                    repository_root=Path("/srv/tradingai"),
                )

    def test_disabled_registration_is_safe_and_skips_lifecycle(self):
        app = application()
        result = startup_money_management_application(
            app, configuration=LossLimitApplicationConfiguration()
        )
        self.assertEqual(
            result.composition_status, CompositionReadinessStatus.DISABLED
        )
        self.assertIsNone(result.lifecycle_adapter)
        self.assertFalse(result.safe_status.runtime_available)
        self.assertFalse(result.safe_status.new_entry_allowed)

    def test_enabled_startup_registers_safe_status_once(self):
        app = application()
        adapter = Lifecycle()
        config = LossLimitApplicationConfiguration(
            True, True, Path("/srv/tradingai/logs/runtime/mm")
        )
        factory_calls = []

        def factory(value):
            factory_calls.append(value)
            return composition(adapter)

        first = startup_money_management_application(
            app,
            configuration=config,
            composition_factory=factory,
            timestamp_source=lambda: NOW,
        )
        second = startup_money_management_application(
            app,
            configuration=config,
            composition_factory=factory,
            timestamp_source=lambda: NOW,
        )
        self.assertIs(first, second)
        self.assertIs(
            first.base_config_provider,
            second.base_config_provider,
        )
        self.assertEqual(len(factory_calls), 1)
        self.assertEqual(len(adapter.startups), 1)
        self.assertTrue(first.safe_status.runtime_available)
        self.assertTrue(first.safe_status.new_entry_allowed)
        self.assertIs(app.state.money_management, first)

    def test_startup_exception_is_fail_closed_and_secret_safe(self):
        app = application()
        adapter = Lifecycle(startup_error=True)
        config = LossLimitApplicationConfiguration(
            True, True, Path("/srv/tradingai/logs/runtime/mm")
        )
        result = startup_money_management_application(
            app,
            configuration=config,
            composition_factory=lambda value: composition(adapter),
            timestamp_source=lambda: NOW,
        )
        rendered = repr(result) + str(result.to_dict())
        self.assertEqual(result.startup_status, LifecycleOperationStatus.FAILED)
        self.assertFalse(result.safe_status.runtime_available)
        self.assertFalse(result.safe_status.new_entry_allowed)
        self.assertNotIn("private", rendered)
        self.assertNotIn("secret", rendered)

    def test_composition_exception_is_fail_closed(self):
        app = application()
        config = LossLimitApplicationConfiguration(
            True, True, Path("/srv/tradingai/logs/runtime/mm")
        )

        def broken(value):
            raise RuntimeError("/home/private raw-state-secret")

        result = startup_money_management_application(
            app, configuration=config, composition_factory=broken
        )
        self.assertEqual(
            result.composition_status, CompositionReadinessStatus.COMPOSITION_FAILED
        )
        self.assertFalse(result.safe_status.runtime_available)
        self.assertNotIn("private", str(result.to_dict()))

    def test_shutdown_uses_safe_revision_once(self):
        app = application()
        adapter = Lifecycle()
        config = LossLimitApplicationConfiguration(
            True, True, Path("/srv/tradingai/logs/runtime/mm")
        )
        startup_money_management_application(
            app,
            configuration=config,
            composition_factory=lambda value: composition(adapter),
            timestamp_source=lambda: NOW,
        )
        first = shutdown_money_management_application(
            app, timestamp_source=lambda: NOW
        )
        second = shutdown_money_management_application(
            app, timestamp_source=lambda: NOW
        )
        self.assertIs(first, second)
        self.assertEqual(len(adapter.shutdowns), 1)
        self.assertEqual(adapter.shutdowns[0].expected_revision, 3)
        self.assertEqual(first.shutdown_status, LifecycleOperationStatus.SUCCEEDED)
        self.assertFalse(first.safe_status.runtime_available)

    def test_shutdown_exception_is_safe_and_non_raising(self):
        app = application()
        adapter = Lifecycle(shutdown_error=True)
        config = LossLimitApplicationConfiguration(
            True, True, Path("/srv/tradingai/logs/runtime/mm")
        )
        startup_money_management_application(
            app,
            configuration=config,
            composition_factory=lambda value: composition(adapter),
            timestamp_source=lambda: NOW,
        )
        result = shutdown_money_management_application(
            app, timestamp_source=lambda: NOW
        )
        rendered = repr(result) + str(result.to_dict())
        self.assertEqual(result.shutdown_status, LifecycleOperationStatus.FAILED)
        self.assertFalse(result.safe_status.new_entry_allowed)
        self.assertNotIn("private", rendered)
        self.assertNotIn("secret", rendered)


if __name__ == "__main__":
    unittest.main()
