# 01_AUTO_MARKET_SELECTION_Specification

## Purpose
AUTO MARKET SELECTION defines how TradingAI automatically chooses the most suitable crypto futures market while preserving MANUAL selection for testing and research.

It answers:

> **What market should TradingAI trade right now?**

It does not decide BUY/SELL/HOLD, final quantity, execution authorization, or order submission.

## Core Flow

```text
USER POLICY
    ↓
AUTO MONEY MANAGEMENT
    ↓
CAPITAL / RISK CAPACITY
    ↓
MARKET UNIVERSE
    ↓
MARKET SCANNER
    ↓
CAPITAL ELIGIBILITY
    ↓
MARKET QUALITY
    ↓
MICRO EDGE SUITABILITY
    ↓
MARKET RANKING
    ↓
ACTIVE SYMBOL AUTHORITY
    ↓
MARKET INTELLIGENCE
    ↓
PYTHON STRATEGY
    ↓
AI REVIEW
    ↓
FINAL MONEY MANAGEMENT
    ↓
GOVERNANCE
    ↓
EXECUTION
```

## AUTO / MANUAL

```text
SYMBOL SELECTION MODE
AUTO
MANUAL
```

MANUAL preserves the current operator-selected symbol workflow.

AUTO selects the Active Symbol automatically.

## Version 1 Safety Scope

```text
1 Active Symbol
1 Executable Position Maximum
```

The scanner may monitor many markets, but v1 allows one authoritative deep-analysis/trading symbol and one executable position at a time.

## Market Universe
Initial source: KuCoin Futures.

Tradable contracts should be retrieved dynamically rather than maintained as a fixed permanent list.

## Tiered Scanner

```text
TIER 1  Market Universe
        ↓
TIER 2  Lightweight Scanner (~30–50)
        ↓
TIER 3  Shortlist / Ranking (~5–10)
        ↓
TIER 4  Deep Analysis (~1–3)
        ↓
ACTIVE SYMBOL (1)
```

Heavy order-book processing must not run across the entire universe.

## Lightweight Inputs
Possible KuCoin inputs:
- All Futures Tickers
- Best Bid / Ask
- Bid / Ask Size
- Last Price
- Recent activity
- Contract metadata

External providers may be used for discovery/enrichment, but TradingAI remains the selection authority.

## Capital-Aware Selection
The current account capital and AUTO MONEY MANAGEMENT risk-capacity contract must be applied before final ranking.

Paper uses Paper Account authority.
Live uses Real Account authority.

A candidate must answer:

> Is this market safely tradable under current capital and risk policy?

## AUTO MONEY MANAGEMENT Input
AUTO MARKET SELECTION should consume a shared contract such as:

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
maxConcurrentPositions
remainingPositionCapacity
ruinGuardStatus
policyVersion
evaluatedAt
```

AUTO MARKET SELECTION must not recreate Money Management logic independently.

## Capital Eligibility
Per candidate, evaluate available authoritative constraints such as:
- minimum contract size
- minimum notional
- required margin
- available capital
- risk budget
- max position notional
- exposure availability
- fees / slippage allowance
- leverage constraints
- quantity step
- contract multiplier
- position capacity
- MM lock / ruin guard state

## Market Quality
Potential inputs:
- liquidity
- spread
- spread stability
- market activity
- volatility
- order-book quality
- trade activity
- depth proxy
- freshness
- estimated slippage

## Micro Edge Suitability
A liquid market is not automatically suitable.

Evaluate whether the market is appropriate for detailed Micro Edge processing while keeping this separate from BUY/SELL/HOLD.

## Candidate Ranking
Eligible markets are ranked deterministically and audibly.

Ranking may use:
- Capital Eligibility
- Market Quality
- Liquidity
- Spread
- Activity
- Micro Edge Suitability

Opaque AI-only ranking is prohibited in v1.

### v1 Lightweight Ranking Contract (AMS-1C-R1)

Capital eligibility is a gate and is not scored. Spread Quality (40%) and
Top-of-Book Liquidity (30%) are required. Market Activity (20%) is optional.
Price/Data Quality (10%) is reserved and excluded until an authoritative
numeric field exists. Micro Edge Suitability is evaluated only by the later
deep-analysis stage.

Spread Quality uses inverse min-max normalization of `spreadPercent` within
the rankable candidates in one scanner cycle. Top-of-Book Liquidity is
`min(bidSize, askSize)` and uses regular min-max normalization. Available
`activityMetric` values use regular min-max normalization. Equal values,
including a single-candidate set, normalize to `1.0`.

Missing optional factors are not converted to zero. Available base weights
are proportionally re-normalized per candidate, and the final Decimal score is
the sum of normalized factors times their effective weights. Higher is better.
Missing or invalid required data produces `RANKING_DATA_INCOMPLETE` and the
candidate is not ranked.

Candidates sort by score descending, then `spreadPercent` ascending, then
top-of-book liquidity descending, then canonical symbol ascending. Ranks are
one-based and `topCandidate` is rank 1. `topCandidate` is not `activeSymbol`
and ranking performs no runtime mutation.

## Active Symbol Authority
TradingAI must have one authoritative `activeSymbol`.

Recommended related fields:

```text
selectionMode
activeSymbol
selectedAt
selectionReason
selectionCycleId
previousSymbol
candidateRank
switchState
```

Dashboard, Market Intelligence, DOM, Recent Trades, Detectors, Feature Builder, Strategy, AI Review, MM, Governance, Execution, and Recorder must use the same authority.

## Safe Symbol Switch

```text
Current Symbol
    ↓
