# 00_SPEC_INDEX.md

# TradingAI MARKET INTELLIGENCE

## Specification Index

**Version:** 1.0

------------------------------------------------------------------------

## Purpose

This document is the master index for all MARKET INTELLIGENCE
specifications.

When starting a new ChatGPT/Codex/Claude conversation, attach this file
first, then attach only the specification document(s) required for the
current task.

------------------------------------------------------------------------

# Specification List

## 01_UI_SPEC.md

**Purpose**

Defines the overall screen layout and page structure.

**Scope**

-   Screen layout
-   Replay Panel
-   Decision Railway
-   Timeline
-   Inspector
-   Summary
-   Navigation

**Does NOT define**

-   API
-   Data model
-   Business logic

------------------------------------------------------------------------

## 02_COMPONENT_SPEC.md

**Purpose**

Defines every UI component and its responsibilities.

**Scope**

-   Replay Panel
-   Order Book
-   Recent Trades
-   Railway
-   Station
-   Timeline
-   Inspector
-   Replay Controller
-   Summary

------------------------------------------------------------------------

## 03_INTERACTION_SPEC.md

**Purpose**

Defines every user interaction.

**Scope**

-   Click
-   Replay
-   Timeline
-   Marker
-   Keyboard
-   Mouse
-   Hover
-   Zoom
-   Synchronization
-   State Machine
-   Error Recovery

------------------------------------------------------------------------

## 04_VISUAL_GUIDELINE.md

**Purpose**

Defines the design system.

**Scope**

-   Colors
-   Typography
-   Grid
-   Cards
-   Icons
-   Animation
-   Spacing
-   Responsive Rules

------------------------------------------------------------------------

## 05_DATA_MODEL_SPEC.md

**Purpose**

Defines replay and decision data structures.

**Scope**

-   Position
-   Timeline
-   Replay
-   Events
-   Decision
-   Railway
-   Inspector
-   Marker

------------------------------------------------------------------------

## 06_API_SPEC.md

**Purpose**

Defines backend interfaces.

**Scope**

-   REST API
-   WebSocket
-   Request
-   Response
-   Error Model
-   Versioning

------------------------------------------------------------------------

## 07_RAILWAY_LOGIC_SPEC.md

**Purpose**

Defines the meaning and processing rules for every Decision Railway
station.

**Scope**

-   Python Runtime
-   Runtime Adapter
-   Feature Builder
-   Strategy
-   LSTM
-   LLM
-   Consensus
-   Governance
-   Execution

------------------------------------------------------------------------

## 08_IMPLEMENTATION_GUIDE.md

**Purpose**

Development guide for implementation.

**Scope**

-   Coding Rules
-   Naming
-   Performance
-   Testing
-   Review Process

------------------------------------------------------------------------

## 09_DESIGN_PHILOSOPHY.md

**Purpose**

Records the architectural philosophy behind MARKET INTELLIGENCE.

**Scope**

-   Design Principles
-   UX Philosophy
-   Replay Philosophy
-   Railway Philosophy
-   Long-term Vision

------------------------------------------------------------------------

# Recommended Workflow

1.  Read this index.
2.  Open only the required specification(s).
3.  Implement one chapter at a time.
4.  Submit changes for review.
5.  Move to the next chapter only after approval.

------------------------------------------------------------------------

# New Chat Template

``` text
TradingAI

Reference Document:
00_SPEC_INDEX.md

Target Specification:
03_INTERACTION_SPEC.md

Target Chapter:
Chapter 7 - Replay Controller

Objective:
Implement only Chapter 7.

Do NOT modify:
- UI Layout
- API
- Railway Logic
- Timeline

Definition of Done:
Fully satisfies the referenced chapter.

commit / push / deploy prohibited.
```

------------------------------------------------------------------------

# Revision History

**v1.0**

-   Initial specification index created.
-   Covers specifications 01 through 09.
