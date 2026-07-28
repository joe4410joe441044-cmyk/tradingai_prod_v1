# TradingAI Money Management Master Specification v1.1
## Proposed Additions

This document defines additions to the existing
`01_Money_Management_Master_Specification.md`.

---

# New Chapter : Professional Workflow

Money Management is not merely a settings screen.

It is a guided workflow that teaches the operator the same sequence used by
professional traders and fund managers.

Every configuration page shall follow the workflow below.

1. Capital
2. Risk Policy
3. Portfolio Allocation
4. Bot Allocation
5. Position Sizing
6. Capital Protection
7. Trading Cost Analysis
8. Simulation
9. Apply

---

# New Chapter : Guided Learning UI

Every configurable item shall contain an explanation panel.

The UI shall explain:

- Why this setting exists.
- Why a professional trader changes it.
- Advantages.
- Risks.
- Typical use cases.
- Expected effects.
- Situations where the value should be avoided.
- Relationships with other settings.

The operator should understand the setting before applying it.

---

## Example

### Position Risk

Explanation

Why choose 0.5% instead of 2%?

Possible effects:

- Smaller drawdown
- Slower account growth
- Higher survivability

Changing this value affects:

- Position Size
- Maximum Drawdown
- Recovery Time
- Compound Growth

---

# Dashboard Integration

Dashboard displays:

- Current Capital
- Current Exposure
- Active Risk
- Portfolio Summary
- Bot Status

Money Management modifies these values and immediately reflects them back to Dashboard.

---

# Multi-Bot Architecture

Future architecture:

Portfolio
├── Bot 1
├── Bot 2
└── Bot N

Money Management operates at Portfolio level first,
then Bot Allocation level,
then Position level.

Current implementation supports a single bot.

---

# Trading Cost Analysis

Include:

- Entry Fee
- Exit Fee
- Spread
- Slippage
- Funding
- Estimated Net Profit
- Cost Efficiency

Simulation shall include all trading costs.

---

# AI Advisor

AI provides recommendations only.

It never changes settings automatically.

Example:

Current drawdown is elevated.

Recommendation:

Reduce position risk from 1.0% to 0.6%.

Reason:

Improves long-term capital preservation while reducing expected volatility.

---

# Design Principle

Every screen should answer four questions before the user presses Apply.

1. What does this setting do?
2. Why should I change it?
3. What could happen if I increase or decrease it?
4. How will it affect my long-term performance?

Only after these questions are answered should configuration be applied.

This educational approach is a core design philosophy of TradingAI Money Management.


---

# Approved Numeric Decision Baseline (D01--D28)

This section is normative. It supersedes any conflicting proposed, legacy, or default value in this document. No runtime implementation is created here.

## Operating Profile

| Field | Approved value |
| --- | --- |
| Profile | CAPITAL_PROTECTION_STANDARD |
| Mode | Paper |
| Exchange | KuCoin Futures |
| Primary symbol | XRPUSDTM |
| Initial Reference Equity | 1,000 USDT; reference only, not a fixed live configuration |
| Multi-Bot | Disabled / Not Permitted |

## D01--D06: Risk, Position, Exposure, and Leverage

| ID | Approved decision |
| --- | --- |
| D01 | Risk per trade is 0.50% of current eligible equity. Hard maximum is 1.00%. `riskAmount = eligibleEquity * 0.005`. Leverage never increases riskAmount. |
| D02 | Maximum position is 100 USDT notional for one logical position. |
| D03 | Maximum account drawdown is 5.00% from Account High-Water Mark Equity. Scope is account. Breach is `LOCKED`; no new trade and approvedSize is 0. |
| D04 | Maximum total exposure is 20% of eligible equity (200 USDT at reference equity). |
| D05 | Maximum single-symbol exposure is 10% of eligible equity (100 USDT at reference equity). |
| D06 | Maximum leverage is 5x per position. It is a hard limit and margin-only; it does not increase risk amount or maximum position. |

## D07--D13: Period Loss Controls

