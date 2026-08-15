# TradingAI MARKET INTELLIGENCE
# 02 — Component Specification

**Document ID:** MI-02  
**Title:** MARKET INTELLIGENCE Component Specification  
**Version:** 1.0  
**Status:** Baseline Specification  
**Scope:** Frontend component structure and component-level behavior  
**Parent document:** `01_MARKET_INTELLIGENCE_UI_SPEC.md`

---

## 1. Purpose

This document defines the UI components that make up the TradingAI MARKET INTELLIGENCE screen.

It specifies:

- component responsibilities;
- information shown by each component;
- required states;
- component boundaries;
- input and output relationships;
- prohibited responsibilities;
- extensibility rules.

This document does not define backend persistence, API contracts, or the internal decision logic of Strategy, LSTM, LLM, Governance, or Execution. Those topics are defined in separate specifications.

---

## 2. Component Design Principles

All MARKET INTELLIGENCE components must follow these principles:

1. **Review first**  
   Historical position and decision review is the primary use case.

2. **Position centered**  
   The selected position is the top-level context for the entire screen.

3. **Deterministic rendering**  
   The same replay record must produce the same visual result.

4. **No trading controls**  
   MARKET INTELLIGENCE must not submit, cancel, flatten, or modify orders.

5. **Explicit uncertainty**  
   Missing, unknown, stale, unsupported, and malformed values must be displayed distinctly.

6. **Stable component boundaries**  
   Data acquisition, interpretation, and rendering must remain separated.

7. **Fixed Railway structure**  
   Existing stations must not move because of temporary implementation convenience.

---

## 3. Top-Level Component Tree

```text
MarketIntelligencePage
├── MarketIntelligenceHeader
├── MarketIntelligenceToolbar
│   ├── PositionSelector
│   ├── ReplayModeSelector
│   ├── ReplayTimestamp
│   └── DataQualityIndicator
├── MarketIntelligenceWorkspace
│   ├── MarketReplayPanel
│   │   ├── OrderBookReplay
│   │   ├── RecentTradesReplay
│   │   ├── PositionMarkerOverlay
│   │   ├── MarketEventSummary
│   │   └── ReplayController
│   └── DecisionRailwayPanel
│       ├── DecisionRailway
│       │   ├── RailwayStation[]
│       │   ├── RailwayConnector[]
│       │   └── RailwayTerminalResult
│       ├── StationInspector
│       ├── DecisionSummary
│       └── ExecutionOutcome
├── PositionTimeline
├── MarketIntelligenceStatusLayer
└── MarketIntelligenceErrorBoundary
```

---

# 4. MarketIntelligencePage

## 4.1 Responsibility

`MarketIntelligencePage` is the screen-level orchestration component.

It owns:

- selected position identity;
- selected decision identity;
- selected marker identity;
- replay cursor;
- replay mode;
- page-level loading and error state;
- coordination between LEFT and RIGHT panels.

It must not calculate detector results, Strategy decisions, AI decisions, Governance outcomes, or execution classifications.

## 4.2 Required Inputs

```text
selectedPositionId
selectedDecisionId
replayMode
replayCursor
replayRecord
decisionRecord
dataQuality
loadingState
errorState
```

## 4.3 Required Outputs

```text
onPositionSelect(positionId)
onDecisionSelect(decisionId)
onMarkerSelect(markerId)
onReplaySeek(timestamp)
onReplayStep(direction)
onReplayModeChange(mode)
onRetry()
```

## 4.4 States

- No position selected
- Position loading
- Position loaded
- Partial data
- Replay unavailable
- Decision unavailable
- Fatal page error

---

# 5. MarketIntelligenceHeader

## 5.1 Content

Title:

```text
MARKET INTELLIGENCE
```

Subtitle:

```text
Real-time Market Recognition & AI Decision Engine
```

The subtitle is retained as the official product subtitle, even though the primary operational workflow is post-trade review.

## 5.2 Optional Status Items

