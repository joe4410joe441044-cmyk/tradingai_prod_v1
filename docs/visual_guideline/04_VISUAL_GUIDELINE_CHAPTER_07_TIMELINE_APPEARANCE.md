# 04_VISUAL_GUIDELINE

## Chapter 7 - Timeline Appearance

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter defines the visual presentation of the Timeline component.

The Timeline is the chronological view of market events and AI
decisions. It must support rapid navigation without overwhelming the
user.

------------------------------------------------------------------------

# 1. Timeline Philosophy

-   Time flows in one direction.
-   Events are visually ordered.
-   Important events are emphasized.
-   Visual noise is minimized.

------------------------------------------------------------------------

# 2. Layout

The Timeline consists of:

-   Time axis
-   Event markers
-   Current replay cursor
-   Optional zoom indicator

The replay cursor must always remain visible.

------------------------------------------------------------------------

# 3. Event Types

Supported event categories include:

-   Entry
-   Exit
-   Take Profit
-   Stop Loss
-   Partial Close
-   Flatten
-   Governance Block
-   AI Decision
-   Strategy Update
-   Detector Update
-   Market Snapshot

Each category should have a consistent visual identity.

------------------------------------------------------------------------

# 4. Marker Design

Markers should:

-   Remain readable at all zoom levels.
-   Use consistent sizing.
-   Avoid overlap where possible.

Priority order:

1.  Entry / Exit
2.  TP / SL
3.  Governance
4.  Strategy
5.  Detector

------------------------------------------------------------------------

# 5. Labels

Each visible event may display:

-   Time
-   Event name
-   Optional price
-   Optional quantity

Long text should be truncated with a tooltip.

------------------------------------------------------------------------

# 6. Hover & Selection

Hover:

-   Highlight marker
-   Show tooltip

Selection:

-   Highlight event
-   Synchronize replay
-   Synchronize Railway
-   Synchronize Inspector

------------------------------------------------------------------------

# 7. Dense Event Handling

When events become dense:

-   Merge secondary labels.
-   Preserve primary markers.
-   Avoid overlapping text.

The chronological order must never change.

------------------------------------------------------------------------

# 8. Zoom Behaviour

Zoom should affect:

-   Event spacing
-   Label visibility

Zoom must not change event order.

------------------------------------------------------------------------

# 9. Replay Cursor

The replay cursor should:

-   Be visually distinct.
-   Remain visible during playback.
-   Move smoothly.
-   Stop exactly on event timestamps.

------------------------------------------------------------------------

# 10. Review Checklist

-   Clear chronology
-   Stable replay cursor
-   Readable markers
-   Consistent event colors
-   Scalable timeline
-   No overlapping critical events

------------------------------------------------------------------------

End of Chapter 7.
