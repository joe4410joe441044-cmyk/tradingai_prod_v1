# 04_VISUAL_GUIDELINE

## Chapter 4 - Layout Grid

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter defines the layout grid system for MARKET INTELLIGENCE to
ensure consistent alignment, spacing, and scalability.

------------------------------------------------------------------------

# 1. Grid Philosophy

-   Use a predictable grid.
-   Prioritize readability over maximum density.
-   Components align to shared grid lines.

------------------------------------------------------------------------

# 2. Desktop Grid

Recommended structure:

-   12-column grid
-   Consistent gutters
-   Fixed outer margins
-   Flexible content width

------------------------------------------------------------------------

# 3. Primary Layout

Left Panel: - Market Replay - Order Book - Recent Trades

Right Panel: - Decision Railway - Inspector - Decision Summary

Bottom: - Timeline

------------------------------------------------------------------------

# 4. Alignment Rules

-   Card headers align horizontally.
-   Card bodies begin on the same baseline where practical.
-   Numeric columns align vertically.

------------------------------------------------------------------------

# 5. Spacing System

Use a consistent spacing scale.

Apply it to:

-   Card padding
-   Component gaps
-   Section spacing
-   Header spacing
-   Timeline spacing

Avoid arbitrary spacing values.

------------------------------------------------------------------------

# 6. Card Sizing

Cards should define:

-   Minimum width
-   Preferred width
-   Maximum expansion
-   Minimum height

Large cards should expand before creating new rows.

------------------------------------------------------------------------

# 7. Responsive Rules

Desktop is the primary target.

Tablet: - Preserve hierarchy. - Collapse secondary panels only when
necessary.

Avoid horizontal scrolling for primary workflows.

------------------------------------------------------------------------

# 8. Overflow

Content overflow should:

-   Scroll within the component.
-   Never shift surrounding layout.
-   Preserve headers.

------------------------------------------------------------------------

# 9. Layout Stability

Loading, replay, and inspector updates must not cause layout jumps.

Reserve space for dynamic content where possible.

------------------------------------------------------------------------

# 10. Review Checklist

-   Grid consistency
-   Alignment correctness
-   Stable spacing
-   Predictable resizing
-   No unnecessary layout shifts

------------------------------------------------------------------------

End of Chapter 4.
