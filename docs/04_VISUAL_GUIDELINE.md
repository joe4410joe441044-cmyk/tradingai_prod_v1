# 04_VISUAL_GUIDELINE

# TradingAI MARKET INTELLIGENCE

## Visual Guideline

Version 1.0 (Merged Edition)

------------------------------------------------------------------------

## Table of Contents

1.  Design Philosophy
2.  Color System
3.  Typography
4.  Layout Grid
5.  Card Design
6.  Railway Appearance
7.  Timeline Appearance
8.  Icons
9.  Motion
10. Responsive Design
11. Accessibility
12. Review Checklist

------------------------------------------------------------------------

------------------------------------------------------------------------

# 04_VISUAL_GUIDELINE

## Chapter 1 - Design Philosophy

Version 1.0

------------------------------------------------------------------------

# 1. Purpose

This chapter defines the visual philosophy of the MARKET INTELLIGENCE
interface.

The objective is not to create a futuristic dashboard, but a
professional analysis console that can be comfortably used for many
hours.

------------------------------------------------------------------------

# 2. Design Principles

## 2.1 Information First

Information has priority over decoration.

Every visual element must communicate useful information.

Decorative elements should be minimized.

------------------------------------------------------------------------

## 2.2 Long Session Readability

The interface is designed for continuous operation.

Requirements:

-   Low eye fatigue
-   Stable layout
-   Consistent spacing
-   Predictable interaction

------------------------------------------------------------------------

## 2.3 Professional Appearance

The design language combines inspiration from:

-   Bloomberg Terminal
-   Professional Trading Platforms
-   Mission Control dashboards

It intentionally avoids game-like or flashy effects.

------------------------------------------------------------------------

## 2.4 Visual Hierarchy

Priority order:

1.  Replay State
2.  Decision Railway
3.  Market Replay
4.  Timeline
5.  Inspector
6.  Secondary Metrics

Higher priority information should always be easier to locate.

------------------------------------------------------------------------

## 2.5 Consistency

Cards sharing the same purpose must use:

-   identical spacing
-   identical typography
-   identical border radius
-   identical header height

------------------------------------------------------------------------

## 2.6 Motion Philosophy

Animation exists only to explain state changes.

Animation must never distract from analysis.

------------------------------------------------------------------------

## 2.7 Color Philosophy

Color communicates meaning.

Never use color purely for decoration.

Examples:

Green = Positive Red = Negative Yellow = Warning Blue = Information Gray
= Inactive

------------------------------------------------------------------------

## 2.8 Density

The interface favors information density over excessive whitespace while
maintaining readability.

------------------------------------------------------------------------

## 2.9 Scalability

New Railway stations, detectors, or metrics must fit the design system
without redesigning the interface.

------------------------------------------------------------------------

# Review Checklist

-   Visual priorities are respected.
-   Decorative elements are minimized.
-   Motion supports understanding.
-   Colors communicate meaning.
-   Layout supports long-term monitoring.

------------------------------------------------------------------------

End of Chapter 1.

------------------------------------------------------------------------

# 04_VISUAL_GUIDELINE

## Chapter 2 - Color System

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter standardizes every color used in the MARKET INTELLIGENCE
interface.

Color exists to communicate meaning, hierarchy, and system state.

------------------------------------------------------------------------

# 1. Color Principles

-   Use color to convey information.
-   Never rely on color alone; pair with labels/icons.
-   Keep the palette limited and consistent.
-   Maintain sufficient contrast for readability.

------------------------------------------------------------------------

# 2. Background Palette

  Layer                  Purpose
  ---------------------- --------------------
  Primary Background     Application canvas
  Secondary Background   Panels
  Card Surface           Individual cards
  Elevated Surface       Popups / Inspector
  Overlay                Modal dimming

------------------------------------------------------------------------

# 3. Semantic Status Colors

  Meaning       Usage
  ------------- ----------------------------
  Success       Completed / Healthy
  Warning       Attention required
  Error         Failed / Blocked
  Information   Neutral system information
  Disabled      Inactive elements

------------------------------------------------------------------------

# 4. Railway Colors

Station states:

-   Inactive
-   Referenced
-   Active
-   Completed
-   Blocked
-   Error

Each state must have a unique, reusable semantic color.

------------------------------------------------------------------------

# 5. Timeline Colors

Timeline events should distinguish:

-   Entry
-   Exit
-   Take Profit
-   Stop Loss
-   Manual Close
-   Flatten
-   Governance Block
-   Replay Position

------------------------------------------------------------------------

# 6. Marker Colors

Marker colors must remain consistent across:

-   Order Book
-   Replay
-   Timeline

The same event must never appear with different colors.

------------------------------------------------------------------------

# 7. Interactive States

Every interactive element defines:

-   Default
-   Hover
-   Focus
-   Active
-   Disabled

Transitions should be subtle and under 200 ms.

------------------------------------------------------------------------

# 8. Charts & Metrics

Metric colors should communicate trend, not decoration.

Recommended semantic groups:

-   Positive
-   Neutral
-   Negative
-   Unknown

------------------------------------------------------------------------

# 9. Accessibility

Color combinations must satisfy accessible contrast ratios.

Critical information must never depend solely on color.

------------------------------------------------------------------------

# 10. Review Checklist

-   Consistent semantic mapping
-   No conflicting color meanings
-   Accessible contrast
-   Stable dark theme
-   Uniform interaction states

------------------------------------------------------------------------

End of Chapter 2.

------------------------------------------------------------------------

# 04_VISUAL_GUIDELINE

## Chapter 3 - Typography

Version 1.0

# Purpose

Typography is the primary communication layer of MARKET INTELLIGENCE.

## Typography Principles

-   Readability before style
-   Consistent hierarchy
-   Numeric alignment
-   Minimal visual noise

## Font Family

-   Primary UI font
-   Numeric font
-   Monospace for debug/logs

## Font Scale

-   Page Title
-   Card Title
-   Section Header
-   Body
-   Caption
-   Tooltip

## Font Weight

Regular, Medium, Semi-Bold, Bold.

## Numeric Display

-   Right aligned
-   Consistent decimal precision
-   Thousands separator where appropriate
-   Preserve sign

## Tables

-   Text left aligned
-   Numbers right aligned
-   Consistent row height

## Timeline

Short labels with aligned timestamps.

## Inspector

Hierarchy: 1. Station 2. Section 3. Values 4. Notes 5. Debug

## Debug Text

Use monospace for JSON, IDs, payloads and timing.

## Accessibility

-   Clear hierarchy
-   Scalable text
-   High readability

## Review Checklist

-   Consistent hierarchy
-   Numeric alignment
-   Readable debug output

End of Chapter 3.

------------------------------------------------------------------------

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

------------------------------------------------------------------------

# 04_VISUAL_GUIDELINE

## Chapter 5 - Card Design

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter defines the visual and structural standards for every card
used in MARKET INTELLIGENCE.

Cards are the primary information containers and must behave
consistently across the interface.

------------------------------------------------------------------------

# 1. Card Philosophy

-   One responsibility per card.
-   Stable dimensions whenever possible.
-   Clear visual separation.
-   Minimal decorative styling.

------------------------------------------------------------------------

# 2. Card Structure

Every card consists of:

1.  Header
2.  Body
3.  Optional Footer

The structure must remain consistent across all cards.

------------------------------------------------------------------------

# 3. Header

The header should contain:

-   Title
-   Optional subtitle
-   Status indicator
-   Optional actions

Rules:

-   Consistent height
-   Consistent horizontal padding
-   Divider between header and body

------------------------------------------------------------------------

# 4. Body

The body contains the primary content.

Requirements:

-   Consistent internal spacing
-   Predictable alignment
-   No overlapping elements
-   Independent scrolling when required

------------------------------------------------------------------------

# 5. Footer

Use only when additional actions or summaries are needed.

Examples:

-   Replay controls
-   Pagination
-   Totals

------------------------------------------------------------------------

# 6. Borders

Borders should:

-   Clearly define card boundaries.
-   Avoid excessive visual weight.
-   Be consistent throughout the application.

------------------------------------------------------------------------

# 7. Corner Radius

Use one standard radius for all primary cards.

Avoid mixing multiple corner styles.

------------------------------------------------------------------------

# 8. Shadows

Shadows should communicate elevation only.

Avoid heavy shadows that reduce readability.

------------------------------------------------------------------------

# 9. Internal Spacing

Maintain a consistent spacing scale for:

-   Header padding
-   Body padding
-   Section gaps
-   Item spacing

------------------------------------------------------------------------

