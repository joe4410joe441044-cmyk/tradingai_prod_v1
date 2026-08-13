# 01_SUPERVISOR_Master_Specification

```text
Version: 1.1
Status: IMPLEMENTATION BASELINE
Initial Agents: Master Supervisor + MM Supervisor
Initial Runtime Mode: SHADOW
```

## 1. Purpose

SUPERVISOR is the operational oversight layer for TradingAI.

Its first version consists of exactly two agents:

1. **Master Supervisor Agent**
2. **MM Supervisor Agent**

The Master represents the operator's highest-level philosophy: survive for the long term, protect capital when conditions deteriorate, actively capture valid edge when conditions are healthy, and allow controlled compounding as capital grows.

The MM Supervisor is the first specialist Supervisor. It evaluates money-management state and produces a structured professional assessment. It does not place orders or directly change runtime settings.

The UI and runtime must be extensible so Strategy, Execution, and System Health Supervisors can be added later without rebuilding the Master or the page architecture.

## 2. Initial Architecture

```text
Human Operator
    ↓ conversation / policy
Master Supervisor Agent
    ↓ structured request
MM Supervisor Agent
    ↓ structured assessment
Existing Python MM Authority
    ↓ deterministic calculation
Hard Safety Limits
    ↓
Governance
    ↓
Execution
```

The two agents are an oversight and explanation layer. They are not a replacement for deterministic Python authority.

## 3. Operator Constitution

The following principles are authoritative:

- Long-term survival is an absolute condition.
- Capital protection is a means, not the final purpose.
- When verified edge, capital state, and system health are favorable, TradingAI should pursue profit actively within policy limits.
- Short-term Micro Edge profits are accumulated into long-term growth.
- Compounding may increase future risk capacity only inside explicit user policy and hard safety limits.
- When drawdown, loss streak, estimate uncertainty, execution quality, or expected value deteriorates, risk must contract.
- When ruin risk or a hard limit is breached, profit opportunity never overrides capital protection.

The agents may interpret this constitution for operational advice, but may not rewrite it autonomously.

## 4. Authority Hierarchy

From highest safety authority to lowest:

```text
Emergency / Hard Safety Limits
    ↓
Governance
    ↓
User Policy
    ↓
Deterministic Python MM Engine
    ↓
Master Supervisor operational policy
    ↓
MM Supervisor assessment
```

The Master has the highest Agent-level operational-policy role. It does not have the highest system safety authority.

## 5. Master Supervisor Agent

### Responsibilities

- Act as the normal conversation entry point for the operator.
- Summarize current TradingAI operational condition.
- Integrate MM Supervisor assessment with available system state.
- Select an advisory overall posture.
- Explain why the posture was selected and what would change it.
- Identify whether human attention or approval is required.
- Preserve an auditable decision record.

### Initial Postures

```text
GROWTH
NORMAL
CAUTION
DEFENSIVE
LOCKED
UNKNOWN
```

`GROWTH` permits only a proposal to use additional capacity already allowed by policy and Python. It never expands a hard limit.

### Prohibited Actions

- Submit, cancel, replace, or manage an order.
- Directly calculate executable quantity when Python authority exists.
- Override Emergency, Governance, Ruin Guard, drawdown limits, exposure limits, or user policy.
- Upgrade missing or stale data into a healthy state.
- Treat an LLM inference as an authoritative account or runtime fact.
- Modify its constitution without an explicit, validated human policy change.

## 6. MM Supervisor Agent

### Responsibilities

- Read the authoritative MM snapshot.
- Assess capital condition, drawdown, current MM regime, risk capacity, exposure, position capacity, compounding state, and Ruin Guard state.
- Compare short-, medium-, and long-window performance only when authoritative statistics are available.
- Produce a structured assessment for the Master or operator.
- Explain causes, uncertainty, recovery conditions, and recommended risk direction.

### Prohibited Actions

- Change risk percentage, leverage, exposure, MM regime, or position size directly.
- Reimplement or contradict deterministic MM calculations.
- Infer missing equity, available capital, stop, entry, risk budget, or performance statistics.
- Increase risk beyond policy or Python-approved capacity.
- Control Governance or Execution.

## 7. Existing MM Authority Inputs

Supervisor must consume existing contracts rather than duplicate their calculations.

Minimum target snapshot:

