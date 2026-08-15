# 02_AUTO_MONEY_MANAGEMENT_Specification

## Purpose
AUTO MONEY MANAGEMENT defines how TradingAI dynamically manages risk capacity, compounding, capital eligibility, and position sizing within explicit user-defined safety limits.

It answers:

> **Given current capital and risk policy, how much risk capacity may TradingAI safely use right now?**

## Core Principle

```text
USER POLICY
    ↓
AUTO MONEY MANAGEMENT
    ↓
RISK CAPACITY
    ↓
AUTO MARKET SELECTION
    ↓
TRADING DECISION
    ↓
FINAL POSITION SIZING
    ↓
RUIN / RISK GUARDS
    ↓
GOVERNANCE
    ↓
EXECUTION
```

Humans define the risk constitution.
Python performs deterministic optimization inside it.
AI may review but cannot expand it.
Governance remains final authority.

## Money Management Modes

```text
MANUAL
ASSISTED
AUTO
```

### MANUAL
Operator controls supported MM settings.

### ASSISTED
Python proposes values; operator confirms.

### AUTO
Python adjusts runtime risk capacity automatically within hard policy bounds.

## Human / Machine Boundary

Human-owned policy:
- Risk Profile
- Maximum Drawdown
- Maximum Total Exposure
- Maximum Acceptable Ruin Risk
- Compounding Allowed
- Maximum Live Leverage Policy
- Maximum Executable Position Safety Cap
- Emergency / Lock Rules

Python-owned runtime:
- MM Regime
- Current Risk Budget
- Recommended Risk per Trade
- Capital Eligibility
- Position Capacity
- Position Size
- Exposure allocation
- Compounding base
- Ruin Guard evaluation

AI cannot change user policy.

## Risk Profiles
Possible policy presets:

```text
PRESERVATION
BALANCED
GROWTH
CUSTOM
```

Each preset must map to explicit versioned numeric limits.

## MM Regimes
Recommended runtime states:

```text
NORMAL
CAUTION
DEFENSIVE
LOCKED
```

Regime changes must be deterministic, explainable, and logged.

## Authoritative Capital
Paper uses Paper Account authority.
Live uses Real Account authority.

If capital is unavailable:

```text
MM_CAPITAL_AUTHORITY_UNAVAILABLE
```

Do not guess.

## Compounding
If equity rises, future risk budgets may use the higher equity base.
If equity falls, future sizing must shrink accordingly.

Compounding remains bounded by:
- user policy
- drawdown rules
- exposure limits
- Ruin Guard
- Governance

## Dynamic Risk Budget
Potential inputs:
- equity
- available capital
- drawdown
- realized PnL
- loss streak
- win rate
- payoff ratio
- strategy quality
- current exposure
- market volatility
- MM regime
- user policy

The calculation must be deterministic and versioned.

## Position Capacity
AUTO MM may calculate:

```text
theoreticalMaxConcurrentPositions
remainingPositionCapacity
```

using capital, risk budget, exposure, current positions, and minimum feasible position sizes.

### v1 Safety Rule

```text
Executable Concurrent Position Limit = 1
```

even if theoretical capacity is higher.

The theoretical result should still be recorded for later validation.

## Capital Eligibility Contract
AUTO MM publishes a shared contract for AUTO MARKET SELECTION:

```text
capitalAuthority
equity
availableCapital
mmMode
mmRegime
riskBudget
maxPositionNotional
maxTotalExposure
remainingExposure
theoreticalMaxConcurrentPositions
executableMaxConcurrentPositions
remainingPositionCapacity
ruinGuardStatus
compoundingEnabled
policyVersion
evaluatedAt
```

AUTO MARKET SELECTION consumes this instead of duplicating MM calculations.

## Per-Market Capital Eligibility
For each candidate market, evaluate authoritative constraints such as:
- min contract
- min notional
- quantity step
- contract multiplier
- fees
- slippage
- margin requirement
- risk budget feasibility
- available capital
- exposure capacity
- position capacity

## Final Position Sizing
Pre-selection eligibility is not final sizing.

Final sizing occurs after:
- Active Symbol selection
- fresh market data
- Strategy candidate
- entry / stop context where required

Use existing authoritative MM sizing logic wherever possible.