# 10. Card States

Supported states:

-   Default
-   Selected
-   Focused
-   Disabled
-   Loading
-   Error

Each state must have a clearly distinguishable appearance.

------------------------------------------------------------------------

# 11. Expand / Collapse

Expandable cards must:

-   Preserve header position.
-   Animate smoothly.
-   Preserve user context.

------------------------------------------------------------------------

# 12. Review Checklist

-   Consistent structure
-   Consistent spacing
-   Stable layout
-   Clear hierarchy
-   Uniform interaction states

------------------------------------------------------------------------

End of Chapter 5.

------------------------------------------------------------------------

# 04_VISUAL_GUIDELINE

## Chapter 6 - Railway Appearance

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter defines the complete visual language of the Decision
Railway.

The Railway is the visual representation of the AI decision pipeline and
must remain readable, deterministic, and scalable.

------------------------------------------------------------------------

# 1. Railway Philosophy

-   One station = one processing stage.
-   Visual flow follows execution order.
-   Decorative effects are secondary to clarity.

------------------------------------------------------------------------

# 2. Station Shape

Every station should use:

-   Consistent size
-   Consistent border radius
-   Centered icon
-   Label beneath or beside the station

Shapes must not vary by algorithm type.

------------------------------------------------------------------------

# 3. Station Spacing

Maintain equal spacing between adjacent stations.

Connector lengths should remain visually balanced.

------------------------------------------------------------------------

# 4. Connectors

Connectors represent processing flow.

States:

-   Inactive
-   Active
-   Completed
-   Blocked

Connector style must match station state.

------------------------------------------------------------------------

# 5. Station States

Supported visual states:

-   Inactive
-   Referenced
-   Active
-   Completed
-   Blocked
-   Error
-   Disabled

Only one station may be Active at a time during replay.

------------------------------------------------------------------------

# 6. Labels

Each station must display:

-   Name
-   Optional short status
-   Tooltip for detailed information

Avoid long labels inside the station.

------------------------------------------------------------------------

# 7. Animation

Replay animation should:

-   Progress station by station
-   Highlight active connector
-   Preserve completed history
-   Stop cleanly at the final state

Animation should explain flow, never distract.

------------------------------------------------------------------------

# 8. Icons

Icons should communicate processing role, not decoration.

Examples:

-   Runtime
-   Strategy
-   AI
-   Governance
-   Execution

Use a consistent icon style across all stations.

------------------------------------------------------------------------

# 9. Scalability

Future stations must fit into the Railway without redesign.

When space is limited:

-   Compress spacing first.
-   Scroll only as a last resort.

------------------------------------------------------------------------

# 10. Review Checklist

-   Uniform station sizing
-   Consistent connector spacing
-   Clear active state
-   Readable labels
-   Predictable animation
-   Scalable layout

------------------------------------------------------------------------

End of Chapter 6.

------------------------------------------------------------------------

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

------------------------------------------------------------------------

# 04_VISUAL_GUIDELINE

## Chapter 8 - Icons

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter defines the icon system used throughout MARKET
INTELLIGENCE.

Icons reinforce meaning and improve scanning speed. They never replace
text for critical information.

------------------------------------------------------------------------

# 1. Icon Philosophy

-   Functional before decorative.
-   Consistent visual language.
-   Simple silhouettes.
-   Recognizable at small sizes.

------------------------------------------------------------------------

# 2. Icon Categories

## Navigation

-   Back
-   Forward
-   Home

## Replay

-   Play
-   Pause
-   Stop
-   Previous
-   Next

## Railway

-   Runtime
-   Strategy
-   LSTM
-   LLM
-   Consensus
-   Governance
-   Execution

## Status

-   Success
-   Warning
-   Error
-   Information
-   Disabled

## Actions

-   Refresh
-   Search
-   Filter
-   Expand
-   Collapse
-   Settings

------------------------------------------------------------------------

# 3. Sizing

Use a limited icon scale:

-   Small
-   Medium
-   Large

Do not arbitrarily resize icons.

------------------------------------------------------------------------

# 4. Alignment

Icons should align with text baselines.

Maintain consistent spacing between icon and label.

------------------------------------------------------------------------

# 5. States

Every interactive icon supports:

-   Default
-   Hover
-   Focus
-   Active
-   Disabled

State changes should remain subtle.