```text
capitalAuthority
equity
availableCapital
mmMode
mmRegime
riskBudget
maxPositionNotional
maxTotalExposure
remainingExposure
theoreticalMaxConcurrentPositions
executableMaxConcurrentPositions
remainingPositionCapacity
ruinGuardStatus
compoundingEnabled
policyVersion
evaluatedAt
dataFreshness
reasonCodes
```

When a field is unavailable, the value remains `null` or `UNKNOWN` with a reason code. The Agent must not guess.

## 8. Structured MM Assessment

```json
{
  "schemaVersion": 1,
  "agent": "MM_SUPERVISOR",
  "mode": "SHADOW",
  "assessmentState": "NORMAL|CAUTION|DEFENSIVE|LOCKED|UNKNOWN",
  "recommendedRiskDirection": "INCREASE_WITHIN_POLICY|MAINTAIN|REDUCE|PAUSE|UNKNOWN",
  "recommendedRiskMultiplier": null,
  "capitalCondition": "HEALTHY|DEGRADED|CRITICAL|UNKNOWN",
  "confidence": 0.0,
  "reasons": [],
  "uncertainties": [],
  "recoveryConditions": [],
  "sourceEvaluatedAt": null,
  "assessedAt": null
}
```

In v1, `recommendedRiskMultiplier` is advisory only. A non-null value must still be validated by deterministic Python.

## 9. Structured Master Decision

```json
{
  "schemaVersion": 1,
  "agent": "MASTER_SUPERVISOR",
  "mode": "SHADOW",
  "overallPosture": "GROWTH|NORMAL|CAUTION|DEFENSIVE|LOCKED|UNKNOWN",
  "tradingRecommendation": "CONTINUE|CONTINUE_REDUCED|PAUSE_NEW_ENTRIES|STOP|UNKNOWN",
  "mmRecommendation": "INCREASE_WITHIN_POLICY|MAINTAIN|REDUCE|PAUSE|UNKNOWN",
  "humanAttention": "NOT_REQUIRED|REVIEW|APPROVAL_REQUIRED|IMMEDIATE_ACTION",
  "reasons": [],
  "conflicts": [],
  "uncertainties": [],
  "nextReviewConditions": [],
  "sourceEvaluatedAt": null,
  "decidedAt": null
}
```

## 10. Operating Modes

### SHADOW — initial and mandatory

- Agent decisions are generated and logged.
- No MM setting, runtime state, order, or policy is changed.
- The operator can compare Agent judgment with actual outcomes.

### ADVISORY

- The UI may present an explicit proposal to the operator.
- Application requires a separate human confirmation path.
- Python and safety validation remain mandatory.

### ACTIVE / LIMITED_AUTO — out of initial implementation scope

- May be considered only after a defined validation sample and acceptance criteria pass.
- Must use bounded, reversible changes.
- Must never modify hard safety limits.

### Mode Transition Rules

```text
SHADOW → ADVISORY → ACTIVE
```

- Direct `SHADOW → ACTIVE` transition is prohibited.
- `ACTIVE → SHADOW`, `ACTIVE → ADVISORY`, and `ADVISORY → SHADOW` are immediate safety-side transitions.
- `SHADOW → ADVISORY` requires explicit human confirmation.
- `ADVISORY → ACTIVE` requires a pre-flight safety check and explicit human confirmation.
- An Agent may recommend a stronger mode but cannot promote itself.
- The system may automatically demote `ACTIVE → SHADOW` on failure.
- Automatic promotion to ACTIVE is prohibited.
- Switching to SHADOW disables new Supervisor-driven changes; it does not stop TradingAI or automatically unwind existing positions.

Before ACTIVE, the pre-flight check must confirm at minimum:

```text
MM authority available
capital data fresh
Governance operational
Emergency state safe
hard limits loaded
Agent contracts valid
decision logging operational
no unresolved policy conflict
```

## 11. Human Conversation Interface

A new top-level browser navigation item is added:

```text
SUPERVISOR
```

### 11.1 Primary UI Principle

The SUPERVISOR page exists to reduce information overload, not to duplicate the Dashboard.

Default view shows only:

```text
Current overall state
Current operational posture
Human action required / not required
One short Master explanation
Master chat
Collapsed specialist Supervisor rows
```

