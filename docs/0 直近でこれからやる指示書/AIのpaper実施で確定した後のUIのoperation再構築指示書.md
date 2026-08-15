# TradingAI — AI採否決定後の再開指示書

作成日: 2026-08-12
用途: 現在進行中のPAPER実地試験が完了した後、新しいGPTへこの文書を渡して開発を再開するための引継ぎ指示書

---

## 0. 新しいGPTへの指示

この文書は、TradingAI の以下3系統を統合して再開するための現在地点である。

1. AUTO MARKET SELECTION
2. Dashboard OPERATION / Pre-Start Setup Flow
3. Trading Decision Pipeline（AI Reviewを残すか外すか）

現在、別のGPTで Production PAPER 実地試験を実施しており、

**AI ReviewをTrading Decision本線に残すか、外すか**

を検証中である。

その結論が出るまでは、BOT START本線・Pre-Start Automation backend・AMS mainline integrationを確定しない。

再開時には、必ず最初にPAPER試験の最新Final Reportをユーザーから受け取り、その結果をこの文書へ適用してから次工程へ進むこと。

---

# 1. 現在のAUTO MARKET SELECTION状態

AMS Completion Audit:

`AMS_V1_PRODUCTION_VALIDATION_INCOMPLETE`

その後、仕様上の最後の実装gapだった Micro Edge Suitability Deep Analysis Contract を修正。

最新結果:

`PASS_DEEP_ANALYSIS_FAIL_CLOSED`

確認済み:

- Market Universe
- Scanner
- Capital Eligibility
- Candidate Ranking
- Active Symbol Authority
- Active Market Comparison
- Micro Edge Suitability
- Deep Analysis
- Position / Pending authority
- Official MM integration
- Governance / Emergency precedence
- Anti-Flapping
- ObservationId / CAS
- Live Read Only
- Operator Approval
- Live AUTO Runtime
- Phase-1
- Phase-2
- LiveSymbolSwitchPermission
- SafeSymbolSwitch
- Restart Safety
- Order Firewall

Micro Edge Deep Analysisについては:

- empty detector evidence → fail closed
- deep analysis bypass option removed
- missing suitability identity → Phase-1 block
- Phase-2 identity mismatch → block
- permission binds suitability identity
- commit-time CAS validates suitability
- changed/missing evidence → SafeSwitch前にreject

Regression:

`475 passed`

---

# 2. AMS Standalone Production Trial結果

Task:

`AMS-FINAL-1C`

Result:

`NO_ELIGIBLE_SWITCH_OBSERVED`

Standalone verdict:

`IMPLEMENTED_AND_TESTED`
`PRODUCTION_SWITCH_NOT_YET_OBSERVED`

Production observation:

- Universe: 677
- Eligible: 513
- Scanner/Ranking operational
- max scoreAdvantage: 0.173
- required minimumScoreAdvantage: 0.42
- consecutive wins: 0 / 5
- SafeSwitch invocation: 0
- SafeSwitch commit: 0
- activeSymbol mutation: 0
- Real orders: 0
- Cancels: 0
- Fund movements: 0

Cleanup:

- Bot STOPPED
- Loop STOPPED
- Live AUTO OFF
- approval cleared
- AUTO TRADE false
- executionEnabled false
- realOrderAllowed false

IMPORTANT:

This is not a failed AMS implementation.

Natural market conditions did not satisfy the configured switching gates.

---

# 3. Important AMS Runtime Finding

During AMS-FINAL-1C:

Micro Edge Suitability became unavailable because the detector/feature evidence currently requires the Trading Loop, while the standalone AMS trial intentionally kept Loop STOPPED.

This creates a possible startup dependency question:

```text
AMS needs Micro Edge Suitability
        ↑
Detector / Feature Builder may need Loop
        ↑
Loop may need Active Symbol
        ↑
AMS may need to choose Active Symbol
```

Do NOT assume this is a bug.

The actual BOT START / Loop / AMS bootstrap lifecycle must be audited after the AI Review architecture is decided.

---

# 4. Current Dashboard OPERATION状態

Task:

`TR-DASHBOARD-OPERATION-SETUP-FLOW-R2`

Result:

`BLOCKED_PRESTART_AUTOMATION_AUTHORITY`

UI itself has been updated to the intended human setup order:

```text
1. Trading Mode
2. Market Selection
3. Risk Settings
4. Automation
5. Ready / Start
```

Design principle:

```text
CONFIGURE EVERYTHING
        ↓
REVIEW
        ↓
START BOT
        ↓
OBSERVE CURRENT RUNTIME
```

