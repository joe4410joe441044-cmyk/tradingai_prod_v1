import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal

from backend.money_management.position_risk import (
    PositionSizingInput,
    calculate_position_size,
    calculate_risk_budget,
)


D = Decimal


def sizing_input(**overrides):
    values = {
        "entry_price": D("0.50"),
        "stop_loss_percent": D("1.00"),
        "effective_cost_percent": D("0.20"),
        "risk_percent": D("0.50"),
        "risk_base_capital": D("1000"),
        "maximum_position_notional": D("100"),
        "total_exposure_remaining": D("200"),
        "available_capital": D("900"),
        "quantity_step": D("0.001"),
        "contract_multiplier": D("1"),
        "risk_budget_remaining": D("5"),
    }
    values.update(overrides)
    return PositionSizingInput(**values)


class PositionSizingCalculatorTests(unittest.TestCase):
    def test_decimal_calculation_limits_and_rounding_are_deterministic(self):
        value = sizing_input()
        first = calculate_position_size(value)
        second = calculate_position_size(value)

        self.assertEqual(first, second)
        self.assertEqual(first.risk_amount, D("5"))
        self.assertEqual(first.raw_position_notional, D("416.6666666666666666666666667"))
        self.assertEqual(first.final_position_notional, D("100.0000"))
        self.assertEqual(first.position_quantity, D("200.000"))
        self.assertEqual(first.applied_limits, ("MAXIMUM_POSITION_NOTIONAL",))
        self.assertTrue(first.calculation_allowed)
        self.assertEqual(first.to_dict()["positionQuantity"], "200")
        with self.assertRaises(FrozenInstanceError):
            value.entry_price = D("1")

    def test_each_capacity_and_multiple_equal_limits_are_reported(self):
        result = calculate_position_size(sizing_input(
            maximum_position_notional=D("80"),
            total_exposure_remaining=D("80"),
            available_capital=D("80"),
            risk_budget_remaining=D("0.96"),
        ))
        self.assertEqual(
            result.applied_limits,
            (
                "MAXIMUM_POSITION_NOTIONAL",
                "TOTAL_EXPOSURE_REMAINING",
                "AVAILABLE_CAPITAL",
                "RISK_BUDGET_REMAINING",
            ),
        )

    def test_zero_quantity_and_invalid_inputs_fail_safely(self):
        zero = calculate_position_size(sizing_input(
            risk_budget_remaining=D("0"),
        ))
        self.assertFalse(zero.calculation_allowed)
        self.assertEqual(zero.reasons, ("POSITION_SIZE_ZERO",))
        for patch in (
            {"entry_price": D("0")},
            {"stop_loss_percent": D("0")},
            {"stop_loss_percent": D("-1")},
            {"risk_base_capital": D("-1")},
            {"risk_percent": D("101")},
            {"entry_price": D("NaN")},
        ):
            with self.subTest(patch=patch):
                with self.assertRaises((TypeError, ValueError)):
                    sizing_input(**patch)


class RiskBudgetCalculatorTests(unittest.TestCase):
    def test_flat_budget_zero_under_and_over_limit(self):
        flat = calculate_risk_budget(D("1000"), D("1"), D("0"), D("0"))
        self.assertEqual(flat.risk_limit_amount, D("10"))
        self.assertEqual(flat.risk_budget_remaining, D("10"))
        self.assertEqual(flat.risk_utilization, D("0"))

        used = calculate_risk_budget(D("1000"), D("1"), D("4"), D("1"))
        self.assertEqual(used.risk_budget_remaining, D("5"))
        self.assertEqual(used.risk_utilization, D("50"))

        over = calculate_risk_budget(D("1000"), D("1"), D("12"), D("1"))
        self.assertEqual(over.risk_budget_remaining, D("0"))
        self.assertEqual(over.risk_utilization, D("130"))

    def test_unknown_authority_remains_null_with_diagnostics(self):
        value = calculate_risk_budget(D("1000"), D("1"), None, None)
        self.assertIsNone(value.risk_utilization)
        self.assertIsNone(value.risk_budget_remaining)
        self.assertIn("CURRENT_POSITION_RISK_UNAVAILABLE", value.diagnostics)
        self.assertIn("RESERVED_RISK_UNAVAILABLE", value.diagnostics)
        self.assertIn("RISK_UTILIZATION_UNAVAILABLE", value.diagnostics)


if __name__ == "__main__":
    unittest.main()