| ID | Approved decision |
| --- | --- |
| D07 | Daily loss warning: 1.00%; state CAUTION; risk multiplier ceiling 0.75. |
| D08 | Daily loss block: 1.50%; `RISK_BLOCKED`; no new trade. UTC reset applies only when no active lock and Governance conditions permit. |
| D09 | Weekly loss warning: 2.00%; CAUTION or DEFENSIVE; multiplier ceiling 0.50. |
| D10 | Weekly loss block: 3.00%; `RISK_BLOCKED`. |
| D11 | Monthly loss warning: 3.00%; DEFENSIVE; multiplier ceiling 0.50. |
| D12 | Monthly loss block: 4.00%; `RISK_BLOCKED`. |
| D13 | Boundaries are daily 00:00 UTC, weekly Monday 00:00 UTC, monthly day 1 00:00 UTC. Period loss uses period-start eligible equity. Account-HWM drawdown is separate and never resets by a period boundary. |

## D14--D16: Profit Protection

Profit Lock starts at +1.00% daily realized net profit after fees, spread, slippage, and funding. Track daily peak net profit.

| Tier | Daily net profit | Maximum giveback from peak | Risk multiplier ceiling |
| --- | ---: | ---: | ---: |
| 0 | < 1% | none | 1.00 |
| 1 | >= 1% | 50% | 0.90 |
| 2 | >= 2% | 35% | 0.75 |
| 3 | >= 3% | 25% | 0.50 |
| 4 | >= 5% | 20% | 0.25 |

`protectedProfitFloor = dailyPeakNetProfit * (1 - givebackFraction)`. Profit Lock normally scales risk and does not itself hard-block. A giveback-floor breach blocks new trades for the rest of the UTC day as Profit Protection Block.

## D17--D18: Risk of Ruin

Risk of Ruin is the probability of reaching the configured Maximum Drawdown (5.00%). LOW is 0% <= p < 5%; MODERATE is 5% <= p < 10% and warns; HIGH is 10% <= p < 20% with multiplier ceiling 0.50; CRITICAL is p >= 20% and returns `RISK_BLOCKED`. `INSUFFICIENT_DATA` warns only unless another hard block exists.

## Position Sizing Formula

```text
eligibleEquity = validated current equity
riskAmount = eligibleEquity * riskPerTradeFraction
stopLossFraction = abs(entryPrice - stopPrice) / entryPrice
baseCostFraction = roundTripFee + spread + entrySlippage + exitSlippage + expectedFunding
effectiveCostFraction = baseCostFraction * 1.20
effectiveRiskFraction = stopLossFraction + effectiveCostFraction
rawNotional = riskAmount / effectiveRiskFraction
rawQuantity = rawNotional / entryPrice
approvedNotional = min(rawNotional, requestedNotional, maximumPositionNotional,
  availableSingleSymbolExposure, availableTotalExposure, liquidityAdjustedLimit,
  governanceLimit)
approvedQuantity = roundDownToQuantityStep(approvedNotional / entryPrice)
requiredMargin = approvedNotional / leverage
```

Invalid/missing equity, entry, stop, cost assumption, effective fraction, quantity step, minimum-order compliance, or any hard-limit breach produces zero approved size. Missing runtime data produces `INSUFFICIENT_DATA`.

### Runtime risk budget and read-only preview

The authoritative risk base is current `available_balance`; unknown capital
must not fall back to equity. The active `risk_per_trade_pct` defines
`riskLimitAmount = available_balance * risk_per_trade_pct / 100`.
`totalUsedRisk = currentRiskAmount + reservedRiskAmount`,
`riskBudgetRemaining = max(riskLimitAmount - totalUsedRisk, 0)`, and
`riskUtilization = totalUsedRisk / riskLimitAmount * 100`.

An empty position/order set authoritatively contributes zero. An open position
without its protective stop, or pending orders without reserved-risk data,
produce null current/reserved risk and explicit diagnostics; exposure or margin
must never substitute for risk.

`POST /api/money-management/position-size/preview` is a deterministic,
read-only calculation boundary. It requires explicit entry price, stop-loss
percent, effective round-trip cost percent, contract multiplier, quantity
step, and symbol. Risk
percent defaults to the active configuration and cannot exceed it. Final
notional is capped by maximum position notional, remaining total exposure,
available capital, and remaining risk budget. Quantity is rounded down to the
explicit exchange contract multiplier and quantity step. The preview never creates, reserves, or
submits an order. Runtime recommended size remains null when no authoritative
entry/stop candidate exists.