- selected exchange;
- selected symbol;
- selected position status;
- replay/live badge;
- data source badge;
- data quality badge.

## 5.3 Prohibited Content

The header must not contain:

- Loop controls;
- Auto Trade controls;
- Emergency controls;
- risk configuration;
- order submission controls.

---

# 6. MarketIntelligenceToolbar

## 6.1 Responsibility

Provides the global review context and high-level navigation controls.

## 6.2 Child Components

- `PositionSelector`
- `ReplayModeSelector`
- `ReplayTimestamp`
- `DataQualityIndicator`

---

# 7. PositionSelector

## 7.1 Purpose

Allows the user to select one historical or active position.

## 7.2 Required Display Fields

Each option or row must support:

- position number;
- position ID;
- symbol;
- exchange;
- direction;
- entry time;
- exit time;
- position status;
- realized PnL;
- unrealized PnL where applicable;
- duration;
- trade mode;
- close reason.

## 7.3 Position Status Values

- OPEN
- CLOSED
- PARTIALLY_CLOSED
- FLATTENED
- CANCELLED_BEFORE_ENTRY
- UNKNOWN

## 7.4 Selection Rule

Selecting a position must:

1. reset the previously selected marker;
2. select the default decision event;
3. load the position replay package;
4. set the replay cursor to entry when available;
5. update both LEFT and RIGHT panels atomically.

## 7.5 Default Decision Event

Priority:

1. Entry decision
2. First available decision
3. Exit decision
4. No decision selected

## 7.6 Empty State

```text
No positions available for review.
```

---

# 8. ReplayModeSelector

## 8.1 Modes

- REVIEW
- LIVE

## 8.2 Default

```text
REVIEW
```

## 8.3 REVIEW Mode

Uses stored replay data associated with a position or decision.

## 8.4 LIVE Mode

Displays current market state where supported.

LIVE mode must not replace or overwrite historical replay context.

## 8.5 Safety Rule

Changing to LIVE mode must not enable Auto Trade or Execution.

---

# 9. ReplayTimestamp

Displays:

- selected replay timestamp;
- event-relative offset;
- data capture timestamp;
- timezone;
- optional milliseconds.

Example:

```text
2026-07-19 14:32:18.426 JST
Entry + 1.250s
```

Unknown timestamps must display:

```text
Timestamp unavailable
```

---

# 10. DataQualityIndicator

## 10.1 Purpose

Shows whether the loaded replay is trustworthy and complete.

## 10.2 States

- COMPLETE
- PARTIAL
- STALE
- UNSYNCED
- MISSING
- MALFORMED
- UNSUPPORTED

## 10.3 Required Detail

The indicator must expose the reason, for example:

```text
PARTIAL — Recent Trades snapshot missing
```

## 10.4 Rule

Data quality must never be inferred from color alone. A text label is mandatory.

---

# 11. MarketIntelligenceWorkspace

## 11.1 Layout

Desktop:

```text
LEFT 45%  |  RIGHT 55%
```

The split is the canonical layout.

## 11.2 Responsibilities

- render both main panels;
- maintain synchronized vertical context;
- prevent one panel from silently updating without the other;
- preserve selected event during resize.

## 11.3 Responsive Rule

At widths where two columns are not readable:

```text
Market Replay
↓
AI Decision Railway
```

The logical order must remain LEFT first, RIGHT second.

---

# 12. MarketReplayPanel

## 12.1 Purpose

Explains what happened in the market at the selected replay point.

## 12.2 Children

- `OrderBookReplay`
- `RecentTradesReplay`
- `PositionMarkerOverlay`
- `MarketEventSummary`
- `ReplayController`

## 12.3 Required Context Header

Must show:

- symbol;
- exchange;
- replay timestamp;
- selected event;
- position number;
- side;
- trade mode.

---

# 13. OrderBookReplay

## 13.1 Purpose

Displays the stored order-book state associated with the selected replay cursor.

