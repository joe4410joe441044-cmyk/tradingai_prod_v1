# 04_VISUAL_GUIDELINE

## Chapter 9 - Motion

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter defines all motion and animation principles used throughout
MARKET INTELLIGENCE.

Motion should clarify system behavior, not entertain.

------------------------------------------------------------------------

# 1. Motion Philosophy

-   Explain state changes.
-   Reinforce user actions.
-   Preserve context.
-   Never distract from analysis.

------------------------------------------------------------------------

# 2. Animation Principles

Animations must be:

-   Short
-   Predictable
-   Consistent
-   Interruptible

Avoid chained or unnecessary effects.

------------------------------------------------------------------------

# 3. Replay Animation

Replay progresses in chronological order.

Rules:

-   Smooth cursor movement
-   Sequential Railway highlighting
-   Stable timeline updates
-   Pause immediately on user request

------------------------------------------------------------------------

# 4. Railway Animation

Station transitions:

Inactive → Active → Completed

Blocked/Error states interrupt the sequence and remain visually obvious.

------------------------------------------------------------------------

# 5. Hover Animation

Hover feedback should be subtle.

Examples:

-   Slight elevation
-   Border emphasis
-   Background tint

No dramatic scaling or rotation.

------------------------------------------------------------------------

# 6. Loading Animation

Loading indicators should:

-   Preserve layout
-   Communicate progress
-   Avoid flashing

Skeleton placeholders are preferred.

------------------------------------------------------------------------

# 7. State Change Animation

State changes should visually indicate:

-   Success
-   Warning
-   Error
-   Disabled

Animation must reinforce the semantic meaning.

------------------------------------------------------------------------

# 8. Timing Guidelines

Recommended durations:

-   Hover: 100--150 ms
-   Selection: 100--200 ms
-   Panel transitions: 150--250 ms
-   Replay progression: configurable, smooth
-   Loading transitions: ≤300 ms where possible

------------------------------------------------------------------------

# 9. Reduced Motion

Support reduced-motion preferences.

When enabled:

-   Disable non-essential animations.
-   Preserve functional transitions.
-   Maintain usability.

------------------------------------------------------------------------

# 10. Review Checklist

-   Motion supports understanding.
-   Timing is consistent.
-   Animations are interruptible.
-   Layout remains stable.
-   Reduced-motion support is respected.

------------------------------------------------------------------------

End of Chapter 9.
