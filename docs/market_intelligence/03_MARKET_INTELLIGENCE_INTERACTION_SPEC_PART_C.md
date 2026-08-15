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
