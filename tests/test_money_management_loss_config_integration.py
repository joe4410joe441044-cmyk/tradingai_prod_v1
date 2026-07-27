import unittest
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

from backend.money_management.config_models import CONFIG_SCHEMA_VERSION, MoneyManagementConfigRoot
from backend.money_management.config_resolver import resolve_loss_limit_config
from backend.money_management.enums import MoneyManagementProfile, TradingMode
from backend.money_management.loss_models import LossLimitConfig
from backend.money_management.models import MoneyManagementConfig


def D(value):
    return Decimal(value)


def base_config(**changes):
    values = dict(
        profile=MoneyManagementProfile.CAPITAL_PROTECTION_STANDARD,
        mode=TradingMode.PAPER,
        initial_reference_equity=D("1000"), risk_per_trade_pct=D(".50"),
        maximum_position_notional=D("100"), maximum_drawdown_pct=D("5"),
        total_exposure_pct=D("20"), single_symbol_exposure_pct=D("10"),
        maximum_leverage=D("5"), multi_bot_enabled=False,
    )
    values.update(changes)
    return MoneyManagementConfig(**values)


class LossConfigIntegrationTests(unittest.TestCase):
    def root(self, loss=None, base=None):
        return MoneyManagementConfigRoot(CONFIG_SCHEMA_VERSION, base or base_config(), loss or LossLimitConfig())

    def test_nested_config_is_resolved_without_override(self):
        loss = LossLimitConfig(daily_warning_pct=D("1.10"), daily_block_pct=D("1.50"))
        root = self.root(loss=loss, base=base_config(daily_loss_warning_pct=D("1.10")))
        self.assertIs(resolve_loss_limit_config(root), loss)

    def test_legacy_threshold_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            self.root(base=base_config(daily_loss_warning_pct=D("1.10")))

    def test_schema_and_types_are_strict(self):
        with self.assertRaises(ValueError):
            MoneyManagementConfigRoot("money-management-config/v2", base_config(), LossLimitConfig())
        with self.assertRaises(TypeError):
            MoneyManagementConfigRoot(CONFIG_SCHEMA_VERSION, base_config(), object())
        with self.assertRaises(TypeError):
            resolve_loss_limit_config(LossLimitConfig())

    def test_decimal_config_validation_is_not_coercive(self):
        with self.assertRaises(TypeError):
            LossLimitConfig(daily_warning_pct=1)

    def test_serialization_is_nested_and_deterministic(self):
        root = self.root()
        first, second = root.to_dict(), root.to_dict()
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], CONFIG_SCHEMA_VERSION)
        self.assertEqual(first["loss_limits"]["daily_warning_pct"], "1.00")
        self.assertIn("base_config", first)

    def test_root_and_child_are_immutable(self):
        root = self.root()
        with self.assertRaises(FrozenInstanceError):
            root.loss_limits = LossLimitConfig()
        with self.assertRaises(FrozenInstanceError):
            root.loss_limits.daily_warning_pct = D("1.1")
        original = root.to_dict()
        _ = resolve_loss_limit_config(root)
        self.assertEqual(root.to_dict(), original)

    def test_root_is_reproducible_for_equal_inputs(self):
        self.assertEqual(self.root(), self.root())
        self.assertEqual(self.root().to_dict(), self.root().to_dict())


if __name__ == "__main__":
    unittest.main()