New Candidate
    ↓
Position = FLAT
    ↓
Pending Order = NONE
    ↓
Pause New Entries
    ↓
Subscribe New Market Data
    ↓
Valid Fresh Snapshot
    ↓
Commit Active Symbol
    ↓
Unsubscribe Old Deep Feed
    ↓
Resume Trading Pipeline
```

Do not switch while a position or unresolved order exists.

## Continuous Selection
The scanner keeps running while the Bot is running.

Re-selection triggers:
1. Position closes.
2. Active market deteriorates while FLAT and no pending order exists.
3. Periodic ranking refresh.

## Anti-Flapping
A slightly better temporary score must not trigger constant switching.

Possible controls:
- minimum score advantage
- stability duration
- minimum active duration
- switch cooldown
- FLAT state
- no pending order

Validate these in Paper/Replay before Live.

## Dashboard
Add:

```text
AUTO MARKET SELECTION（自動銘柄選定）
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

Suggested card fields:
- Mode
- Active Symbol
- Capital Authority
- Available Capital
- MM Regime
- Scanner Status
- Universe Count
- Capital Eligible Count
- Shortlist Count
- Selected At
- Selection Reason
- Top candidate ranking
- Rejected reasons

## Audit Trail
Every meaningful selection cycle must record:
- timestamp
- capital authority
- available capital
- MM regime
- risk budget
- ruin guard status
- universe count
- eligible count
- shortlist count
- selected symbol
- selection reason
- previous symbol
- candidate details
- rejected reasons

## Recorder / Replay

```text
Market Universe Snapshot
    ↓
Scanner Snapshot
    ↓
MM Capital Eligibility
    ↓
Ranking
    ↓
Selected Symbol
    ↓
Active Symbol Switch
    ↓
Order Book
    ↓
Detectors
    ↓
Python Strategy
    ↓
AI Review
    ↓
Final MM
    ↓
Governance
    ↓
Execution
```

Replay must explain why a market was selected over another.

## Storage Strategy
- Universe Snapshot: lightweight multi-market data
- Candidate Snapshot: richer shortlist data
- Active Symbol: full detailed microstructure data

## Paper / Live
Selection logic is shared.
Capital authority changes by mode.
Execution destination remains separate.

## Python / AI Boundary
Python is primary for normalization, filtering, eligibility, ranking, and selection.
AI may later review and downgrade/reject but cannot be the opaque primary selector in v1.

## Failure Modes
- `AUTO_SELECTION_UNAVAILABLE`
- `NO_ELIGIBLE_MARKET`
- `CAPITAL_AUTHORITY_UNAVAILABLE`
- stale ranking
- unsafe/locked MM
- symbol-switch failure

All fail safe.

## Safety Rules
AUTO MARKET SELECTION must never:
- bypass MM or Governance
- enable Live
- alter realOrderAllowed/dryRun
- force BUY/SELL
- change risk thresholds
- switch with open position/pending order
- use stale data
- guess capital
- send an order simply because a symbol was selected

