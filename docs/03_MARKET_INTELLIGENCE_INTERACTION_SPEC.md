# 03 MARKET INTELLIGENCE INTERACTION SPECIFICATION
Version 1.0 (Merged Draft)

## Table of Contents

- Part A — Core Interaction Principles
- Part B — Timeline, Inspector and User Interaction
- Part C — Replay State Machine and Synchronization
- Part D — Implementation, Testing and Review

---



---

# 03 MARKET INTELLIGENCE INTERACTION SPECIFICATION
Version 1.0 (Part A)

> NOTE
> This is Part A of the complete Interaction Specification.
> The final document will merge Parts A–D into one file.

# 1. Purpose

This specification defines every user interaction on the MARKET INTELLIGENCE screen.

It specifies:
- click behavior
- replay behavior
- synchronization
- animation rules
- state transitions
- error handling
- keyboard navigation

# 2. Core Principles

1. Position-first interaction.
2. Replay-first workflow.
3. Every interaction is deterministic.
4. LEFT and RIGHT panels always remain synchronized.
5. No interaction may trigger trading actions.

# 3. Primary Interaction Flow

Position Selected
    ↓
Replay Package Loaded
    ↓
Replay Cursor Initialized
    ↓
LEFT Panel Updated
    ↓
RIGHT Railway Updated
    ↓
Inspector Updated
    ↓
Timeline Updated

# 4. Position Selection

Selecting a position MUST:

- cancel current replay
- preserve zoom
- load replay package
- select default decision
- move replay cursor to entry
- refresh LEFT panel
- refresh RIGHT panel
- refresh inspector
- refresh timeline

Selecting the same position again MUST NOT reload data unless explicitly refreshed.

# 5. Marker Interaction

Supported markers:

- BUY Entry
- SELL Entry
- Exit
- Partial Exit
- TP
- SL
- Flatten
- Manual Close

Clicking a marker MUST:

1. Stop replay.
2. Move replay cursor.
3. Highlight marker.
4. Update Railway.
5. Update Inspector.
6. Update Decision Summary.
7. Scroll timeline to selected event.

# 6. Railway Interaction

Clicking a station MUST:

- highlight station
- open inspector
- preserve replay cursor
- preserve selected marker

Double click SHOULD pin the inspector.

# 7. Replay Controls

Buttons:

Play
Pause
Next Frame
Previous Frame
Next Event
Previous Event
Jump Entry
Jump Exit

Replay MUST NOT trigger backend execution.

# 8. Synchronization Rules

Whenever replay cursor changes:

LEFT panel updates
RIGHT panel updates
Timeline updates
Inspector updates

No component may lag behind another.

# 9. Animation Rules

Replay order:

Python Runtime
↓
Runtime Adapter
↓
Feature Builder
↓
Strategy
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

Approximate total duration:
2 seconds.

# 10. MUST

- Keep panels synchronized.
- Never desynchronize replay cursor.
- Never execute trades.
- Preserve selected position.

End of Part A.


---

# 03 MARKET INTELLIGENCE INTERACTION SPECIFICATION
Version 1.0 (Part B)

> This is Part B of the complete Interaction Specification.

# 11. Timeline Interaction

## Purpose

The timeline is the primary navigation component for reviewing a position's lifecycle.

## Selecting an Event

Selecting an event MUST:

1. Pause replay if playing.
2. Move replay cursor to the event timestamp.
3. Highlight the selected timeline item.
4. Update Market Replay.
5. Update Decision Railway.
6. Update Station Inspector.
7. Update Decision Summary.

## Timeline Events

- Market Snapshot
- Detector Update
- Feature Update
- Strategy Candidate
- LSTM Result
- LLM Result
- Consensus
- Governance
- Order Submitted
- Order Filled
- Stop Loss
- Take Profit
- Flatten
- Close
- Error

# 12. Station Inspector

Selecting a Railway station opens the inspector.

Inspector sections:

- Overview
- Inputs
- Outputs
- Evidence
- Reason
- Timing
- Raw Data (optional)

Rules:

- Only one station may be selected.
- Closing the inspector must not change replay position.
- Inspector scrolling is independent.