### Deterministic Simulation and Projection

`POST /api/money-management/simulation` is analysis-only. It does not update
configuration, runtime snapshots, risk reservations, positions, orders, or
runtime history. Supported scenarios are `EXPECTED_SEQUENCE`,
`WORST_LOSS_STREAK`, `ALL_WINS`, `ALL_LOSSES`, `ALTERNATING`, and explicit
`CUSTOM_SEQUENCE`. Expected wins use a deterministic percentage accumulator;
Monte Carlo and unseeded randomness are not used.

```text
riskBase = compounding ? currentCapital : initialCapital
riskAmount = riskBase * riskPerTradePercent / 100
rewardMultiple = averageWinPercent / averageLossPercent
grossWin = riskAmount * rewardMultiple
grossLoss = -riskAmount
positionNotional = existing Position Sizing Calculator result
cost = positionNotional * (feesPercent + slippagePercent) / 100
netTradeResult = grossResult - cost
```

`averageLossPercent` is the projected stop distance. Position sizing reuses the
active maximum-position, total-exposure, and single-symbol limits. Each point
contains trade number, capital, peak, drawdown, risk, position notional, net
result, cumulative P/L, and status. Maximum drawdown produces `LOCKED` and
stops later projected trades. Capital at or below zero is `RUINED`, distinct
from `LOCKED`.

```text
lossFraction = (peakCapital - finalCapital) / peakCapital
recoveryRequiredPercent = lossFraction / (1 - lossFraction) * 100
```

At complete loss recovery is null with `RECOVERY_UNDEFINED`. Requests are
limited to 1,000 trades. Capital and drawdown charts represent only returned
simulation projection, never runtime Timeline or a future guarantee.

### Durable Runtime Timeline and History

The Money Management Timeline records only confirmed Paper/Runtime changes.
Simulation projections and status reads never write Timeline events. Event
types cover application start, configuration and runtime metric updates, loss
and recovery state transitions, exposure/risk-budget/position changes,
lock/unlock, and diagnostic raised/cleared transitions.

Each immutable event contains a random opaque event ID, UTC timestamp,
monotonic sequence, type, source, current/previous state, priority-ordered
block/hold/warning reason codes, available metric snapshot, configuration
version, diagnostics, correlation ID, and a minimal change set. Unknown metrics
remain null. Consecutive events with equal normalized type, snapshot, reasons,
configuration version, and changes are not appended.

Runtime events are recorded only after an applied Loss Runtime Hook update.
Configuration events are recorded only after successful atomic configuration
replacement; recovery events require an actual state change. A GET status,
GET history, or Simulation request cannot generate an event.

The durable format is permission-restricted JSON Lines at
`logs/runtime/money_management_timeline.jsonl`. Writes use no-follow append,
flush, and fsync. Retention preserves the newest 5,000 events and rewrites
through an exclusive temporary file plus atomic replace. Startup restores the
latest retained events and deduplication state without regenerating them.
Malformed lines are skipped and counted while valid lines remain available.
Absolute directory validation, parent/target symlink rejection, strict event
shape, and a fixed filename prevent path traversal or credential capture.

`GET /api/money-management/history` is read-only. It returns newest-first
events with `limit` (default 100, maximum 500), opaque sequence cursor
pagination through `before`/`after`, and exact `eventType`/`state` filters.
Invalid cursors, filters, and limits are rejected. Empty history returns an
empty array. Frontend analysis charts use at most 500 fetched points and render
equity, drawdown, exposure utilization, and risk utilization with null values
as gaps. State-transition markers remain distinct from Simulation charts.

### Final integrated implementation and deployment boundary

The implemented HTTP surface is `GET /status`, `GET /configuration`,
`PUT /configuration`, `POST /recovery`, `POST /position-size/preview`,
`POST /simulation`, and `GET /history`, all below
`/api/money-management`. Decimal values remain strings, unavailable runtime
values remain null, and unsupported states fail closed as `UNKNOWN`.

`MoneyManagementConfigProvider` owns the application-scoped base
configuration; `LossLimitConfig` remains limited to loss thresholds.
`LossRuntimeMetrics` and authoritative position/order snapshots supply runtime
facts. Position sizing is deterministic and read-only. Simulation is a
separate hypothetical boundary and cannot mutate runtime or Timeline.
Timeline/history contains only confirmed runtime and configuration changes.

