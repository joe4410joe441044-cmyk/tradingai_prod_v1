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
