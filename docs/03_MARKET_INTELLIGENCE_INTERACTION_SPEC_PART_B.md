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