Equity, drawdown, risk budget, exposure, reason codes, model metadata, runtime contracts, and diagnostics remain hidden until requested.

### 11.2 Progressive Disclosure

Information is presented in three levels:

```text
LEVEL 1  Conclusion
         state / posture / human action / short explanation

LEVEL 2  Reasons
         specialist assessment / key causes / recovery conditions

LEVEL 3  Evidence and Diagnostics
         numeric values / authority source / freshness / history / logs
```

Repeated unchanged decisions, successful background polling, and low-level internal logs are not promoted to the default view. The default view highlights state changes, required human action, safety degradation, and material decisions.

### 11.3 Stacked Conversation Layout

The page uses two vertically stacked conversations in v1:

```text
MASTER SUPERVISOR CHAT
  TradingAI-wide state, attack/defense posture, operational summary,
  cross-domain questions, and overall requests

MM SUPERVISOR CHAT
  risk, capital, lot/quantity policy, drawdown, exposure,
  compounding, Ruin Guard, and MM-specific explanations
```

Master chat is the first and primary entry point. MM Supervisor is placed below it and may be collapsed by default. Each chat keeps its own conversation history. Important specialist findings can be referenced by Master without copying the entire specialist conversation into the Master thread.

### 11.4 Future Specialist Supervisors

The layout must accept additional collapsed specialist sections below Master:

```text
Master Supervisor
├─ MM Supervisor               v1
├─ Strategy Supervisor         future
├─ Execution Supervisor        future
└─ System Health Supervisor    future
```

Specialists are registered through a common Supervisor Registry/contract rather than hard-coded into Master logic. Each registration defines identity, domain, allowed data, output schema, authority, prohibited actions, current state, and conversation endpoint.

When specialists increase, the default UI shows only the count and number requiring attention until the operator expands the list.

### 11.5 Voice Input

Master and MM Supervisor chat inputs include a microphone button in v1.

Initial behavior:

```text
press microphone
→ capture speech
→ convert to editable text
→ display recognized text
→ human sends or corrects it
```

- Voice input does not directly apply a setting.
- Risk, percentage, leverage, quantity, mode, symbol, and stop-related instructions require text confirmation before submission.
- The initial release may use browser speech recognition behind an adapter; a local speech-to-text provider may replace it later.
- Text response is the default. Voice playback is optional and out of initial scope.

### 11.6 Natural-Language Operational Requests

Natural-language requests never write arbitrary internal values directly.

```text
Human request
→ Master interprets intent
→ relevant specialist produces a structured proposal
→ deterministic Python validates and calculates
→ Hard Safety / Governance validates
→ UI shows exact before/after change and expected effect
→ authorization required by the current mode
→ approved configuration interface applies the change
→ audit record is written
```

Conversation may propose changes only through allow-listed configuration commands. It does not edit source code, secrets, exchange credentials, raw database fields, Governance state, or Emergency state.

### 11.7 Compact Mode Control

The current mode is always visible but visually compact:

```text
MODE: SHADOW
automatic operational effect: OFF
```

Clicking it opens the mode-control panel. ACTIVE additionally displays its exact allow-listed authority. Mode controls must not dominate the normal conversation UI.

### 11.8 v1 Page Sketch

```text
SUPERVISOR                                      MODE: SHADOW

State: NORMAL        Posture: NORMAL        Human action: NONE
Master: TradingAI is operating normally. No important change is required.

MASTER SUPERVISOR
[conversation]
[microphone] [message input] [send]

MM SUPERVISOR                         NORMAL   [open / close]
[specialist conversation when expanded]
[microphone] [message input] [send]

[Details]
  MM assessment
  reasons and recovery conditions
  current settings
  decision/change history
  numeric evidence
  system/runtime
  diagnostics
```

## 12. AI Advisor Boundary

AI Advisor remains separate during Supervisor validation.

```text
SUPERVISOR
  Operational monitoring, posture, MM oversight, explanation

AI ADVISOR
  Research, design, improvement proposals, post-hoc review,
  second opinion on Supervisor decisions
```

AI Advisor has no operational authority and does not replace the Master. After sufficient validation, overlapping daily-consultation features may be reviewed for consolidation, but no consolidation is part of v1.

## 13. Failure-Safe Rules