# 13. Decision Summary Interaction

Whenever the selected decision changes:

- Summary updates immediately.
- Previous summary is discarded.
- Animation should not exceed 150 ms.

# 14. Keyboard Navigation

Required shortcuts:

Arrow Left:
Previous replay frame

Arrow Right:
Next replay frame

Arrow Up:
Previous timeline event

Arrow Down:
Next timeline event

Space:
Play / Pause

Home:
Jump to Entry

End:
Jump to Exit

Escape:
Close Inspector

Keyboard navigation MUST preserve synchronization.

# 15. Mouse Interaction

Supported:

- Click
- Double Click
- Hover
- Wheel Scroll

Not required:

- Drag stations
- Rearrange railway

# 16. Hover Behavior

Hovering a station SHOULD display:

- Station name
- Status
- Timestamp
- Duration

Hovering a marker SHOULD display:

- Price
- Quantity
- Time
- Decision ID

# 17. Zoom

Optional for:

- Timeline
- Order Book

Zoom MUST NOT affect Railway layout.

# 18. Loading

During loading:

- Skeleton components remain visible.
- Layout must not shift.
- Existing replay remains visible until replacement is ready when possible.

# 19. Error Recovery

If replay data fails:

Display an inline recoverable error.

Provide:

- Retry
- Return to Position List

Errors in one component MUST NOT break the entire page.

# 20. Partial Data

Missing components MUST display explicit placeholders.

Example:

"Recent trades unavailable."

The system MUST distinguish:

- Missing
- Unknown
- Unsupported
- Malformed

# 21. Interaction Timing

Recommended maximum response:

Position selection:
<300 ms (cached)

Marker selection:
<150 ms

Station selection:
<100 ms

Replay frame:
Smooth continuous updates

End of Part B.


---

# 03 MARKET INTELLIGENCE INTERACTION SPECIFICATION
Version 1.0 (Part C)

> This is Part C of the complete Interaction Specification.

# 22. Replay State Machine

```text
IDLE
  │
  ▼
POSITION_SELECTED
  │
  ▼
REPLAY_LOADING
  │
  ├── failure ─────► REPLAY_ERROR
  │
  ▼
REPLAY_READY
  │
  ├── Play ───────► PLAYING
  │                  │
  │                  ├── Pause ───► PAUSED
  │                  ├── End ─────► COMPLETED
  │                  └── Error ───► REPLAY_ERROR
  │
  └── Jump ───────► SEEKING
                         │
                         ▼
                    REPLAY_READY
```

Rules:

- Only one replay session may exist.
- Replay cursor is authoritative.
- Replay never changes historical data.

---

# 23. Position Lifecycle

```text
Position Selected
      │
      ▼
Replay Loaded
      │
      ▼
Entry Event
      │
      ▼
Management Events
      │
      ▼
Exit Event
      │
      ▼
Completed
```

Each lifecycle event updates:

- Timeline
- Replay
- Railway
- Inspector
- Summary

Atomically.

---

# 24. Marker Lifecycle

```text
Marker Created
      │
      ▼
Marker Displayed
      │
      ▼
Marker Selected
      │
      ▼
Replay Jump
      │
      ▼
Railway Update
      │
      ▼
Inspector Update
```

Marker selection must never create a new replay session.

---

# 25. Railway State Machine

Station states:

UNUSED

↓

REFERENCED

↓

USED

↓

COMPLETED

Blocked route:

USED

↓

BLOCKED

↓

TERMINATED

Unavailable route:

UNAVAILABLE

Reserved route:

RESERVED

No station may transition directly from UNUSED to COMPLETED.

---

# 26. Synchronization Sequence

```text
User Click
    │
    ▼
Replay Cursor Update
    │
    ├── Timeline
    ├── Replay
    ├── Railway
    ├── Inspector
    └── Summary
```

All updates must belong to the same replay cursor.

---

# 27. Replay Completion

When replay reaches the last frame:

- Stop playback.
- Preserve final frame.
- Preserve selected station.
- Preserve selected marker.
- Preserve timeline position.

Do not automatically restart.

---

# 28. Exception Flow

Possible failures:

- Missing replay
- Missing marker
- Missing decision
- Missing station
- Malformed payload
- Version mismatch

Each failure must:

1. Preserve page layout.
2. Preserve selected position.
3. Display explicit message.
4. Allow retry.

---

# 29. Recovery Rules

Retry should reload only missing resources.

Do not reset:

- replay speed
- zoom
- selected position
- selected marker

unless requested by the user.

---

# 30. State Transition Rules

Replay Playing

↓

Pause

↓

Seek

↓

Resume

↓

Complete

Every transition must be deterministic.

No hidden transitions are allowed.

---

# 31. Sequence Example

```text
BUY① Click

↓

Replay Pause

↓

Replay Cursor Move

↓

Timeline Highlight

↓

Railway Highlight

↓

Inspector Refresh

↓

Summary Refresh

↓

Animation Complete
```

---

# 32. MUST

- Replay cursor is the single source of truth.
- State transitions must be deterministic.
- Timeline, Railway and Replay must never diverge.

# SHOULD

- Preserve user context.
- Minimize unnecessary reloads.

# MUST NOT

- Reset replay unexpectedly.
- Lose selected position.
- Recalculate historical decisions.

End of Part C.


---

# 03 MARKET INTELLIGENCE INTERACTION SPECIFICATION
Version 1.0 (Part D)

> Final section of the complete Interaction Specification.

# 33. Implementation Guidelines

Implementation priorities:

1. Deterministic replay engine
2. Shared replay cursor
3. Stateless presentation components
4. Explicit state transitions
5. Component isolation

The replay cursor SHALL be the authoritative source for all synchronized UI.

---

# 34. Component Responsibilities

Market Replay
- Render historical market data.
- Never infer missing data.

Decision Railway
- Visualize decision flow.
- Never modify replay state.

Timeline
- Navigate historical events.
- Never execute replay logic directly.

Inspector
- Display details for the selected station.
- Never change station state.

Replay Controller
- Control playback only.

---

# 35. Performance Targets

Initial replay load:
<= 500 ms (cached target)

Marker selection:
<= 150 ms

Station selection:
<= 100 ms

Replay:
Smooth playback at configured speed.

---

# 36. Testing Requirements

Unit Tests

- Replay cursor
- Timeline synchronization
- Railway synchronization
- Marker selection
- Station selection
- Inspector update

Integration Tests

- Position selection
- Replay lifecycle
- Timeline interaction
- Error recovery

End-to-End Tests

Scenario 1
Select Position
Play Replay
Pause
Jump to Exit
Verify synchronization

Scenario 2
Select BUY marker
Verify inspector
Verify railway

Scenario 3
Replay reaches end
Verify completed state

Scenario 4
Replay loading failure
Verify retry path

---

# 37. Definition of Done

The interaction system is complete when:

- Replay is deterministic.
- Timeline and Railway remain synchronized.
- Inspector reflects current replay cursor.
- No historical state is modified.
- Error recovery succeeds.
- All interaction tests pass.

---

# 38. Cross Specification References

01_UI_SPEC
Defines screen layout.

02_COMPONENT_SPEC
Defines components.

04_VISUAL_GUIDELINE
Defines appearance.

05_DATA_MODEL_SPEC
Defines replay data.

06_API_SPEC
Defines interfaces.

07_RAILWAY_LOGIC_SPEC
Defines station semantics.

08_IMPLEMENTATION_GUIDE
Defines development guidance.

09_DESIGN_PHILOSOPHY
Defines architectural intent.

---

# 39. Review Checklist

Reviewers should verify:

- State transitions are deterministic.
- Synchronization is preserved.
- Replay never changes historical data.
- Components are isolated.
- Error handling is explicit.
- Performance targets are realistic.

---

# 40. Final Principles

MUST

- One replay cursor.
- One synchronized state.
- Deterministic transitions.
- Immutable historical data.

SHOULD

- Preserve user context.
- Minimize visual disruption.
- Keep interactions predictable.

MUST NOT

- Trigger live trading.
- Modify historical evidence.
- Desynchronize panels.
- Hide interaction failures.

---

End of Part D

This concludes the Interaction Specification.