## v1 Scope
- AUTO / MANUAL
- KuCoin Futures universe
- Lightweight scanner
- Capital eligibility
- Market quality
- Candidate ranking
- Single Active Symbol
- Safe switching
- Continuous scanning
- Anti-flapping
- Dashboard
- Audit trail
- Recorder / Replay
- Paper-first

## Out of Scope v1
- multiple simultaneous executable positions
- portfolio optimization
- AI-primary selection
- cross-exchange execution
- unrestricted auto leverage
- automatic Live activation
- cross-exchange arbitrage
- full deep recording of all markets

## LIVE AUTO SELECTION SAFETY

### Status and Default

This chapter specifies prerequisites for a future Live AUTO implementation. It
does not authorize or implement Live switching.

```text
LIVE AUTO = DISABLED BY DEFAULT
```

`AUTO_LIVE` may be activated only when every validation gate in this chapter
has passed and an operator has given explicit, deliberate, auditable approval.
Paper completion and Live read-only observation do not constitute approval.
Process restart always returns Live AUTO to OFF; AUTO must not resume from a
persisted or previous-process state without a new explicit activation.

Modes are distinct and must not be collapsed into ambiguous `AUTO`:

```text
MANUAL
AUTO_PAPER
LIVE_READ_ONLY
AUTO_LIVE  (specified here, not implemented or enabled)
```

### Activation Gates

All of the following are mandatory before `AUTO_LIVE` implementation or
activation:

1. Paper AUTO MARKET SELECTION is complete.
2. Live read-only validation has passed.
3. This Live safety specification has passed review.
4. A fresh, authoritative Live account source has passed integration tests.
5. Anti-flapping calibration is complete for every required setting.
6. Rate-limit-safe observation cadence calibration is complete.
7. Live SafeSwitch targeted and failure-injection tests pass.
8. Restart safety passes with Live AUTO OFF by default.
9. No wrong-symbol decision or execution is possible.
10. Governance and Emergency precedence tests pass.
11. No credential leakage is present.
12. Explicit operator approval is recorded against the configuration version.

An unknown, missing, stale, inconsistent, expired, or partially satisfied gate
is a failed gate. There is no automatic promotion from Paper or
`LIVE_READ_ONLY` to `AUTO_LIVE`.

### Live Capital and Runtime Authority

Fixed, mocked, Paper, or synthetic capital snapshots are prohibited for Live
AUTO permission. Every observation and every pre-commit revalidation must use
one fresh authoritative Live account view covering at least:

```text
equity
available capital
open exposure
position state
pending/open orders
MM Capital Eligibility
authority evaluatedAt / freshness
```

If the Live account authority or MM authority is unavailable, stale, unknown,
or inconsistent, no Live AUTO switch is permitted. v1 retains:

```text
maxExecutablePositions = 1
requireFreshLiveAccountAuthority = true
requireFreshMM = true
requireFlatPosition = true
requireNoPendingOrders = true
requireEmergencySafe = true
```

Only `Position = FLAT` and `Pending Order = NONE` permit a Live symbol switch.
OPEN, EXISTS, or UNKNOWN fails closed.

### Mandatory Anti-Flapping Policy

Paper validation observed A -> B -> A oscillation. Live AUTO therefore requires
all of the following controls; seeing a different rank-1 candidate is not
sufficient switch authority:

```text
minimumScoreAdvantage
minimumActiveDuration
switchCooldown
requiredConsecutiveWins
selectionObservationInterval
```

Definitions:

- `minimumScoreAdvantage`: minimum value of
  `rankingScore(candidate) - rankingScore(currentActiveSymbol)`.
- `minimumActiveDuration`: minimum time the current committed market must remain
  active before a normal ranking switch can be considered.
- `switchCooldown`: minimum safety interval between finalized switch
  transactions. It is separate from minimum active duration.
- `requiredConsecutiveWins`: number of consecutive comparable observations in
  which the same candidate satisfies every gate and score advantage.
- `selectionObservationInterval`: rate-limit-compatible interval between Live
  selection observations. It is not the trading/decision-loop interval.