- Missing authority → `UNKNOWN`, never healthy by default.
- Stale snapshot → no increase recommendation.
- Conflicting snapshots → `REVIEW` or stronger human attention.
- Agent timeout or invalid schema → preserve prior runtime settings; record failure.
- Local model unavailable → Supervisor unavailable; TradingAI deterministic runtime remains independent.
- Prompt or conversation request conflicting with hard policy → reject and explain.
- Every assessment records model/provider version, prompt/contract version, source timestamp, and output validation result.

## 14. Initial Model and Framework Direction

The preferred zero-additional-API-cost starting point is:

```text
LangGraph
  + Ollama-compatible local model
  + strict typed schemas
  + existing TradingAI read-only APIs
```

The model-provider boundary must remain replaceable. Model choice is not authoritative; contract validation and system safety boundaries are authoritative.

## 15. Implementation Phases

```text
SUP-0A  Existing Authority / AI Advisor Audit
SUP-0B  Supervisor Contracts and Failure-Safe Validation
SUP-1A  SUPERVISOR Navigation and Read-only Page Shell
SUP-1B  Read-only Supervisor Snapshot API
SUP-1C  MM Supervisor SHADOW Runtime
SUP-1D  Master Supervisor SHADOW Runtime
SUP-1E  Conversation API and UI
SUP-1F  Decision History / Replay / Audit
SUP-2A  Paper Validation Harness
SUP-2B  ADVISORY Human-Approval Flow
SUP-3A  ACTIVE / LIMITED_AUTO Design Review — not automatically authorized
SUP-3B  ACTIVE / LIMITED_AUTO Activation
SUP-3C  ACTIVE Validation and Authority Review
```

## 16. First Work Order — SUP-0A

### Objective

Audit the existing TradingAI repository without changing runtime behavior, and produce the exact connection map required for Supervisor implementation.

### Required Inspection

1. Git branch, HEAD, origin/main, ahead/behind, and dirty files.
2. Existing frontend navigation and page-switching mechanism.
3. Existing AI Advisor page, backend routes, prompts, model provider, tools, memory/context, and authority.
4. Existing Money Management status/configuration/history/simulation/position-preview APIs.
5. Existing AUTO MM capital-eligibility contract and authoritative field producers.
6. Existing runtime status, Governance, Emergency, and data-freshness sources.
7. Current dependency files and whether LangGraph, Pydantic, Ollama client, or equivalent components already exist.
8. Test conventions for frontend navigation, API contracts, and MM runtime.
9. Existing reusable chat, accordion/disclosure, microphone, confirmation-dialog, and history components.
10. The safest integration point for a common Supervisor Registry that supports later specialist additions.

### Deliverable

Produce a report containing:

- Git start state
- Existing architecture map with file paths and symbols
- Authoritative Supervisor input table: field → producer → API → freshness rule
- AI Advisor current role/authority audit
- Reusable components and prohibited duplication
- Proposed exact files for `SUP-0B` and `SUP-1A`
- Findings by severity
- PASS / PASS WITH FINDINGS / FAIL verdict

### Restrictions

- No implementation changes.
- No commit, push, deploy, package installation, service restart, or environment-variable change.
- Do not expose API keys, secrets, private endpoints, or full environment contents.
- Do not change Money Management, Governance, Execution, AI Advisor, or current UI behavior.

## 17. Completion Definition for v1

v1 is complete only when:

- The SUPERVISOR tab is available in the browser.
- Master and MM Supervisor conversations work.
- Master chat appears first and MM Supervisor chat appears below it.
- The default page shows only state, posture, human action, and a short Master explanation.
- Detailed values, reasons, history, and diagnostics remain behind explicit disclosure controls.
- Both chat inputs provide editable, confirm-before-send voice transcription.
- Additional specialist Supervisors can be registered without rewriting Master or the page structure.
- Both agents operate in SHADOW mode.
- All displayed facts originate from identified authoritative sources.
- Structured outputs reject invalid values and missing fields safely.
- No Agent can change MM, Governance, or Execution.
- Decisions and failures are logged and reviewable.
- Existing TradingAI runtime continues to work when the Agent service is unavailable.

## 18. Final Responsibility Boundary

> The human defines the constitution. The Master interprets overall operational posture. The MM Supervisor provides professional money-management assessment. Python calculates and validates. Hard Safety and Governance retain final authority. Execution alone submits orders.