## 13.2 Required Columns

Ask side:

- price;
- size;
- cumulative size.

Bid side:

- price;
- size;
- cumulative size.

Shared:

- spread;
- mid price;
- best bid;
- best ask.

## 13.3 Optional Derived Indicators

- depth imbalance;
- liquidity concentration;
- large wall indicator;
- spread quality;
- spread volatility;
- pressure region.

These must be labeled as derived values.

## 13.4 Price Levels

The number of displayed levels must be configurable.

Default recommendation:

```text
20 ask levels
20 bid levels
```

## 13.5 Snapshot Rule

In REVIEW mode, the component must show the stored snapshot for the replay point, not the current market board.

## 13.6 Missing Snapshot

Display:

```text
Order book snapshot unavailable for this event.
```

The component must not substitute live data unless explicitly marked as LIVE.

## 13.7 Visual Requirements

- asks and bids must be visually distinguishable;
- current spread must be visible;
- entry/exit marker price bands must remain identifiable;
- unusually large levels may be emphasized;
- numeric alignment must remain stable.

---

# 14. RecentTradesReplay

## 14.1 Purpose

Displays recent trade prints surrounding the selected event.

## 14.2 Required Columns

- timestamp;
- price;
- size;
- aggressor side;
- event-relative offset.

## 14.3 Required Summary Metrics

Where data exists:

- buy trade ratio;
- sell trade ratio;
- buy volume;
- sell volume;
- order-flow delta;
- VWAP;
- largest print;
- print count.

## 14.4 Classification

Aggressor side values:

- BUY
- SELL
- UNKNOWN

## 14.5 Missing Data

```text
Recent trades snapshot unavailable for this event.
```

---

# 15. PositionMarkerOverlay

## 15.1 Purpose

Shows execution and lifecycle events on market replay components.

## 15.2 Marker Types

- BUY_ENTRY
- SELL_ENTRY
- BUY_EXIT
- SELL_EXIT
- PARTIAL_EXIT
- STOP_LOSS
- TAKE_PROFIT
- FLATTEN
- MANUAL_CLOSE
- CANCEL
- REJECT
- UNKNOWN

## 15.3 Numbering

Events belonging to the same position share the same position number.

Examples:

```text
BUY①
SELL①
TP①
FLATTEN①
```

## 15.4 Marker Content

Each marker must support:

- marker label;
- position number;
- timestamp;
- price;
- quantity;
- side;
- reduceOnly;
- event type;
- execution status;
- decision ID.

## 15.5 Click Behavior

Selecting a marker must:

1. move the replay cursor to the marker timestamp;
2. select the linked decision;
3. update the Railway route;
4. update Station Inspector;
5. preserve the selected position.

## 15.6 Marker Persistence

Markers must remain identifiable even when the replayed board moves away from their original price.

---

# 16. MarketEventSummary

## 16.1 Purpose

Provides a concise explanation of the selected market event.

## 16.2 Required Fields

- selected event type;
- event time;
- event price;
- position context;
- strongest market signals;
- detected anomalies;
- snapshot quality.

## 16.3 Example

```text
BUY Entry
Strong buy pressure, positive directional bias, acceptable liquidity.
No spoof condition selected as decision evidence.
```

## 16.4 Rule

This summary must be generated from recorded fields. It must not invent missing reasoning.

---

# 17. ReplayController

## 17.1 Controls

- Play
- Pause
- Previous event
- Next event
- Previous frame
- Next frame
- Jump to entry
- Jump to exit
- Restart replay
- Playback speed

## 17.2 Supported Speeds

Recommended:

- 0.25×
- 0.5×
- 1×
- 2×
- 4×

## 17.3 Timeline Range

The replay range may include:

- pre-entry context;
- entry decision;
- order submission;
- fill;
- position management;
- exit decision;
- exit execution;
- post-exit context.

## 17.4 Playback Rule

Replay must not trigger real backend trading actions.

