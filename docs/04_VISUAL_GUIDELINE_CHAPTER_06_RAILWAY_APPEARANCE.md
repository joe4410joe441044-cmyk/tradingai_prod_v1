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