Emergency remains outside the numbered normal flow.

---

# 5. Current START BOT Semantics

Current backend authority was audited.

START BOT currently:

- starts Bot monitoring/runtime only
- does NOT start Loop
- does NOT stage/start AMS
- forces/keeps AUTO TRADE OFF
- requires Loop and AUTO TRADE runtime operations afterward

Current authority facts:

- Loop can start only after BOT RUNNING
- AUTO TRADE requires BOT + LOOP RUNNING
- Market Selection status authority exists
- Dashboard AUTO/MANUAL mutation API is not exposed
- AMS Monitoring and AMS Runtime Activation are separate authorities
- Risk / Leverage can be supplied in START payload
- Emergency is independent Governance authority

Therefore the desired operator UX and current backend lifecycle do not yet match.

---

# 6. Desired Final OPERATION Model

The human operator should make every intended session decision BEFORE pressing START BOT.

Target:

```text
1. TRADING MODE
   PAPER / LIVE

        ↓

2. MARKET SELECTION
   MANUAL / AUTO

   MANUAL:
   choose symbol

   AUTO:
   AMS owns symbol selection

        ↓

3. RISK SETTINGS
   Risk
   Leverage
   Advanced

        ↓

4. AUTOMATION
   Loop intent
   AMS intent / Market-selection behavior
   Auto Trade intent

        ↓

5. READY / START
   review complete session configuration

   [ START BOT ]
```

START BOT must be the final normal setup action.

After START, the lower panel should report CURRENT RUNTIME STATE, not force the operator to finish configuring the intended session.

---

# 7. Why Backend Work Is Deliberately Waiting

Do NOT immediately implement:

- `loopOnStart`
- `autoTradeOnStart`
- AMS activation intent
- BOT START → AMS mainline
- final Decision Pipeline startup

until the current PAPER AI trial decides whether AI Review remains in the trading path.

The final pipeline may be either:

## AI retained

```text
BOT START
→ Market Selection / AMS
→ Active Symbol
→ Loop / Market Processing
→ Python Strategy / Micro Edge
→ AI Review
→ Final MM
→ Governance
→ Execution
```

or:

## AI removed from execution path

```text
BOT START
→ Market Selection / AMS
→ Active Symbol
→ Loop / Market Processing
→ Python Strategy / Micro Edge
→ Final MM
→ Governance
→ Execution
```

The startup contract should be designed only after this is known.

---

# 8. FIRST ACTION WHEN DEVELOPMENT RESUMES

Ask the user for the latest PAPER AI trial Final Report if it is not already in the current conversation.

Determine exactly:

- AI Review retained or removed?
- Does AI remain advisory-only?
- Did PAPER E2E reach Strategy/MM/Governance/Execution?
- What was the first runtime blocker, if any?
- Was Decision Pipeline architecture changed?
- Were service/source changes applied?

Do not begin implementation until these answers are grounded in the returned report.

---

# 9. Next Task After AI Decision

After AI architecture is finalized, create:

`TR-RUNTIME-STARTUP-CONTRACT-1A`

Title:

**Pre-Start Session Configuration + Atomic BOT START Lifecycle Contract**

Purpose:

Define and implement one authoritative session-start contract so the user configures the desired run before START.

The contract should cover, according to actual backend authority:

```text
Trading Mode
Market Selection Mode
Manual Symbol if applicable
Risk
Leverage
Loop-on-start intent
AMS / market-selection intent
Auto-Trade intent
Decision Pipeline mode
Emergency readiness
Configuration version
```

Do not implement these as unrelated booleans if an existing typed runtime configuration can be extended cleanly.

---

# 10. Startup Contract Safety Requirements

The startup implementation must be fail-closed and lifecycle-aware.

It must NOT mean:

```text
START BOT
→ blindly turn everything ON
```

Instead:

```text
Pre-Start Configuration
        ↓
Validate
        ↓
Ready
        ↓
START BOT
        ↓
Apply only authorized staged intents
        ↓
Verify each transition
        ↓
RUNNING session state
```

Critical rules:

- AUTO TRADE and real execution remain separate authorities.
- `realOrderAllowed` must never become true merely because START BOT was pressed.
- LIVE mode must preserve all existing Governance / Emergency / execution permissions.
- AMS selection permission must remain distinct from order permission.
- Unknown/stale authority fails closed.
- Partial startup must have explicit state/error reporting.
- No hidden automatic retries that can duplicate mutations.

---

# 11. Required Market Selection Semantics

The startup contract must distinguish:

## MANUAL MARKET

```text
Operator selects symbol
→ authoritative activeSymbol
→ market data ready
→ strategy/loop may proceed
```

