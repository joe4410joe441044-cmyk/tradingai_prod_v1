# 04_VISUAL_GUIDELINE

## Chapter 10 - Responsive Design

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter defines responsive behavior for MARKET INTELLIGENCE across
supported display sizes while preserving usability and information
hierarchy.

------------------------------------------------------------------------

# 1. Responsive Philosophy

-   Desktop is the primary target.
-   Preserve workflow before compactness.
-   Never hide critical trading information without an explicit user
    action.

------------------------------------------------------------------------

# 2. Supported Viewports

## Desktop

Primary operating environment.

## Large Desktop

Allow additional whitespace without changing hierarchy.

## Tablet

Maintain core functionality with selective panel resizing.

Mobile phones are not a primary target for this interface.

------------------------------------------------------------------------

# 3. Layout Adaptation

When horizontal space decreases:

1.  Reduce empty spacing.
2.  Reduce panel width.
3.  Collapse secondary panels.
4.  Introduce internal scrolling.

Avoid rearranging primary workflow unnecessarily.

------------------------------------------------------------------------

# 4. Panel Priorities

Highest priority:

-   Market Replay
-   Decision Railway

Medium priority:

-   Timeline
-   Inspector

Lowest priority:

-   Secondary metrics
-   Optional summaries

------------------------------------------------------------------------

# 5. Scrolling

Prefer:

-   Component-level scrolling

Avoid:

-   Entire-page horizontal scrolling

------------------------------------------------------------------------

# 6. Multi-Monitor Support

The layout should support:

-   Full-screen operation
-   High-resolution displays
-   Multi-monitor trading desks

No assumptions should be made about monitor aspect ratio.

------------------------------------------------------------------------

# 7. Window Resizing

Resizing should:

-   Preserve state
-   Preserve replay position
-   Preserve selected station
-   Avoid layout jumps

------------------------------------------------------------------------

# 8. Accessibility

Responsive behavior must not reduce:

-   Contrast
-   Readability
-   Keyboard accessibility

------------------------------------------------------------------------

# 9. Review Checklist

-   Stable resizing
-   No hidden critical information
-   Consistent hierarchy
-   Scroll behavior remains predictable
-   Desktop workflow preserved

------------------------------------------------------------------------

End of Chapter 10.