AMS-6C fixes the following conservative initial calibration for Live AUTO v1:

| Setting | Classification | Live AUTO v1 value |
|---|---|---|
| `minimumScoreAdvantage` | CALIBRATED v1 | `0.42` |
| `minimumActiveDuration` | CALIBRATED v1 | `60 seconds` |
| `switchCooldown` | CALIBRATED v1 | `120 seconds` |
| `requiredConsecutiveWins` | CALIBRATED v1 | `5` |
| `selectionObservationInterval` | CALIBRATED v1 | `10 seconds` |

The values are based on 101 valid five-second observations. Score advantage
ranged approximately 0.4163–0.4256 with p25 approximately 0.4203; `0.42`
therefore filters the lower tail without selecting the unsupported all-blocked
region above the observed maximum. Median candidate run length was 3, p75 was
13, and observed reversals had an approximately 85.71% oscillation rate; five
wins, 60-second minimum active duration, and 120-second cooldown are independent
conservative gates. Ten-second observation cadence doubles the tested cadence
to reserve capacity for concurrent public, private, MM, and runtime traffic.

The candidate and current active market must be scored in the same Ranking
Contract and cycle. Persistence counts only consecutive authoritative
observations satisfying the score gate. A different candidate, stale/missing
observation, invalid ranking, snapshot mismatch, or authority inconsistency
resets the counter. Boundary comparisons are inclusive (`>=`).

The future configuration contract must also expose these fixed safety fields:

| Setting | Classification | Required value/default |
|---|---|---|
| `liveAutoEnabled` | FIXED BY SAFETY RULE | `false` by default; `true` only after all gates and explicit approval |
| `maxExecutablePositions` | FIXED BY SAFETY RULE | `1` |
| `requireFreshLiveAccountAuthority` | FIXED BY SAFETY RULE | `true` |
| `requireFreshMM` | FIXED BY SAFETY RULE | `true` |
| `requireFlatPosition` | FIXED BY SAFETY RULE | `true` |
| `requireNoPendingOrders` | FIXED BY SAFETY RULE | `true` |
| `requireEmergencySafe` | FIXED BY SAFETY RULE | `true` |
| `requireGovernanceAllow` | FIXED BY SAFETY RULE | `true` |
| `requireLiveStatusConsistency` | FIXED BY SAFETY RULE | `true` |
| `automaticSafetyRecoverySwitchEnabled` | FIXED BY SAFETY RULE | `false` |

None of the five calibrated anti-flapping/cadence settings is OPTIONAL or NOT
USED for Live AUTO v1.

### Current Active Market Comparison

For a normal ranking switch, the current active market must be evaluated by the
same scanner and Ranking Contract as the candidate so that scores are
comparable. A candidate cannot win by comparing different cycles, features,
normalization populations, timestamps, or MM authority revisions.

If the current market is `NOT_TRADABLE`, `MM BLOCKED`, or `DATA INVALID`:

1. Block new entries immediately through the existing safety authorities.
2. Do not reinterpret missing/invalid current score as candidate advantage.
3. Do not force-close a position or authorize a symbol switch from ranking.
4. While OPEN or pending/unknown, no switch is permitted.
5. While FLAT, remain blocked unless a separately specified and validated
   safety-recovery switch policy authorizes the transition.

Automatic safety-recovery switching is disabled in v1. This is not permission
to fall back to BTC, the previous winner, or another default symbol.

### Activation, Restart, and Execution Separation

Every process/service/server restart initializes `liveAutoEnabled=false` and
does not restore a previous Live AUTO state. Activation requires an explicit,
auditable approval containing `configurationVersion`, `approvedAt`, approval
identity, and approval source. Approval for symbol selection never changes
`realOrderAllowed`, `dryRun`, AUTO TRADE, Execution, Governance, or Emergency.

`exchangeAuth=VERIFIED` or `apiKeyStatus=VERIFIED` while credential/client/
balance/position failure reasons remain present is inconsistent status.
`LIVE_STATUS_CONSISTENCY_REQUIRED` blocks Live AUTO activation until the status
producer is corrected and revalidated; AMS must not silently remove the block.

### Normal Ranking Switch vs Safety Event