------------------------------------------------------------------------

# 6. Accessibility

Icons conveying important information must include:

-   Text label or
-   Tooltip or
-   Accessible name

Never rely solely on icon shape.

------------------------------------------------------------------------

# 7. Review Checklist

-   Consistent icon family
-   Proper alignment
-   Consistent sizing
-   Accessible labeling
-   Appropriate semantic usage

------------------------------------------------------------------------

End of Chapter 8.

------------------------------------------------------------------------

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

------------------------------------------------------------------------

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

------------------------------------------------------------------------

# 04_VISUAL_GUIDELINE

## Chapter 11 - Accessibility

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter defines accessibility requirements for the MARKET
INTELLIGENCE interface.

Accessibility ensures the interface remains usable for a broad range of
users without reducing analytical capability.

------------------------------------------------------------------------

# 1. Accessibility Philosophy

-   Accessibility is a core design requirement.
-   Features should enhance usability without compromising information
    density.
-   Accessibility improvements should benefit all users where possible.

------------------------------------------------------------------------

# 2. Contrast

Requirements:

-   Text must maintain sufficient contrast against its background.
-   Critical status indicators must remain distinguishable.
-   Decorative colors must never reduce readability.

------------------------------------------------------------------------

# 3. Keyboard Accessibility

Every primary interaction must be operable using a keyboard.

Required support:

-   Tab navigation
-   Arrow key navigation where appropriate
-   Escape to close transient UI
-   Enter / Space for activation

------------------------------------------------------------------------

# 4. Focus Indicators

Focused elements must display a clear visual indicator.

Focus styles should:

-   Be visible on all backgrounds.
-   Remain consistent across components.
-   Never rely only on color changes.

------------------------------------------------------------------------

# 5. Color Independence

Important information must not depend solely on color.

Use combinations of:

-   Labels
-   Icons
-   Shape
-   Position
-   Color

------------------------------------------------------------------------

# 6. Target Size

Interactive controls should provide comfortable pointer targets.

Avoid placing controls too closely together.

------------------------------------------------------------------------

# 7. Screen Readers

Provide meaningful names for:

-   Buttons
-   Railway stations
-   Timeline events
-   Replay controls

Decorative elements should be ignored where appropriate.

------------------------------------------------------------------------

# 8. Reduced Motion

Respect system preferences for reduced motion.

Disable non-essential animations while preserving functional
transitions.

------------------------------------------------------------------------

# 9. Review Checklist

-   Sufficient contrast
-   Keyboard operable
-   Clear focus indicators
-   Color-independent communication
-   Screen reader compatibility
-   Reduced-motion support

------------------------------------------------------------------------

End of Chapter 11.

------------------------------------------------------------------------

# 04_VISUAL_GUIDELINE

## Chapter 12 - Review Checklist

Version 1.0

------------------------------------------------------------------------

# Purpose

This chapter defines the review process and acceptance criteria for the
MARKET INTELLIGENCE visual design.

------------------------------------------------------------------------

# 1. Visual Consistency

Verify:

-   Typography hierarchy
-   Color consistency
-   Card consistency
-   Railway consistency
-   Timeline consistency

------------------------------------------------------------------------

# 2. Layout Review

Confirm:

-   Grid alignment
-   Stable spacing
-   Predictable resizing
-   No layout shifts

------------------------------------------------------------------------

# 3. Component Review

Each component should be checked for:

-   Appearance
-   Interaction feedback
-   Visual hierarchy
-   Accessibility

------------------------------------------------------------------------

# 4. Motion Review

Review:

-   Animation timing
-   Replay progression
-   Hover feedback
-   Loading transitions

------------------------------------------------------------------------

# 5. Accessibility Review

Verify:

-   Contrast
-   Keyboard navigation
-   Focus indicators
-   Reduced motion
-   Screen reader support

------------------------------------------------------------------------

# 6. Definition of Done

The visual guideline is considered complete when:

-   All chapters are implemented.
-   Design language is consistent.
-   Accessibility requirements are met.
-   Motion is predictable.
-   Visual review passes without major findings.

------------------------------------------------------------------------

# 7. Final Approval Checklist

The reviewer should confirm:

-   Consistent visual language
-   Predictable interaction
-   Stable layout
-   Scalable design
-   Long-session readability

------------------------------------------------------------------------

End of Chapter 12.