Protective-stop data and reserved-risk data are not currently guaranteed by
the runtime contract. When either authority is missing, current or reserved
risk, remaining budget, and utilization stay null as applicable, the UI shows
an em dash, and diagnostics describe the missing authority. Exposure or
position notional is never substituted. Future work must extend the
position/order runtime contracts; this implementation does not alter the
Execution Engine or order flow.

The Money Management page includes status, editable configuration with
revision control, recovery evaluation, position-size preview, deterministic
simulation, runtime Timeline/history, and four runtime charts. Loading, error,
empty, and unknown states use the shared TradingAI console design system.
Before production deployment, the frontend is built only to a temporary
directory and previewed on loopback; production `frontend/dist`, systemd,
Nginx, and running services remain unchanged.

### Runtime authority integration

Money Management consumes runtime observations through the scalar-only,
read-only boundary
`ExecutionEngine -> BotManager.get_runtime_metrics_snapshot() ->
BotManagerLossRuntimeMetricsSource`. It never retains an Execution object and
does not invoke order, strategy, emergency, or state-transition methods.

The account authority supplies balance, equity, available balance, realized
and unrealized PnL. The Bot Manager accumulator supplies UTC period PnL/trade
counts and high-water-mark drawdown. The Execution Engine's confirmed
`actual_position` supplies side, quantity, mark notional, entry price, and the
active `sl` value. A single BUY/LONG position maps to LONG and a single
SELL/SHORT position maps to SHORT; no position maps to FLAT. Multiple or
unrecognized confirmed positions map to OPEN, never to a guessed direction.

Current position risk is calculated only when the confirmed position has a
recognized side, positive entry price and quantity, and a positive protective
stop on the loss side of entry. It is the absolute entry-to-stop distance
multiplied by absolute coin quantity. Missing, malformed, or directionally
invalid stop data keeps current risk null.

Pending-order authority currently proves only whether a pending order exists.
No immutable pending-order quantity, entry, and protective-stop reservation
contract exists. Therefore no pending order proves reserved risk zero, while
an existing or unknown pending order keeps reserved risk null. Creating a
reserved-risk amount from the configured risk percentage or intended order
size is prohibited.

Runtime History records applied runtime observations and derives
POSITION_STATE_CHANGED, EXPOSURE_STATE_CHANGED, RISK_BUDGET_CHANGED,
LOSS_STATE_CHANGED, lock/unlock, and diagnostic transitions. Configuration
and recovery changes use their dedicated event types. Simulation and GET
requests never create history events.

Runtime activation remains an explicit operations decision through the
existing strict Money Management settings and persistence boundary. This
integration does not enable LIVE, start Paper execution, or change Execution,
Strategy, Emergency, or Simulation state.


## D19--D25: Consecutive Loss, Cooldown, and Recovery

D19: three consecutive net-loss trades (net of all costs) set DEFENSIVE, cap the risk multiplier at 0.50, and start a 30-minute cooldown. D20: four consecutive losses return RISK_BLOCKED with approvedSize 0 and a 12-hour cooldown. Abnormal loss velocity, liquidity deterioration, or execution-cost deterioration may also trigger the initial cooldown. A timer alone never releases Maximum Drawdown LOCKED.

D23 enters RECOVERY_25 only after at least 12 hours cooldown, user review, cause resolution, no active blocker, Governance permission, normal liquidity/slippage, and position/order reconciliation. Its multiplier is 0.25. D24 promotes to RECOVERY_50 (0.50) after three clean trades and recovery cumulative net PnL >= 0. D25 promotes to NORMAL after five additional clean trades (eight total), cumulative net PnL >= 0, normal liquidity/slippage, and no new limit. A hard-limit breach during recovery returns LOCKED.

A clean trade has no MM/Governance block or execution failure, no serious slippage, normal liquidity, loss within expected risk budget, and no position/order inconsistency.

## D26--D28

D26 cost buffer is actual estimated round-trip cost (entry/exit fees, spread, entry/exit slippage, expected funding) multiplied by 1.20. D27 Multi-Bot is Not Permitted. D28 Maximum Bot Allocation is N/A.

## Control Priority

