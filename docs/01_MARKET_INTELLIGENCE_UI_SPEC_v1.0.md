# TradingAI MARKET INTELLIGENCE

# Complete UI Specification

Version: 1.0 (Master Draft)

------------------------------------------------------------------------

# 1. Purpose

This document is the authoritative UI specification for the MARKET
INTELLIGENCE screen.

The objective is to define the screen completely enough that any
developer or AI assistant can implement the same interface without
redesigning it.

MARKET INTELLIGENCE is **not** a trading dashboard.

It is a **Market Replay & AI Decision Audit System**.

Primary goals:

-   Replay historical positions.
-   Explain every AI decision.
-   Visualize the complete decision path.
-   Audit Python → Strategy → AI → Governance → Execution.

------------------------------------------------------------------------

# 2. Design Philosophy

The design follows five principles.

1.  Explainability
2.  Position-centered workflow
3.  Replay-first
4.  Fixed information architecture
5.  Long-term extensibility

The screen must always prioritize understanding **why** a decision
happened instead of only showing **what** happened.

------------------------------------------------------------------------

# 3. Screen Layout

Horizontal split.

LEFT : 45%

RIGHT : 55%

    +---------------------------------------------------------------+
    |                 MARKET INTELLIGENCE                           |
    +---------------------------+-----------------------------------+
    | MARKET REPLAY             | AI DECISION RAILWAY              |
    |                           |                                   |
    | Order Book                | Railway                           |
    | Recent Trades             | Decision Details                  |
    | Position Timeline         | Station Inspector                 |
    | Replay Controls           | Final Result                      |
    +---------------------------+-----------------------------------+

------------------------------------------------------------------------

# 4. LEFT PANEL

## 4.1 Position Selector

Displays completed positions.

Information:

-   Position ID
-   Entry time
-   Exit time
-   Direction
-   PnL
-   Duration

Selecting one position updates the entire page.

------------------------------------------------------------------------

## 4.2 Replay Mode

Modes:

-   LIVE
-   REVIEW

Default:

REVIEW

------------------------------------------------------------------------

## 4.3 Order Book

Display the stored DOM snapshot captured during replay.

Columns:

-   Price
-   Bid Size
-   Ask Size
-   Cumulative Volume

Support highlighting:

-   Large walls
-   Liquidity imbalance
-   Entry marker
-   Exit marker

------------------------------------------------------------------------

## 4.4 Recent Trades

Columns:

-   Time
-   Price
-   Size
-   Side

Statistics:

-   Buy ratio
-   Sell ratio
-   VWAP

------------------------------------------------------------------------

## 4.5 Position Markers

Supported:

-   BUY Entry
-   SELL Entry
-   Exit
-   Partial Exit
-   Stop Loss
-   Take Profit
-   Flatten
-   Manual Close

Markers are numbered.

BUY① SELL①

Selecting a marker switches replay to that event.

------------------------------------------------------------------------

## 4.6 Replay Controller

Functions:

-   Play
-   Pause
-   Previous Step
-   Next Step
-   Jump to Entry
-   Jump to Exit

------------------------------------------------------------------------

# 5. RIGHT PANEL

Purpose:

Visualize the reasoning path.

No free-form layout.

Railway is fixed.

------------------------------------------------------------------------

# 6. AI Decision Railway

Order never changes.

Python Runtime ↓

Runtime Adapter ↓

Feature Builder ↓

Python Strategy ↓

LSTM ↓

LLM ↓

Consensus ↓

AI Final Decision ↓

Governance ↓

Execution

Future stations may be inserted without changing existing order.

------------------------------------------------------------------------

# 7. Station Definitions

## Python Runtime

Inputs:

-   Buy Pressure
-   Sell Pressure
-   Momentum Persistence
-   AI Momentum Persistence
-   Liquidity Quality
-   Spread
-   Spread Volatility
-   Absorption
-   Fake Pressure
-   Imbalance Strength
-   Stagnant Heavy Flow

## Runtime Adapter

Produces:

-   Directional Bias
-   Momentum Score
-   Liquidity Score
-   Confidence Score
-   Order Flow Delta
-   Spread Score
-   Imbalance Score

## Feature Builder

Produces normalized feature vector.

## Python Strategy

Outputs:

-   BUY
-   SELL
-   HOLD

Includes:

-   confidence
-   executionAllowed
-   suppressionReason

## LSTM

Prediction:

BUY / SELL / HOLD

## LLM

Final reasoning layer.

Displays:

-   Directional Bias
-   Momentum
-   Imbalance
-   Explanation

## Consensus

States:

-   MATCH
-   NOT MATCH

## AI Final Decision

BUY

SELL

HOLD

## Governance

PASS

BLOCK

BLOCK REASON

## Execution

Submitted

Filled

Cancelled

Rejected

------------------------------------------------------------------------

# 8. Station States

Gray

Unused

Green

Executed

Yellow

Referenced

Red

Blocked

------------------------------------------------------------------------

# 9. Replay Animation

Replay sequence:

Python Runtime

↓

Runtime Adapter

↓

Feature Builder

↓

Python Strategy

↓

LSTM

↓

LLM

↓

Consensus

↓

Governance

↓

Execution

Animation should complete in approximately two seconds.

------------------------------------------------------------------------

# 10. Click Behaviour

Click Position

→ Load replay

Click Marker

→ Jump replay

Click Station

→ Show inspector

------------------------------------------------------------------------

# 11. Inspector

Every station displays:

Input

Output

Reason

Timestamp

Execution Time

------------------------------------------------------------------------

# 12. Empty State

Display:

"No replay selected."

------------------------------------------------------------------------

# 13. Loading

Skeleton layout only.

No layout shift.

------------------------------------------------------------------------

# 14. Error State

Gracefully display unavailable replay data.

------------------------------------------------------------------------

# 15. UI Rules

MUST

-   Fixed layout
-   Fixed railway order
-   Position-first workflow
-   Replay-first workflow

SHOULD

-   Smooth transitions
-   Minimal animations
-   Dark professional theme

MUST NOT

-   Rearrange stations
-   Mix audit and trading controls
-   Prioritize live monitoring over replay

------------------------------------------------------------------------

# 16. Future Extensions

Reserved stations:

-   Iceberg Detector
-   Spoof Detector
-   Liquidity Heatmap
-   Multi-Agent Review
-   Explainable AI Summary

------------------------------------------------------------------------

# 17. Non Goals

This screen is not intended to:

-   Submit trades
-   Configure risk
-   Replace Dashboard
-   Replace Runtime Monitor

------------------------------------------------------------------------

# 18. Final Objective

Selecting any historical position should allow the user to understand:

Market

↓

Python

↓

Strategy

↓

AI

↓

Governance

↓

Execution

without reading logs.

This document serves as the authoritative UI specification for the
MARKET INTELLIGENCE screen.
