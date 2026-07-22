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