## 17.5 End Behavior

At replay end:

- stop playback;
- retain final state;
- retain highlighted Railway route;
- do not reset automatically.

---

# 18. DecisionRailwayPanel

## 18.1 Purpose

Explains how the system progressed from market state to final execution outcome.

## 18.2 Children

- `DecisionRailway`
- `StationInspector`
- `DecisionSummary`
- `ExecutionOutcome`

## 18.3 Fixed Order

```text
Python Runtime
→ Runtime Adapter
→ Feature Builder
→ Python Strategy
→ LSTM
→ LLM
→ Consensus
→ AI Final Decision
→ Governance
→ Execution
```

Current implementation truth must determine whether a station is active, unavailable, reserved, or not applicable.

---

# 19. DecisionRailway

## 19.1 Purpose

Renders the complete decision path as a fixed railway map.

## 19.2 Core Elements

- stations;
- connectors;
- branch labels where required;
- terminal result;
- selected route;
- blocked route;
- unused route.

## 19.3 Station Position Rule

Existing station positions must not change merely because a station is inactive.

## 19.4 Route Rule

The selected decision record determines:

- used stations;
- referenced stations;
- unused stations;
- blocked station;
- terminal state.

## 19.5 No-Data Rule

The Railway skeleton remains visible even when no decision is selected.

---

# 20. RailwayStation

## 20.1 Required Fields

```text
stationId
stationType
title
status
availability
inputSummary
outputSummary
reason
timestamp
durationMs
dataQuality
```

## 20.2 Station Status

- USED
- REFERENCED
- UNUSED
- BLOCKED
- UNAVAILABLE
- RESERVED
- ERROR

## 20.3 Availability

- CURRENT
- RESERVED
- NOT_IMPLEMENTED
- NOT_RECORDED
- UNSUPPORTED

## 20.4 Visual Meaning

Recommended semantics:

- USED: green
- REFERENCED: yellow
- UNUSED: gray
- BLOCKED: red
- UNAVAILABLE: muted/dashed
- RESERVED: outline/dashed
- ERROR: red with explicit error label

Text labels are mandatory.

## 20.5 Selection

Clicking a station opens the Station Inspector for that station.

---

# 21. RailwayConnector

## 21.1 Purpose

Represents the transition between two stations.

## 21.2 States

- ACTIVE
- INACTIVE
- BLOCKED
- UNKNOWN
- RESERVED

## 21.3 Required Metadata

Where available:

- transition timestamp;
- transition reason;
- elapsed time;
- branch condition;
- source station;
- destination station.

## 21.4 Rule

A connector must not be shown as active solely because both adjacent stations contain data. It must reflect the recorded route.

---

# 22. RailwayTerminalResult

## 22.1 Possible Results

- BUY
- SELL
- HOLD
- BLOCKED
- SUBMITTED
- FILLED
- CANCELLED
- REJECTED
- FAILED
- UNKNOWN

## 22.2 Required Context

- final decision;
- Governance result;
- execution result;
- order ID where available;
- paper/live mode;
- final reason.

---

# 23. StationInspector

## 23.1 Purpose

Displays full details for one selected Railway station.

## 23.2 Required Sections

- Overview
- Inputs
- Outputs
- Evidence
- Reason
- Timing
- Data quality
- Raw values where permitted

## 23.3 Required Common Fields

- station name;
- station status;
- availability;
- timestamp;
- processing duration;
- source component;
- schema version.

## 23.4 Evidence Display

Evidence must distinguish:

- directly used;
- referenced;
- ignored;
- unavailable;
- rejected.

## 23.5 Raw Data

Raw JSON may be available in a collapsible developer section.

It must not be the only human-readable explanation.

## 23.6 Missing Reason

Display:

```text
Reason was not recorded.
```

Do not generate a fabricated reason.

---

# 24. DecisionSummary

## 24.1 Purpose

Summarizes the selected decision in a human-readable form.