1. Governance Block
2. Account Maximum Drawdown LOCKED
3. Period Loss Block
4. Exposure Block
5. Maximum Position Block
6. Maximum Leverage Block
7. Risk of Ruin CRITICAL Block
8. Consecutive Loss Block
9. Cooldown
10. Recovery Limit
11. Drawdown Risk Scaling
12. Profit Lock Risk Scaling
13. Consecutive Loss Warning Scaling
14. Risk of Ruin HIGH Scaling
15. Normal Position Sizing

## Hard and Soft Limits

Hard limits are Maximum Drawdown, Maximum Position, Total Exposure, Single-Symbol Exposure, Maximum Leverage, daily/weekly/monthly loss blocks, Risk of Ruin CRITICAL, consecutive-loss block, Governance block, and live explicit approval. A hard MM limit sets approvedSize 0, riskAllowed false, and RISK_BLOCKED; Governance returns GOVERNANCE_BLOCKED.

Soft limits are CAUTION, DEFENSIVE, drawdown scaling, profit-lock scaling, consecutive-loss warning, Risk of Ruin MODERATE/HIGH, initial cooldown, and recovery scaling.

## Decision States, Outputs, and Block Reasons

States: NORMAL, CAUTION, DEFENSIVE, LOCKED, RECOVERY_25, RECOVERY_50.

Outputs: decisionResult, approvedSize, approvedNotional, approvedQuantity, riskAllowed, riskBlockReason, riskState, riskMultiplier, drawdownState, profitProtectionState, periodLossState, exposureState, consecutiveLossState, cooldownState, recoveryState, riskOfRuinState, configurationVersion, and evaluatedAt. MM-1A must define whether approvedSize is quantity, notional, or a wrapper.

Block reasons: MAXIMUM_DRAWDOWN, DAILY_LOSS_LIMIT, WEEKLY_LOSS_LIMIT, MONTHLY_LOSS_LIMIT, MAXIMUM_POSITION, TOTAL_EXPOSURE_LIMIT, SYMBOL_EXPOSURE_LIMIT, MAXIMUM_LEVERAGE, RISK_OF_RUIN_CRITICAL, CONSECUTIVE_LOSS_LIMIT, COOLDOWN_ACTIVE, RECOVERY_LIMIT, INVALID_EQUITY, INVALID_ENTRY_PRICE, INVALID_STOP, INVALID_COST_ASSUMPTION, BELOW_MINIMUM_ORDER, INSUFFICIENT_DATA, PROFIT_PROTECTION_LIMIT.

## Configuration, Paper/Live, Runtime, and Persistence

Only Active configuration affects runtime. Draft supports validation, simulation, and impact preview. Apply records version, changed fields, previous/new value, actor, reason, timestamp, Paper/Live, validation, user confirmation, and Governance result.

Paper permits simulation, draft, validation, and impact preview; it never submits live orders. Live requires user confirmation for risk increases, Active Apply, and hard-limit override requests; Governance remains final and aggressive profile is initially prohibited.

Required runtime data includes equity, eligibleEquity, highWaterMark, requestedSize/requestedNotional, entryPrice, stopPrice, position/exposure values, realized/unrealized PnL, dailyPeakNetProfit, periodStartEquity, trade costs, loss/cooldown/recovery states, ruin state, liquidity/Governance limits, quantity step, and minimum order requirement.

Persist Active/Draft configuration and history; equity/HWM; period starts/counters; daily peak and protected floor; loss count; cooldown; recovery and clean-trade count; ruin assessment; latest decision and approved amounts; block reason; and state transitions.

## Validation and MM-1A Input Package

Validate daily warning < daily block; weekly warning < weekly block; monthly warning < monthly block; daily block < weekly block <= monthly block < maximum DD; maximum position <= symbol exposure <= total exposure; 0 < risk per trade <= 1%; 0 < leverage <= 5x Standard; profit thresholds strictly rise; giveback and multiplier ceilings decrease by tier; 0.25 < 0.50 < 1.00; approved amounts are non-negative and no greater than requested; MM never changes direction; leverage never raises risk amount; Governance is final.

MM-1A input package: typed models, enums, calculation inputs/outputs, units, precision, rounding, validation errors, block reasons, states, configuration fields, and persistence fields.