Concept:

```text
Available Capital
× Risk %
→ Risk Amount

Risk Amount
÷ Effective Risk per Unit
→ Raw Position Size

Apply caps:
Max Position Notional
Exposure Remaining
Available Capital
Risk Budget Remaining
Contract Multiplier
Quantity Step
Fees / Slippage

→ Approved Quantity
```

## Balsara / Risk of Ruin Guard
Risk of Ruin is a Guard, not a direct sizing authority.

```text
Proposed Size
    ↓
Ruin Evaluation
    ↓
PASS
or
REDUCE
or
BLOCK
```

If size cannot be reduced to a safe level:

```text
SKIP TRADE
```

The exact model must be explicit, testable, and versioned.

## Ruin Guard Inputs
Possible inputs:
- estimated win probability
- payoff ratio
- fraction of capital at risk
- current drawdown
- equity
- strategy sample size
- estimation confidence

If inputs are statistically insufficient:

```text
RUIN_ESTIMATE_INSUFFICIENT_DATA
```

Do not fabricate precision.

## Kelly / Fractional Kelly
Kelly may be an optional sizing reference.

Recommended form:

```text
Kelly Estimate
    ↓
Fractional Kelly
    ↓
Policy Cap
    ↓
Drawdown Adjustment
    ↓
Ruin Guard
    ↓
Final MM Bound
```

Full Kelly should not automatically become production risk.

## Estimation Uncertainty
Track:
- sample size
- data window
- strategy version
- estimate confidence
- market regime

High uncertainty should reduce aggressiveness, not increase it.

## Drawdown Protection

```text
Low Drawdown → NORMAL
Moderate Drawdown → CAUTION
High Drawdown → DEFENSIVE
Critical Drawdown → LOCKED
```

Exact thresholds belong to user policy.

## Performance Degradation
AUTO MM may reduce risk due to:
- loss streak
- deteriorating win rate
- worsening payoff
- increasing realized drawdown
- unstable strategy quality

Do not mechanically increase risk because of a short winning streak.

## Growth vs Preservation
AUTO MM must balance:
- survival
- capital preservation
- compounding
- short-term Micro Edge profit accumulation

## AI Role
Python owns:
- calculations
- thresholds
- sizing
- ruin evaluation
- exposure
- compounding
- regime determination

AI may review:

```text
Python MM Proposal
    ↓
AI Review
    ↓
AGREE
or
DOWNGRADE / WARNING
```

AI must not:
- raise risk above policy/Python limits
- increase exposure caps
- override drawdown lock
- override Ruin Guard
- override LOCKED
- enable Live
- freely raise leverage

## Governance Boundary
Governance remains above MM.

```text
AUTO MM PASS
```

can still become:

```text
GOVERNANCE BLOCK
```

MM can never convert a block into permission.

## Runtime Contract
Suggested structure:

```text
autoMoneyManagement
  available
  mode
  regime
  capitalAuthority
  equity
  availableCapital
  compoundingEnabled
  riskBudget
  positionCapacity
  exposure
  ruinGuard
  sizingMethod
  policyVersion
  evaluatedAt
```

Unavailable values remain null/unknown, never invented.

## Dashboard
Add:

```text
AUTO MONEY MANAGEMENT（自動資金管理）
```

Recommended order:

```text
OPERATION
ACCOUNT
AUTO MONEY MANAGEMENT
AUTO MARKET SELECTION
TRADING DECISION
RUNTIME & DIAGNOSTICS
```

Suggested fields:
- Mode
- Capital Authority
- Equity
- Available Capital
- Regime
- Compounding
- Risk Budget
- Ruin Guard
- Theoretical Position Capacity
- Executable Position Capacity
- Current Positions
- Exposure
- Sizing Method
- Reason

## Operator Policy UI
AUTO mode should emphasize policy rather than requiring constant low-level tuning.

Possible fields:
- Risk Profile
- Maximum Drawdown
- Maximum Exposure
- Maximum Acceptable Ruin Risk
- Compounding ON/OFF
- Maximum Executable Position Safety Cap
- Live Safety Policy

Advanced settings may remain under Expert / Manual.

## Audit Trail
Record every meaningful AUTO MM decision:

```text
AUTO_MM_DECISION
timestamp
capitalAuthority
equity
availableCapital
previousRegime
newRegime
previousRiskBudget
newRiskBudget
compoundingState
ruinGuardStatus
theoreticalPositionCapacity
executablePositionCapacity
reasonCodes
policyVersion
strategyVersion
```

## Reason Codes
Possible categories:
- EQUITY_INCREASED
- EQUITY_DECREASED
- DRAWDOWN_INCREASED
- DRAWDOWN_RECOVERED
- LOSS_STREAK
- PAYOFF_DETERIORATED
- ESTIMATE_UNCERTAIN
- CAPITAL_SMALL
- EXPOSURE_LIMIT
- RUIN_RISK_HIGH
- REGIME_CAUTION
- REGIME_DEFENSIVE
- REGIME_LOCKED
- POLICY_CAP

## Recorder / Replay

```text
Account Capital
    ↓
User Policy
    ↓
MM Regime
    ↓
Risk Budget
    ↓
Position Capacity
    ↓
Capital Eligibility
    ↓
Market Selection
    ↓
Strategy
    ↓
Final Position Sizing
    ↓
Ruin Guard
    ↓
Governance
    ↓
Execution
```

Replay must answer why a quantity was permitted, reduced, or rejected.

## Paper / Live
Logic is shared.
Only capital authority differs.
Live activation remains a separate explicit safety decision.

## Safety Rules
AUTO MM must never:
- exceed user policy
- bypass Governance/Emergency
- enable Live
- modify realOrderAllowed
- fabricate capital/statistical confidence
- increase leverage without policy
- ignore drawdown lock
- ignore exposure limits
- send orders itself

## Failure Modes
- `MM_CAPITAL_AUTHORITY_UNAVAILABLE`
- `MM_POLICY_UNAVAILABLE`
- `RUIN_ESTIMATE_INSUFFICIENT_DATA`
- position-size input incomplete
- `MM_LOCKED`

All fail safely.

## v1 Scope
- MANUAL / ASSISTED / AUTO
- User Risk Policy
- Authoritative Capital
- MM Regime
- Compounding
- Dynamic Risk Budget
- Theoretical Position Capacity
- Executable v1 Position Cap = 1
- Capital Eligibility
- Final Position Sizing integration
- Ruin Guard foundation
- Audit trail
- Dashboard
- Recorder / Replay
- Paper-first validation

## Out of Scope v1
- multiple simultaneous executable positions
- portfolio correlation optimization
- AI-primary sizing
- AI ability to increase risk
- unrestricted auto leverage
- automatic Live activation
- cross-exchange capital allocation

## Recommended Implementation Order

```text
MM-AUTO-0A Existing MM Authority Audit
MM-AUTO-0B User Policy Contract
MM-AUTO-0C Runtime Data / Statistics Audit
MM-AUTO-1A AUTO MM Decision Contract
MM-AUTO-1B Regime / Risk Budget Engine
MM-AUTO-1C Compounding Integration
MM-AUTO-1D Position Capacity
MM-AUTO-1E Ruin Guard Foundation
MM-AUTO-1F Optional Fractional Kelly Adapter
MM-AUTO-2A Capital Eligibility Interface
MM-AUTO-2B Final Position Sizing Integration
MM-AUTO-2C Audit Trail
MM-AUTO-2D Dashboard AUTO MM Card
MM-AUTO-3A Recorder Integration
MM-AUTO-3B Replay Integration
MM-AUTO-4A Paper End-to-End
MM-AUTO-4B Long-Run Paper Validation
MM-AUTO-5A Live Read Only
MM-AUTO-5B Explicitly Approved Live Activation
```

## Final Responsibility Boundary

```text
USER
How much risk am I willing to accept?

AUTO MONEY MANAGEMENT
How much risk capacity is safe now?

AUTO MARKET SELECTION
What market fits that capacity?

TRADING DECISION
Should we trade now?

FINAL MONEY MANAGEMENT
What exact quantity is allowed?

GOVERNANCE
May execution proceed?

EXECUTION
Send / Fill / Position
```

> **Humans define the risk constitution. Python dynamically optimizes within it. AI may review but cannot expand it. Governance remains the final safety authority.**