## 24.2 Required Content

- candidate from Python Strategy;
- LSTM output;
- LLM output;
- Consensus state;
- AI final decision;
- Governance result;
- execution result;
- primary reason;
- suppression or block reason.

## 24.3 Example

```text
Strategy proposed BUY with 0.72 confidence.
LSTM predicted BUY.
LLM returned BUY.
Consensus matched.
Governance passed execution.
Paper order was filled.
```

## 24.4 Constraint

The summary must remain traceable to recorded fields.

---

# 25. ExecutionOutcome

## 25.1 Purpose

Displays the final order or non-order outcome.

## 25.2 Required Fields

- execution requested;
- execution allowed;
- trade mode;
- dry run;
- order side;
- order type;
- requested quantity;
- filled quantity;
- average fill price;
- order ID;
- reduceOnly;
- status;
- rejection or cancellation reason;
- latency.

## 25.3 Non-Execution Cases

Must support:

- Strategy HOLD;
- executionAllowed false;
- AI downgrade to HOLD;
- Consensus mismatch;
- Governance BLOCK;
- execution disabled;
- Emergency lock;
- submission failure;
- missing execution data.

---

# 26. PositionTimeline

## 26.1 Purpose

Provides a time-ordered lifecycle of the selected position.

## 26.2 Event Types

- market snapshot;
- detector update;
- feature update;
- Strategy candidate;
- LSTM result;
- LLM result;
- Consensus;
- AI final decision;
- Governance decision;
- order submitted;
- order acknowledged;
- order filled;
- partial fill;
- cancel;
- stop loss;
- take profit;
- flatten;
- close;
- error.

## 26.3 Interaction

Selecting an event updates:

- replay cursor;
- market replay;
- Railway route;
- Station Inspector;
- Decision Summary.

## 26.4 Ordering

Primary order:

```text
event timestamp ascending
```

Tie-breaker:

```text
recorded sequence number
```

---

# 27. MarketIntelligenceStatusLayer

## 27.1 Purpose

Provides consistent loading, empty, partial, unavailable, and error presentation.

## 27.2 States

- IDLE
- LOADING
- READY
- PARTIAL
- EMPTY
- ERROR
- UNSUPPORTED

## 27.3 Loading Rule

Use component skeletons that preserve final layout dimensions.

## 27.4 Partial Rule

Usable content remains visible while unavailable parts are explicitly marked.

---

# 28. MarketIntelligenceErrorBoundary

## 28.1 Purpose

Prevents one malformed replay record from breaking the entire TradingAI application.

## 28.2 Required Behavior

- isolate rendering failure;
- log the component context;
- display a recoverable error;
- provide retry;
- preserve selected position where possible.

## 28.3 Error Message

```text
MARKET INTELLIGENCE could not render this replay record.
```

A technical detail section may be shown in development mode.

---

# 29. Component Data Ownership

## 29.1 Page-Level State

Owned by `MarketIntelligencePage`:

- selected position;
- selected decision;
- selected marker;
- replay cursor;
- replay mode;
- shared loading state.

## 29.2 Local UI State

May be owned locally:

- expanded inspector section;
- selected tab inside inspector;
- playback speed;
- column width;
- collapsed optional panels.

## 29.3 Prohibited Local Derivation

Components must not independently derive authoritative:

- final BUY/SELL/HOLD;
- Governance PASS/BLOCK;
- execution success;
- Station route;
- position status.

These must come from normalized application data.

---

# 30. Component Accessibility

All interactive components must support:

- keyboard focus;
- visible focus indicator;
- readable text labels;
- non-color status indication;
- semantic button behavior;
- accessible names for markers and stations;
- screen-reader-compatible state text.

Recommended Railway station accessible label:

```text
Python Strategy, used, output BUY, confidence 0.72
```

---

# 31. Performance Requirements

