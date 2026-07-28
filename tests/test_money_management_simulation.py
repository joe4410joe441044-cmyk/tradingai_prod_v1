import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal

from backend.money_management.simulation import (
    MAX_SIMULATION_TRADES,
    MoneyManagementSimulationInput,
    SimulationScenario,
    run_simulation,
)


D = Decimal


def simulation_input(**overrides):
    values = {
        "initial_capital": D("1000"),
        "number_of_trades": 10,
        "win_rate_percent": D("50"),
        "average_win_percent": D("1.50"),
        "average_loss_percent": D("1.00"),
        "risk_per_trade_percent": D("0.50"),
        "maximum_drawdown_percent": D("20"),
        "compounding_enabled": True,
        "fees_percent": D("0.06"),
        "slippage_percent": D("0.02"),
        "maximum_position_notional": D("100"),
        "total_exposure_percent": D("20"),
        "single_symbol_exposure_percent": D("10"),
        "scenario": SimulationScenario.EXPECTED_SEQUENCE,
    }
    values.update(overrides)
    return MoneyManagementSimulationInput(**values)


class MoneyManagementSimulationTests(unittest.TestCase):
    def test_expected_sequence_is_deterministic_and_serializable(self):
        value = simulation_input()
        first = run_simulation(value)
        second = run_simulation(value)

        self.assertEqual(first, second)
        self.assertEqual(first.summary["wins"], 5)
        self.assertEqual(first.summary["losses"], 5)
        self.assertEqual(len(first.projection), 10)
        self.assertEqual(
            [point.trade_number for point in first.projection],
            list(range(1, 11)),
        )
        self.assertEqual(
            first.to_dict()["schemaVersion"],
            "money-management-simulation/v1",
        )
        with self.assertRaises(FrozenInstanceError):
            value.initial_capital = D("1")

    def test_all_wins_all_losses_alternating_and_custom(self):
        wins = run_simulation(simulation_input(
            scenario=SimulationScenario.ALL_WINS,
        ))
        losses = run_simulation(simulation_input(
            scenario=SimulationScenario.ALL_LOSSES,
        ))
        alternating = run_simulation(simulation_input(
            scenario=SimulationScenario.ALTERNATING,
        ))
        custom = run_simulation(simulation_input(
            number_of_trades=4,
            scenario=SimulationScenario.CUSTOM_SEQUENCE,
            custom_sequence=("WIN", "LOSS", "LOSS", "WIN"),
        ))

        self.assertGreater(D(wins.summary["finalCapital"]), D("1000"))
        self.assertLess(D(losses.summary["finalCapital"]), D("1000"))
        self.assertEqual(alternating.summary["wins"], 5)
        self.assertEqual(custom.summary["largestLossStreak"], 2)

    def test_compounding_costs_and_fixed_base_change_results(self):
        compounded = run_simulation(simulation_input(
            scenario=SimulationScenario.ALL_WINS,
            fees_percent=D("0"),
            slippage_percent=D("0"),
        ))
        fixed = run_simulation(simulation_input(
            scenario=SimulationScenario.ALL_WINS,
            compounding_enabled=False,
            fees_percent=D("0"),
            slippage_percent=D("0"),
        ))
        costly = run_simulation(simulation_input(
            scenario=SimulationScenario.ALL_WINS,
            fees_percent=D("0.50"),
            slippage_percent=D("0.50"),
        ))

        self.assertNotEqual(
            compounded.summary["finalCapital"],
            fixed.summary["finalCapital"],
        )
        self.assertLess(
            D(costly.summary["finalCapital"]),
            D(compounded.summary["finalCapital"]),
        )

    def test_drawdown_lock_and_recovery_are_explicit(self):
        result = run_simulation(simulation_input(
            scenario=SimulationScenario.ALL_LOSSES,
            maximum_drawdown_percent=D("1"),
        ))

        self.assertTrue(result.summary["lockReached"])
        self.assertFalse(result.summary["ruinReached"])
        self.assertGreater(
            D(result.summary["recoveryRequiredPercent"]), D("0")
        )
        self.assertIn("MAXIMUM_DRAWDOWN_REACHED", result.diagnostics)
        self.assertEqual(result.projection[-1].status, "LOCKED")

    def test_capital_depletion_is_ruined_not_locked(self):
        result = run_simulation(simulation_input(
            initial_capital=D("1"),
            number_of_trades=1000,
            scenario=SimulationScenario.ALL_LOSSES,
            compounding_enabled=False,
            fees_percent=D("100"),
            slippage_percent=D("0"),
            maximum_drawdown_percent=D("100"),
        ))

        self.assertTrue(result.summary["ruinReached"])
        self.assertFalse(result.summary["lockReached"])
        self.assertIsNone(result.summary["recoveryRequiredPercent"])
        self.assertEqual(result.projection[-1].status, "RUINED")
        self.assertIn("CAPITAL_DEPLETED", result.diagnostics)
        self.assertIn("RECOVERY_UNDEFINED", result.diagnostics)

    def test_validation_rejects_unsafe_or_unbounded_inputs(self):
        cases = (
            {"initial_capital": D("0")},
            {"number_of_trades": 0},
            {"number_of_trades": MAX_SIMULATION_TRADES + 1},
            {"win_rate_percent": D("101")},
            {"average_loss_percent": D("0")},
            {"risk_per_trade_percent": D("1.01")},
            {"fees_percent": D("NaN")},
            {"scenario": "UNSUPPORTED"},
        )
        for patch in cases:
            with self.subTest(patch=patch):
                with self.assertRaises((TypeError, ValueError)):
                    simulation_input(**patch)


if __name__ == "__main__":
    unittest.main()