`NORMAL RANKING SWITCH` and `SAFETY FORCED BLOCK / EXIT` are separate state
machines and authorities. Anti-flapping may delay only a normal ranking switch.
Emergency, Governance, or MM safety blocks take effect immediately and must not
wait for score advantage, persistence, minimum duration, or cooldown.

A safety block does not itself authorize position exit, symbol commit, order
cancel, or rollback. Those operations remain owned by their existing explicit
authorities.

### Tiered Analysis and Micro Edge Suitability

Live retains the bounded hierarchy:

```text
Universe
-> Lightweight Scanner
-> Ranking
-> Shortlist / Top N
-> Deep Analysis
-> Live switch eligibility
```

Full-universe deep WebSocket/DOM processing is prohibited. Before a shortlisted
candidate can receive Live commit permission, fresh deterministic Python
Detectors / Feature Builder evidence must establish Micro Edge Suitability.
Missing, stale, or invalid deep-analysis evidence blocks the switch. AI is not
market discovery or symbol-selection authority; it reviews Strategy decisions
for the already authoritative active market only.

### Governance and Emergency Precedence

Governance and Emergency are above AMS:

```text
AMS proposes SWITCH + Governance unsafe -> NO SWITCH / NO ENTRY
Emergency unsafe or unknown -> NO CYCLE / NO SWITCH / NO ENTRY
```

AMS cannot clear, downgrade, bypass, or reinterpret either block. These
authorities must be revalidated immediately before commit.

### Live SafeSwitch Contract

Future Live switching must preserve the AMS-2B order without shortcuts:

```text
FLAT
-> Pending NONE
-> Pause New Entries
-> Prepare New Feed
-> Validate Fresh Snapshot and Runtime Identity
-> Revalidate Live Account / MM / Governance / Emergency
-> Commit Active Symbol
-> Synchronize Market Intelligence and Execution context
-> Detach Old Feed
-> Resume only after safe completion
```

Pre-commit failure keeps the old active symbol and old feed authoritative,
cleans the temporary feed, and resumes only when the old pipeline is confirmed
safe.

Post-commit failure never automatically rolls back to the old symbol. The new
committed symbol remains authoritative, new entries remain paused, and the
state is `ACTION_REQUIRED / FAILED`. Resume is prohibited while feed, runtime,
Market Intelligence, or Execution authority is ambiguous.

### Explicit Operator Approval

Live activation must be explicit, deliberate, and auditable. The approval must
identify the operator/authority, approval timestamp, approved configuration
version, and activation result without placing credentials in audit data.
Approval cannot be inferred from Paper mode, Live read-only mode, process
configuration presence, or a previous process activation.

### Real-Order Permission Separation

Live market selection and real execution are independent permissions:

```text
Live AMS: may observe and, only after all gates, change activeSymbol
Real Execution: separately authorizes an exchange order
```

Enabling Live AMS must never set `realOrderAllowed`, disable `dryRun`, enable
Execution, relax Governance, or alter Emergency state. Selecting a symbol does
not create an order or imply BUY/SELL.

## Recommended Implementation Order

```text
AMS-0A Current Symbol Authority Audit
AMS-0B KuCoin Futures Universe / Metadata Audit
AMS-0C AUTO MM / Capital Eligibility Interface Audit
AMS-1A Market Scanner Contract
AMS-1B Capital Eligibility Contract
AMS-1C Candidate Ranking Contract
AMS-1D Selection Audit Event Contract
AMS-2A Active Symbol Authority
AMS-2B Safe Subscription Switching
AMS-2C Market Intelligence Synchronization
AMS-2D Dashboard AUTO MARKET SELECTION Card
AMS-3A Recorder Integration
AMS-3B Replay Integration
AMS-4A Paper AUTO Selection
AMS-4B Paper End-to-End Trading
AMS-5A Long-Run Paper Validation
AMS-6A Live Read Only Validation
AMS-6B Live AUTO Selection — explicit approval required
```

## Final Responsibility Boundary

```text
AUTO MONEY MANAGEMENT
What risk capacity do we have?

AUTO MARKET SELECTION
What should we trade?

TRADING DECISION
Should we trade it now?

FINAL MONEY MANAGEMENT
How much should we trade?

GOVERNANCE
Are we allowed to execute?

EXECUTION
Send / Fill / Position
```
