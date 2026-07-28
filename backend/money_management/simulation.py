"""Deterministic, side-effect-free Money Management scenario simulation."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Optional, Tuple

from .position_risk import PositionSizingInput, calculate_position_size


MAX_SIMULATION_TRADES = 1000
PROJECTION_SCHEMA_VERSION = "money-management-simulation/v1"


class SimulationScenario(str, Enum):
    EXPECTED_SEQUENCE = "EXPECTED_SEQUENCE"
    WORST_LOSS_STREAK = "WORST_LOSS_STREAK"
    ALL_WINS = "ALL_WINS"
    ALL_LOSSES = "ALL_LOSSES"
    ALTERNATING = "ALTERNATING"
    CUSTOM_SEQUENCE = "CUSTOM_SEQUENCE"


def _decimal(name, value, *, positive=False, nonnegative=False, maximum=None):
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} exceeds maximum")
    return value


@dataclass(frozen=True)
class MoneyManagementSimulationInput:
    initial_capital: Decimal
    number_of_trades: int
    win_rate_percent: Decimal
    average_win_percent: Decimal
    average_loss_percent: Decimal
    risk_per_trade_percent: Decimal
    maximum_drawdown_percent: Decimal
    compounding_enabled: bool
    fees_percent: Decimal
    slippage_percent: Decimal
    maximum_position_notional: Decimal
    total_exposure_percent: Decimal
    single_symbol_exposure_percent: Decimal
    scenario: SimulationScenario
    custom_sequence: Tuple[str, ...] = ()

    def __post_init__(self):
        _decimal("initial_capital", self.initial_capital, positive=True)
        if type(self.number_of_trades) is not int or self.number_of_trades <= 0:
            raise ValueError("number_of_trades must be positive")
        if self.number_of_trades > MAX_SIMULATION_TRADES:
            raise ValueError("number_of_trades exceeds maximum")
        for name in ("win_rate_percent", "average_win_percent"):
            _decimal(name, getattr(self, name), nonnegative=True, maximum=Decimal("100"))
        _decimal("average_loss_percent", self.average_loss_percent, positive=True, maximum=Decimal("100"))
        _decimal("risk_per_trade_percent", self.risk_per_trade_percent, positive=True, maximum=Decimal("1"))
        _decimal("maximum_drawdown_percent", self.maximum_drawdown_percent, positive=True, maximum=Decimal("100"))
        for name in ("fees_percent", "slippage_percent"):
            _decimal(name, getattr(self, name), nonnegative=True, maximum=Decimal("100"))
        _decimal("maximum_position_notional", self.maximum_position_notional, positive=True)
        for name in ("total_exposure_percent", "single_symbol_exposure_percent"):
            _decimal(name, getattr(self, name), positive=True, maximum=Decimal("100"))
        if self.single_symbol_exposure_percent > self.total_exposure_percent:
            raise ValueError("single symbol exposure exceeds total")
        if type(self.compounding_enabled) is not bool:
            raise TypeError("compounding_enabled must be bool")
        object.__setattr__(self, "scenario", SimulationScenario(self.scenario))
        if self.scenario is SimulationScenario.CUSTOM_SEQUENCE:
            if len(self.custom_sequence) != self.number_of_trades:
                raise ValueError("custom sequence length mismatch")
            if any(item not in ("WIN", "LOSS") for item in self.custom_sequence):
                raise ValueError("custom sequence entries invalid")


@dataclass(frozen=True)
class MoneyManagementProjectionPoint:
    trade_number: int
    capital: Decimal
    peak_capital: Decimal
    drawdown_amount: Decimal
    drawdown_percent: Decimal
    risk_amount: Decimal
    position_notional: Optional[Decimal]
    trade_result: Decimal
    cumulative_profit_loss: Decimal
    status: str

    def to_dict(self):
        return {
            "tradeNumber": self.trade_number,
            "capital": format(self.capital, "f"),
            "peakCapital": format(self.peak_capital, "f"),
            "drawdownAmount": format(self.drawdown_amount, "f"),
            "drawdownPercent": format(self.drawdown_percent, "f"),
            "riskAmount": format(self.risk_amount, "f"),
            "positionNotional": (
                format(self.position_notional, "f")
                if self.position_notional is not None else None
            ),
            "tradeResult": format(self.trade_result, "f"),
            "cumulativeProfitLoss": format(
                self.cumulative_profit_loss, "f"
            ),
            "status": self.status,
        }


@dataclass(frozen=True)
class MoneyManagementSimulationResult:
    summary: dict
    projection: Tuple[MoneyManagementProjectionPoint, ...]
    diagnostics: Tuple[str, ...]
    calculation_allowed: bool

    def to_dict(self):
        return {
            "schemaVersion": PROJECTION_SCHEMA_VERSION,
            "summary": self.summary,
            "projection": [point.to_dict() for point in self.projection],
            "diagnostics": list(self.diagnostics),
            "calculationAllowed": self.calculation_allowed,
        }


def _outcomes(value):
    count = value.number_of_trades
    if value.scenario is SimulationScenario.ALL_WINS:
        return ("WIN",) * count
    if value.scenario is SimulationScenario.ALL_LOSSES:
        return ("LOSS",) * count
    if value.scenario is SimulationScenario.ALTERNATING:
        return tuple("WIN" if index % 2 == 0 else "LOSS" for index in range(count))
    if value.scenario is SimulationScenario.CUSTOM_SEQUENCE:
        return value.custom_sequence
    wins = int(
        (Decimal(count) * value.win_rate_percent / Decimal("100"))
        .to_integral_value(rounding=ROUND_DOWN)
    )
    if value.scenario is SimulationScenario.WORST_LOSS_STREAK:
        return ("WIN",) * wins + ("LOSS",) * (count - wins)
    accumulator = Decimal("0")
    outcomes = []
    for _ in range(count):
        accumulator += value.win_rate_percent
        if accumulator >= 100:
            outcomes.append("WIN")
            accumulator -= 100
        else:
            outcomes.append("LOSS")
    return tuple(outcomes)


def _streaks(outcomes):
    largest_win = largest_loss = current_win = current_loss = 0
    for outcome in outcomes:
        if outcome == "WIN":
            current_win += 1
            current_loss = 0
            largest_win = max(largest_win, current_win)
        else:
            current_loss += 1
            current_win = 0
            largest_loss = max(largest_loss, current_loss)
    return largest_win, largest_loss


def run_simulation(value):
    if not isinstance(value, MoneyManagementSimulationInput):
        raise TypeError("MoneyManagementSimulationInput required")
    capital = peak = minimum = value.initial_capital
    fixed_base = value.initial_capital
    projection = []
    diagnostics = []
    position_sizes = []
    completed_outcomes = []
    max_drawdown_amount = max_drawdown_percent = Decimal("0")
    effective_cost_percent = value.fees_percent + value.slippage_percent
    reward_multiple = value.average_win_percent / value.average_loss_percent
    lock_reached = ruin_reached = False

    for number, outcome in enumerate(_outcomes(value), start=1):
        risk_base = capital if value.compounding_enabled else fixed_base
        risk_amount = risk_base * value.risk_per_trade_percent / Decimal("100")
        total_limit = capital * value.total_exposure_percent / Decimal("100")
        symbol_limit = capital * value.single_symbol_exposure_percent / Decimal("100")
        sizing = calculate_position_size(PositionSizingInput(
            entry_price=Decimal("1"),
            stop_loss_percent=value.average_loss_percent,
            effective_cost_percent=effective_cost_percent,
            risk_percent=value.risk_per_trade_percent,
            risk_base_capital=risk_base,
            maximum_position_notional=value.maximum_position_notional,
            total_exposure_remaining=min(total_limit, symbol_limit),
            available_capital=max(capital, Decimal("0")),
            quantity_step=Decimal("0.00000001"),
            contract_multiplier=Decimal("1"),
            risk_budget_remaining=risk_amount,
        ))
        position_notional = (
            sizing.final_position_notional
            if sizing.calculation_allowed else None
        )
        if position_notional is None:
            diagnostics.append("POSITION_SIZE_UNAVAILABLE")
            break
        position_sizes.append(position_notional)
        cost = position_notional * effective_cost_percent / Decimal("100")
        gross = (
            risk_amount * reward_multiple
            if outcome == "WIN" else -risk_amount
        )
        previous_capital = capital
        trade_result = gross - cost
        capital += trade_result
        depleted = capital <= 0
        if depleted:
            capital = Decimal("0")
            trade_result = capital - previous_capital
        completed_outcomes.append(outcome)
        if capital > peak:
            peak = capital
        minimum = min(minimum, capital)
        drawdown_amount = max(peak - capital, Decimal("0"))
        drawdown_percent = (
            drawdown_amount / peak * Decimal("100")
            if peak > 0 else Decimal("100")
        )
        max_drawdown_amount = max(max_drawdown_amount, drawdown_amount)
        max_drawdown_percent = max(max_drawdown_percent, drawdown_percent)
        status = "NORMAL"
        if depleted:
            status = "RUINED"
            ruin_reached = True
            diagnostics.append("CAPITAL_DEPLETED")
        elif drawdown_percent >= value.maximum_drawdown_percent:
            status = "LOCKED"
            lock_reached = True
            diagnostics.extend((
                "MAXIMUM_DRAWDOWN_REACHED",
                "MONEY_MANAGEMENT_LOCK_REACHED",
            ))
        projection.append(MoneyManagementProjectionPoint(
            number,
            capital,
            peak,
            drawdown_amount,
            drawdown_percent,
            risk_amount,
            position_notional,
            trade_result,
            capital - value.initial_capital,
            status,
        ))
        if ruin_reached or lock_reached:
            break

    wins = completed_outcomes.count("WIN")
    losses = completed_outcomes.count("LOSS")
    largest_win, largest_loss = _streaks(completed_outcomes)
    net = capital - value.initial_capital
    return_percent = net / value.initial_capital * Decimal("100")
    loss_fraction = (peak - capital) / peak if peak > 0 else Decimal("1")
    recovery = (
        loss_fraction / (Decimal("1") - loss_fraction) * Decimal("100")
        if loss_fraction < 1 else None
    )
    if recovery is None:
        diagnostics.append("RECOVERY_UNDEFINED")
    average_position = (
        sum(position_sizes, Decimal("0")) / len(position_sizes)
        if position_sizes else None
    )
    summary = {
        "initialCapital": format(value.initial_capital, "f"),
        "finalCapital": format(capital, "f"),
        "netProfitLoss": format(net, "f"),
        "returnPercent": format(return_percent, "f"),
        "peakCapital": format(peak, "f"),
        "maximumDrawdownAmount": format(max_drawdown_amount, "f"),
        "maximumDrawdownPercent": format(max_drawdown_percent, "f"),
        "largestLossStreak": largest_loss,
        "largestWinStreak": largest_win,
        "wins": wins,
        "losses": losses,
        "breakEvenTrades": len(completed_outcomes) - wins - losses,
        "averagePositionNotional": (
            format(average_position, "f")
            if average_position is not None else None
        ),
        "maximumPositionNotionalUsed": (
            format(max(position_sizes), "f") if position_sizes else None
        ),
        "minimumCapital": format(minimum, "f"),
        "recoveryRequiredPercent": (
            format(recovery, "f") if recovery is not None else None
        ),
        "ruinReached": ruin_reached,
        "lockReached": lock_reached,
        "tradesCompleted": len(projection),
    }
    return MoneyManagementSimulationResult(
        summary,
        tuple(projection),
        tuple(dict.fromkeys(diagnostics)),
        bool(projection),
    )