## AUTO MARKET

```text
START BOT
→ AMS bootstrap
→ Universe
→ Scanner
→ Capital Eligibility
→ Ranking
→ required suitability/selection gates
→ Initial Active Symbol
→ market data ready
→ strategy/loop may proceed
```

AUTO mode must not silently reuse a manual/default/stale symbol unless an explicitly specified bootstrap contract permits it.

---

# 12. AMS Mainline Integration Audit

After the startup contract design is clear, run:

`AMS-MAINLINE-INTEGRATION-AUDIT-1A`

Audit:

```text
BOT START
→ Market Selection
→ AMS initial selection
→ Active Symbol
→ Loop
→ Trading Decision
```

Questions to prove:

1. Who owns initial activeSymbol?
2. Does PAPER AUTO necessarily pass through AMS?
3. Does LIVE AUTO necessarily pass through AMS?
4. Does MANUAL correctly bypass automatic selection?
5. Can Strategy start before activeSymbol authority is resolved?
6. Does AMS require Loop-derived detector evidence before initial selection?
7. If so, what is the correct bootstrap order?
8. Is SafeSwitch only reselection or also used for initial selection?
9. Can stale/manual symbol state leak into AUTO startup?

Audit before changing architecture.

---

# 13. Resolve AMS / Loop Bootstrap Dependency

If audit proves a real circular dependency:

```text
AMS suitability requires Loop
Loop requires Active Symbol
Active Symbol requires AMS
```

do not bypass Micro Edge Suitability.

Instead identify the correct architecture from existing components.

Potential valid patterns must be evidence-driven, e.g.:

- bounded candidate deep-analysis runtime before full trading Loop;
- dedicated existing detector/feature observation path;
- bootstrap symbol/feed that is not yet authoritative for Trading Decision;
- separation of selection observation loop from trading decision loop.

Do NOT invent a second detector or feature engine.

Reuse the existing production detector/feature authority.

---

# 14. Then Implement Mainline Integration

If the audit finds AMS is not bound to BOT START, implement the minimum integration.

Target AUTO startup:

```text
Session Config
→ START BOT
→ AMS
→ Initial Active Symbol
→ Market Ready
→ Loop
→ Decision Pipeline
```

Target MANUAL startup:

```text
Session Config
→ START BOT
→ Manual Active Symbol
→ Market Ready
→ Loop
→ Decision Pipeline
```

No duplicate Market Selection engine.

---

# 15. Paper Full Startup E2E

After backend startup integration, run:

`TR-PAPER-FULL-STARTUP-E2E-1A`

Goal:

One operator action after configuration:

```text
READY
→ START BOT
```

should create the intended PAPER session.

Test at least:

## PAPER + MANUAL

```text
Mode PAPER
Market MANUAL
Symbol chosen
Loop intent configured
Auto Trade OFF
→ START BOT
→ correct activeSymbol
→ Loop as configured
→ Decision Pipeline
```

## PAPER + AUTO

```text
Mode PAPER
Market AUTO
Loop intent configured
Auto Trade OFF
→ START BOT
→ AMS scanner/ranking
→ initial activeSymbol
→ Loop
→ Decision Pipeline
```

No real orders.

---

# 16. Operation UI Final Backend Binding

After backend authority is complete, return to the already-redesigned UI.

Implement only the missing bindings:

- AUTO / MANUAL market selection control
- Pre-start Loop intent
- Pre-start AMS intent if separately required
- Pre-start Auto Trade intent where safely supported
- Ready Check projection
- START payload/session contract
- Runtime state readback

Do not redesign the 1→5 layout again unless evidence requires it.

The accepted UI order is:

```text
1 MODE
2 MARKET
3 RISK
4 AUTOMATION
5 READY / START
```

---

# 17. AUTO TRADE Special Rule

Do not blindly make `AUTO TRADE ON START` a generic boolean.

PAPER and LIVE may require different semantics.

For LIVE:

- explicit safety authority
- Governance
- Emergency
- realOrderAllowed
- execution permission
- potentially confirmation/approval

must remain authoritative.

START BOT must never circumvent those boundaries.

If safe pre-staging of Live Auto Trade is not appropriate, UI may show intent while requiring a later explicit execution authorization.

Truthful authority is more important than convenience.

---

# 18. Final AMS Production Proof

AMS standalone is implemented and tested, but natural Production SafeSwitch has not yet occurred.

After mainline/startup integration is stable, perform a later bounded Production observation.

Do NOT reduce the official threshold merely to force proof.

Possible result remains valid:

`NO_ELIGIBLE_SWITCH_OBSERVED`

A successful natural SafeSwitch should eventually prove:

```text
candidate
→ suitability
→ anti-flapping
→ Phase-1
→ Phase-2
→ permission
→ SafeSwitch
→ activeSymbol commit
→ feed/orderbook/context sync
```

Zero orders.

---

# 19. Recorder / Replay Work Is Separate

Market Recorder is already operational.

Do not mix Recorder construction into this startup work.

Separate future data-use line:

```text
Recorder Archive
→ Replay Adapter
→ Micro Edge
→ Python Evaluator
→ AI Advisor
```

This is not the same task as Bot startup integration.

---

# 20. Recommended Task Order After Resume

After the current PAPER AI trial completes:

```text
1. AI Decision Review
   Decide final Trading Decision pipeline.

2. TR-RUNTIME-STARTUP-CONTRACT-1A
   Pre-start Session Configuration + START lifecycle.

3. AMS-MAINLINE-INTEGRATION-AUDIT-1A
   Prove actual BOT START → AMS/Manual → Active Symbol → Loop path.

4. AMS-MAINLINE-INTEGRATION-1B
   Only if audit proves a gap.

5. TR-PAPER-FULL-STARTUP-E2E-1A
   PAPER MANUAL + AUTO full startup proof.

6. TR-DASHBOARD-OPERATION-BACKEND-BINDING-1A
   Connect the existing 1→5 Operation UI to the new backend authority.

7. Production Live startup / AMS proof
   Only after Paper startup E2E is complete.

8. Recorder Replay / Evaluator / AI Advisor
   Continue as a separate next-phase project.
```

---

# 21. Development Policy

The current development policy is:

- use the production-intended implementation;
- run real bounded tests;
- fix the first concrete runtime blocker;
- avoid endless broad audits;
- do not redesign already-working subsystems without evidence;
- preserve strong order/fund safety boundaries.

When a production trial finds a concrete blocker, fix that blocker rather than returning to a large architecture review.

---

# 22. OpenCode Instruction Standard

When generating future OpenCode tasks:

- start with the Safety Checklist;
- include `cd /home/joe4410joe/tradingai_prod_v1` for TradingAI tasks;
- protect existing dirty/untracked work;
- no commit/push unless explicitly authorized;
- do not touch unrelated parallel work;
- identify exact host/repository;
- end with the standardized ChatGPT Review Report;
- save reports under:

```text
tmp/chatgpt_reviews/YYYYMMDD_HHMMSS.md
```

---

# 23. Resume Prompt for Future GPT

When reopening development, the user may paste this section:

```text
TradingAI development resume.

We deliberately paused BOT START / AMS mainline integration while another
Production PAPER trial determines whether AI Review remains in the trading
decision path.

Current important state:

1. AMS implementation and tests are substantially complete.
2. PASS_DEEP_ANALYSIS_FAIL_CLOSED.
3. AMS standalone production trial returned NO_ELIGIBLE_SWITCH_OBSERVED.
4. Scanner/ranking works; SafeSwitch has not naturally committed yet.
5. Micro Edge Suitability currently depends on detector/feature evidence that
   may depend on the Trading Loop; bootstrap ordering must be verified.
6. Dashboard OPERATION has been redesigned to:
   1 Mode
   2 Market Selection
   3 Risk Settings
   4 Automation
   5 Ready / Start
7. START BOT must be the final normal operator action.
8. Current backend cannot stage Loop/Auto Trade/AMS intent before START.
9. Current START BOT starts monitoring/runtime only; Loop remains STOPPED,
   AMS activation is not staged, Auto Trade stays OFF.
10. Operation UI therefore currently reports
    BLOCKED_PRESTART_AUTOMATION_AUTHORITY.
11. Do not redesign the accepted 1→5 UI flow.
12. First obtain/review the latest PAPER AI trial result.
13. After AI is retained or removed, define the final Trading Decision pipeline.
14. Then create TR-RUNTIME-STARTUP-CONTRACT-1A.
15. After that audit BOT START → AMS/Manual → Active Symbol → Loop mainline.
16. Then run full PAPER startup E2E.
17. Only after backend authority exists, bind the existing Operation UI controls.

Do not mix Market Recorder construction into this task.
Do not enable real orders or realOrderAllowed merely to complete startup.
```

---

# 24. Current Pause Classification

`WAITING_FOR_PAPER_AI_ARCHITECTURE_DECISION`

Exact resume point:

**Review the final Production PAPER AI trial report first.**

Do not begin BOT START lifecycle implementation before that report establishes the final Decision Pipeline.