- Selecting a cached position should update visible UI without noticeable delay.
- Large raw payloads must not block first render.
- Order-book rows should use efficient rendering.
- Replay animation must not cause full-page re-render on every frame.
- Inspector raw JSON should load or render lazily.
- Timeline should support long position histories.

---

# 32. Test Requirements

Each component must have tests covering:

- normal data;
- empty data;
- partial data;
- malformed data;
- unknown enum values;
- loading;
- error;
- selection;
- keyboard behavior;
- synchronization with selected position and replay cursor.

Critical integration tests:

1. Select position → both panels update.
2. Select entry marker → entry decision route appears.
3. Select exit marker → exit decision route appears.
4. Governance BLOCK → route terminates at Governance.
5. Strategy HOLD → downstream execution is not shown as used.
6. Missing LLM record → Railway remains stable and shows unavailable.
7. Replay end → final state remains visible.
8. REVIEW mode never displays unlabeled live data.

---

# 33. Current and Reserved Components

## 33.1 Current Components

Current baseline:

- PositionSelector
- ReplayModeSelector
- OrderBookReplay
- RecentTradesReplay
- PositionMarkerOverlay
- ReplayController
- DecisionRailway
- RailwayStation
- RailwayConnector
- StationInspector
- DecisionSummary
- ExecutionOutcome
- PositionTimeline

## 33.2 Reserved Components

May be added later:

- LiquidityHeatmap
- DetectorEvidencePanel
- IcebergEventInspector
- SpoofEventInspector
- MultiAgentReviewPanel
- ExplainableAISummary
- ReplayComparison
- PositionComparison
- ExportAuditReport

Reserved components must not be presented as currently implemented.

---

# 34. MUST

The implementation MUST:

- retain the canonical LEFT/RIGHT information architecture;
- keep the Railway station order stable;
- synchronize position, marker, replay cursor, and decision selection;
- distinguish missing data from zero or false;
- distinguish unused stations from unavailable stations;
- display text status in addition to color;
- prevent trading actions from this screen;
- use recorded decision evidence;
- preserve final replay state after playback;
- support entry and exit decision review separately.

---

# 35. SHOULD

The implementation SHOULD:

- use compact professional visual density;
- keep market data numerically aligned;
- animate only meaningful transitions;
- use reusable normalized data contracts;
- preserve user context when switching inspector stations;
- expose developer raw data without making it the default view;
- support future Station additions without restructuring the page.

---

# 36. MUST NOT

The implementation MUST NOT:

- submit or modify orders;
- infer execution success from the existence of an order ID alone;
- substitute current live board data for missing historical board data;
- fabricate reasons or evidence;
- rearrange the Railway based on active stations;
- hide unavailable stations as though they never existed;
- treat unknown values as false;
- use color as the sole status indicator;
- redesign the page during ordinary feature additions;
- combine Dashboard operation controls with MARKET INTELLIGENCE review controls.

---

# 37. Completion Criteria

This component specification is satisfied when:

- every component has a defined responsibility;
- component ownership is unambiguous;
- LEFT and RIGHT panels remain synchronized;
- entry and exit decisions are independently reviewable;
- missing and partial data are safely rendered;
- the complete recorded route can be inspected;
- future detectors can be added without redesigning existing component boundaries.

---

# 38. Related Documents

```text
01_MARKET_INTELLIGENCE_UI_SPEC.md
02_MARKET_INTELLIGENCE_COMPONENT_SPEC.md
03_MARKET_INTELLIGENCE_INTERACTION_SPEC.md
04_MARKET_INTELLIGENCE_VISUAL_GUIDELINE.md
05_MARKET_INTELLIGENCE_DATA_MODEL_SPEC.md
06_MARKET_INTELLIGENCE_API_SPEC.md
07_AI_DECISION_RAILWAY_LOGIC_SPEC.md
08_MARKET_INTELLIGENCE_IMPLEMENTATION_GUIDE.md
09_MARKET_INTELLIGENCE_DESIGN_PHILOSOPHY.md
```

---

**End of document**
