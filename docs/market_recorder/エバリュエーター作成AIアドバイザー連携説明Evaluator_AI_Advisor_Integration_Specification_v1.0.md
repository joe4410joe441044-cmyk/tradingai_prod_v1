# TradingAI Replay Evaluator + AI Advisor Integration Specification v1.0

作成日: 2026-08-10\
Status: Active Draft / Implementation Baseline\
対象: TradingAI Market Recorder / Replay / Micro Edge / AI Advisor

------------------------------------------------------------------------

## 0. この文書の位置づけ

本書は、現在稼働中の TradingAI Market Recorder
が保存した実市場データを、Micro Edge の検証・調整へ利用するための
**Replay Evaluator** と、その評価結果を既存 **AI Advisor**
から分析・説明できるようにする連携仕様を定義する。

本仕様は既存構成を置き換えない。

既存の責務を維持したまま、以下を追加する。

1.  Recorder archive を決定論的に再生する Replay Adapter
2.  Micro Edge の既存判定ロジックを Replay 上で実行する境界
3.  判定後の市場変化を数値評価する Python Evaluator
4.  複数設定を比較する Experiment Runner
5.  評価結果を Read-only で参照・説明する AI Advisor integration

最終目的は、ユーザーが大量のチャートやシグナルを手作業で判定しなくても、

-   「ここでは入るべきだったか」
-   「なぜ入らなかったか」
-   「どの条件で false entry が増えたか」
-   「threshold 等を変更するとどう変わるか」

を再現可能な数値評価として確認できる状態を作ることである。

------------------------------------------------------------------------

# 1. Existing Architecture Baseline

## 1.1 Recorder

Recorder は TradingAI の検証・学習・バックテスト・Replay
用に市場データを保存する。

現行構成の主要 authority:

-   Recorder Runtime
-   Event Pipeline
-   JSONL Writer
-   Manifest
-   Archive
-   Read API
-   Control API
-   TradingAI Backend Recorder Proxy
-   Market Recorder UI

Recorder production data では、modern orderbook epoch について
snapshot + delta が利用でき、FULL_ORDERBOOK_REPLAY_READY
と評価済みである。

legacy archive の一部は snapshot を持たず、DELTA_ONLY_REQUIRES_SNAPSHOT
として扱う。

## 1.2 Recorder Archive

基本 artifact:

``` text
archive/{exchange}/{symbol}/{year}/{month}/{day}/{stream}/
    {start}_{end}[...].jsonl.zst
    {corresponding manifest}.manifest.json
```

利用可能な主要 event family:

-   ticker
-   trade
-   orderbook
-   orderbook_snapshot
-   system

Recorder timestamp / sequence / book epoch を Replay ordering authority
として使用する。

## 1.3 TradingAI / Micro Edge

Micro Edge の production 判定ロジックを Replay 用に複製してはならない。

Replay は既存 Micro Edge の feature / decision contract を再利用する。

Replay 専用の「似たロジック」「簡易版 Micro Edge」「第二 scoring
engine」を作らない。

## 1.4 AI Advisor

既存 AI Advisor は TradingAI の Read-only advisor として維持する。

原則:

``` text
Read-only advisor
No order execution
No configuration changes
```

Evaluator 連携後もこの境界を変更しない。

AI Advisor は評価値を生成する authority ではない。

------------------------------------------------------------------------

# 2. Target Architecture

``` text
Market Recorder
      │
      │ archived real market data
      ▼
Replay Archive Reader
      │
      ▼
Replay Adapter / Clock
      │
      ├── ticker
      ├── trade
      ├── orderbook snapshot
      └── orderbook delta
      │
      ▼
Existing Micro Edge
      │
      │ ENTER / WAIT / NO_ENTRY
      │ reason / features / scores
      ▼
Replay Evaluator (Python)
      │
      ├── forward returns
      ├── MFE / MAE
      ├── signal statistics
      ├── false-entry analysis
      ├── missed-opportunity analysis
      └── deterministic metrics
      │
      ▼
Experiment Result Store
      │
      ├── run metadata
      ├── decision records
      ├── aggregate metrics
      └── parameter comparison
      │
      ├──────────────────────────┐
      ▼                          ▼
Evaluator Report/API        AI Advisor
                                 │
                                 ▼
                         analysis / explanation
                         experiment suggestions
```

------------------------------------------------------------------------

# 3. Responsibility Boundaries

## 3.1 Recorder responsibility

Recorder owns:

-   original market observations
-   archive bytes
-   manifest
-   checksum
-   event timestamp
-   stream sequence
-   orderbook epoch information

Recorder does NOT decide whether a Micro Edge signal was good or bad.

## 3.2 Replay responsibility

Replay owns:

-   archive loading
-   integrity validation
-   deterministic ordering
-   virtual/replay clock
-   event delivery
-   orderbook reconstruction
-   reproducible replay session

Replay does NOT invent market events.

## 3.3 Micro Edge responsibility

Micro Edge owns:

-   production feature calculations
-   entry/no-entry logic
-   decision reasons
-   configured thresholds
-   strategy-specific scoring

Replay must call the existing authority.

## 3.4 Evaluator responsibility

Evaluator owns deterministic post-decision measurement.

Examples:

-   future mid-price movement
-   forward return in basis points
-   MFE
-   MAE
-   direction agreement
-   false-entry classification
-   missed-opportunity classification
-   signal frequency
-   decision latency
-   configuration comparison

Evaluator must not alter Micro Edge decisions after observing the
future.

## 3.5 AI Advisor responsibility

AI Advisor owns:

-   explanation
-   comparison
-   anomaly summarization
-   experiment interpretation
-   next-experiment suggestions

AI Advisor does NOT own:

-   ground-truth metric calculation
-   replay ordering
-   Micro Edge decision
-   production parameter mutation
-   trading
-   order execution

------------------------------------------------------------------------

# 4. Replay Adapter Specification

## 4.1 Input

Replay Adapter accepts one or more Recorder archive/manifests.

Minimum validation:

-   archive exists
-   manifest exists where required
-   checksum matches
-   decompression succeeds
-   JSONL is valid
-   supported schema/version
-   timestamps valid
-   sequence semantics valid
-   required orderbook snapshot available for full-book replay

Invalid input fails closed.

## 4.2 Ordering

Replay ordering must be deterministic.

Primary ordering authority:

1.  `recorder_timestamp_ns`
2.  stream/event sequence
3.  deterministic tie-break when timestamps are identical

Filesystem order must never become replay order authority.

## 4.3 Replay Clock

Production wall clock must not drive strategy evaluation.

Provide a ReplayClock abstraction.

Required operations:

-   current replay timestamp
-   advance to next event
-   query elapsed replay time
-   resolve forward evaluation windows

No `sleep()`-based correctness dependency.

Fast replay must produce the same decisions as 1x replay.

## 4.4 Orderbook reconstruction

For modern eligible epochs:

``` text
snapshot
   ↓
ordered deltas
   ↓
reconstructed book state
   ↓
Micro Edge feature calculation
```

Required checks:

-   snapshot exists
-   epoch matches
-   sequence continuity
-   delta ordering
-   no unhandled gap
-   no cross-epoch contamination

If continuity is lost, book-dependent evaluation for that interval
becomes unavailable/fail-closed.

## 4.5 Legacy archives

Legacy `DELTA_ONLY_REQUIRES_SNAPSHOT` data must not be silently treated
as a full book.

Possible result:

``` text
replayCapability = PARTIAL
orderbookReplay = UNAVAILABLE
reason = SNAPSHOT_REQUIRED
```

Ticker/trade-only evaluation may proceed only if the Micro Edge path
being evaluated does not require unavailable book state.

------------------------------------------------------------------------

# 5. Replay Session Identity

Each replay execution must have a stable run identity.

Suggested fields:

``` text
replayRunId
datasetId
archiveIds[]
manifestIds[]
exchange
symbol
startTime
endTime
strategyVersion
microEdgeConfigurationVersion
evaluatorVersion
createdAt
```

`datasetId` should be content-derived where practical.

The same dataset + same Micro Edge configuration + same evaluator
version must be reproducible.

------------------------------------------------------------------------

# 6. Future Leakage Prevention

This is a hard requirement.

At replay time `T`, Micro Edge may only observe information with
authoritative timestamp `<= T`.

Evaluator may inspect future observations only after the Micro Edge
decision has been frozen.

Example:

``` text
T0:
    Micro Edge receives market state through T0
    decision = ENTER
    decision is persisted/frozen

T0 + 5s:
    Evaluator calculates forward_5s

T0 + 10s:
    Evaluator calculates forward_10s

T0 + 30s:
    Evaluator calculates forward_30s
```

Future data must never be passed back into feature calculation or
decision logic.

Regression tests must explicitly detect look-ahead leakage.

------------------------------------------------------------------------

# 7. Micro Edge Decision Record

Every evaluated decision should produce a structured record.

Minimum fields:

``` text
replayRunId
decisionId
timestamp
exchange
symbol

decision
direction
decisionReason

microEdgeScore
configuredThreshold

featureSnapshot
gateResults

referencePrice
referenceMidPrice
spread
```

`decision` should preserve existing production semantics where
available.

Examples:

-   ENTER
-   WAIT
-   NO_ENTRY

Do not translate production decisions into a second incompatible
taxonomy unless an adapter is unavoidable.

------------------------------------------------------------------------

# 8. Evaluator Metrics

## 8.1 Initial forward windows

Initial baseline:

-   +1 second
-   +5 seconds
-   +10 seconds
-   +30 seconds
-   +60 seconds

Windows must be configuration-driven so later research does not require
evaluator redesign.

## 8.2 Forward move

For each decision:

``` text
forwardMoveBp =
    directionAdjusted(
        futureReferencePrice - decisionReferencePrice
    )
```

Use one documented reference-price authority.

Preferred initial reference:

`mid-price`

Do not mix last trade / best bid / best ask / mid across runs without
versioning.

## 8.3 MFE

Maximum Favorable Excursion over configured horizon.

Purpose:

Measure how far the market moved in the expected direction after the
decision.

## 8.4 MAE

Maximum Adverse Excursion over configured horizon.

Purpose:

Measure adverse movement after the decision.

## 8.5 Direction agreement

Example:

LONG ENTER:

``` text
forwardMoveBp > 0
```

SHORT ENTER:

``` text
forwardMoveBp > 0
```

after direction normalization.

A configurable neutral band may later be introduced, but v1 must
document exact semantics.

## 8.6 False Entry

Do not define false-entry using subjective chart review.

v1 classification must use explicit thresholds, for example:

``` text
decision = ENTER
AND forwardMove@evaluationWindow <= configuredFailureThreshold
```

Exact thresholds belong to evaluator configuration and must be recorded
with the run.

## 8.7 Missed Opportunity

Missed opportunity is more difficult because every WAIT/NO_ENTRY event
is not an independent opportunity.

v1 must therefore define a sampling/de-duplication policy before
reporting this metric.

Possible baseline:

-   decision transition points only
-   cooldown/debounce window
-   subsequent move exceeds configured opportunity threshold

Do not report a misleading missed-opportunity percentage until the
denominator is formally defined.

------------------------------------------------------------------------

# 9. Aggregate Evaluation

Per replay run, produce at least:

``` text
totalObservations
totalDecisions
enterCount
waitCount
noEntryCount

signalsPerHour

directionAgreement1s
directionAgreement5s
directionAgreement10s
directionAgreement30s
directionAgreement60s

averageForwardMoveBp
medianForwardMoveBp

averageMFE
medianMFE
averageMAE
medianMAE

falseEntryCount
falseEntryRate

unavailableEvaluationCount
dataGapCount
```

Distribution/quantile metrics should be preferred over average-only
reporting.

Recommended:

-   p25
-   p50
-   p75
-   p90
-   p95

------------------------------------------------------------------------

# 10. Evaluator Output

## 10.1 Machine-readable

Primary outputs:

``` text
run.json
decisions.jsonl
metrics.json
```

Optional:

``` text
comparison.json
```

CSV may be generated for manual inspection, but JSON/JSONL remains
canonical.

## 10.2 Human-readable

Generate a compact report containing:

-   dataset
-   strategy/config version
-   replay integrity
-   decision counts
-   forward metrics
-   MFE/MAE
-   false entries
-   missed opportunities if valid
-   unavailable/gap intervals
-   comparison result if applicable

The report is derived from canonical machine-readable metrics.

------------------------------------------------------------------------

# 11. Experiment Runner

## 11.1 Purpose

Allow the same Recorder dataset to be replayed against multiple Micro
Edge configurations.

Example:

``` text
threshold = 0.65
threshold = 0.70
threshold = 0.75
```

## 11.2 Requirement

Every experiment must use:

-   identical dataset
-   identical replay ordering
-   identical evaluation windows
-   identical evaluator version
-   identical market reference-price semantics

Only declared experiment variables may differ.

## 11.3 Comparison output

Example fields:

``` text
experimentId
baselineRunId
candidateRunIds[]

parameterDiff

signalCountDelta
directionAgreementDelta
averageForwardMoveDelta
mfeDelta
maeDelta
falseEntryRateDelta
missedOpportunityRateDelta
```

## 11.4 No automatic production mutation

Experiment Runner must never automatically write the winning
configuration to production.

Allowed:

``` text
recommendation = TEST_CANDIDATE_B
```

Forbidden:

``` text
applyCandidateBToProduction()
```

Production configuration change remains a separately authorized action.

------------------------------------------------------------------------

# 12. AI Advisor Integration

## 12.1 Principle

AI Advisor consumes Evaluator results.

AI Advisor does not independently calculate canonical evaluation metrics
from raw archives.

Preferred chain:

``` text
Recorder
→ Replay
→ Micro Edge
→ Evaluator
→ canonical result
→ AI Advisor
```

## 12.2 New Advisor knowledge source

Add an internal source type conceptually equivalent to:

``` text
Replay Evaluation Results
```

It should expose:

-   replay run metadata
-   aggregate metrics
-   decision-level evidence
-   experiment comparisons
-   evaluator warnings
-   data-quality status

Do not index credentials, secrets, private keys, or raw security
configuration.

## 12.3 Advisor questions to support

Examples:

``` text
昨日のMicro Edge Replay結果を分析して
```

``` text
false entryが多かった条件は？
```

``` text
threshold 0.65 / 0.70 / 0.75を比較して
```

``` text
03:18:22にXRPUSDTへ入らなかった理由は？
```

``` text
10秒後に大きく上昇したのにNO_ENTRYだったケースを調べて
```

``` text
次に試すパラメータ候補を出して
```

## 12.4 Evidence-backed answer contract

Advisor answer should distinguish:

-   deterministic evaluator fact
-   Micro Edge decision reason
-   AI interpretation
-   AI recommendation

Example:

``` text
Evaluator Fact:
10s false-entry rate increased from 11.2% to 16.8%.

Decision Evidence:
Most additional false entries occurred near the configured spread limit.

AI Interpretation:
The degradation appears more associated with spread conditions than
with insufficient score threshold.

Suggested Experiment:
Keep score threshold fixed and test two spread-gate variants.
```

AI interpretation must not be presented as deterministic evaluator fact.

## 12.5 Drill-down

Advisor must be able to resolve a summary back to decision evidence.

Preferred reference chain:

``` text
Advisor statement
→ replayRunId
→ decisionId(s)
→ evaluator metrics
→ frozen feature/decision snapshot
```

This provides auditability and reduces hallucinated explanations.

------------------------------------------------------------------------

# 13. AI Advisor Safety Boundary

Existing Read-only posture remains.

AI Advisor may:

-   read evaluator results
-   search replay runs
-   compare experiments
-   explain decisions
-   recommend another experiment
-   identify suspicious patterns

AI Advisor may not:

-   START/STOP Recorder
-   modify Recorder archive
-   delete archive
-   modify Micro Edge production configuration
-   enable AUTO TRADE
-   change `realOrderAllowed`
-   place/cancel orders
-   move funds
-   invoke SafeSwitch
-   automatically deploy a recommended parameter

Any future write capability requires a separate specification and
explicit authorization boundary.

------------------------------------------------------------------------

# 14. Evaluator API / Service Boundary

Implementation location should be determined by repository audit before
coding.

Preferred logical interface:

``` text
ReplayEvaluationService
```

Operations conceptually:

``` text
create_run(...)
get_run(replayRunId)
list_runs(...)
get_metrics(replayRunId)
get_decisions(replayRunId, filters...)
compare_runs(runIds...)
```

AI Advisor should consume this service/read model rather than reading
evaluator filesystem internals directly.

Do not create a second archive inventory if the existing Recorder/Replay
abstraction already supplies the required data.

------------------------------------------------------------------------

# 15. Storage Model

Initial implementation may use filesystem-backed result storage if that
matches current project architecture.

Suggested layout:

``` text
replay_evaluations/
    runs/
        {replayRunId}/
            run.json
            metrics.json
            decisions.jsonl
    comparisons/
        {comparisonId}.json
```

Requirements:

-   immutable completed run results
-   explicit evaluator version
-   explicit strategy/config version
-   atomic completion marker or state
-   incomplete run distinguishable from completed run
-   no overwrite of unrelated run

A database is not required for v1 unless repository audit proves one is
already the correct authority.

------------------------------------------------------------------------

# 16. Performance

Replay must support faster-than-real-time execution.

Targets should be measured rather than guessed.

Initial implementation should collect:

``` text
eventsProcessed
replayDurationSeconds
sourceDurationSeconds
replaySpeedMultiplier
peakMemory
evaluationRecords
```

Correctness and determinism take priority over maximum speed.

------------------------------------------------------------------------

# 17. Determinism

Given identical:

-   archive bytes
-   manifest
-   Replay Adapter version
-   Micro Edge version
-   configuration
-   Evaluator version

the following must be reproducible:

-   event ordering
-   Micro Edge decision sequence
-   decision IDs
-   aggregate metrics

Where unavoidable nondeterminism exists, it must be identified and
removed from the evaluation path.

------------------------------------------------------------------------

# 18. What v1 Can Evaluate

v1 is intended to answer:

-   Does Micro Edge produce signals at sensible market moments?
-   What happens to market price after ENTER?
-   How often does ENTER immediately move against the signal?
-   Which gate most frequently blocks entries?
-   Are good moves being missed because a gate is too restrictive?
-   Does changing one parameter improve or degrade measurable market
    response?
-   Which market regimes produce poor Micro Edge behavior?
-   Is a new Micro Edge version better than a baseline on the same
    recorded dataset?

------------------------------------------------------------------------

# 19. What v1 Cannot Truthfully Claim

Replay Evaluator v1 must NOT claim exact realized trading profit.

Recorder currently does not provide a complete execution simulator
containing all production execution realities.

Not authoritative for exact PnL:

-   actual fill probability
-   queue position
-   exchange matching priority
-   production network latency
-   order submission latency
-   cancellation latency
-   partial-fill path
-   exact slippage
-   all fees/rebates
-   account/margin state
-   complete trading runtime decisions

Therefore:

``` text
Micro Edge market-response evaluation = SUPPORTED
Exact production PnL simulation = NOT SUPPORTED
```

A future execution simulator may be added separately.

------------------------------------------------------------------------

# 20. Validation and Test Requirements

## 20.1 Replay Adapter

Required tests:

-   checksum mismatch
-   invalid zstd
-   malformed JSONL
-   timestamp ordering
-   same-timestamp tie-break
-   snapshot + delta reconstruction
-   sequence gap
-   epoch transition
-   legacy delta-only rejection/partial mode
-   deterministic repeated replay

## 20.2 Future leakage

Required tests:

-   future ticker unavailable to Micro Edge
-   future trade unavailable
-   future orderbook delta unavailable
-   evaluator can access future window only after frozen decision
-   changing future events cannot change an already-issued decision

## 20.3 Evaluator

Required tests:

-   forward bp calculation
-   LONG normalization
-   SHORT normalization
-   MFE
-   MAE
-   missing future window
-   neutral/no-move
-   false-entry classification
-   decision de-duplication
-   unavailable interval handling
-   aggregate metrics

## 20.4 Experiment Runner

Required tests:

-   identical dataset enforcement
-   config-difference capture
-   deterministic comparison
-   incompatible evaluator version rejection or explicit handling
-   no production config mutation

## 20.5 AI Advisor integration

Required tests:

-   evaluator result retrieval
-   run selection
-   decision drill-down
-   comparison retrieval
-   unavailable evaluator source
-   malformed result
-   AI context contains evidence IDs
-   no credentials in context
-   no write/configuration capability introduced

------------------------------------------------------------------------

# 21. Production / Trading Safety

Replay/Evaluator must be isolated from live execution authority.

During Replay:

``` text
real orders = 0
cancels = 0
fund movements = 0
AUTO TRADE activation = 0
realOrderAllowed mutation = 0
production symbol mutation = 0
```

Replay must not require Bot production activation.

Where production Micro Edge code currently depends on runtime services,
introduce adapters/interfaces rather than enabling trading.

------------------------------------------------------------------------

# 22. Implementation Phases

## Phase R1 --- Architecture / Contract Audit

Audit current:

-   Recorder archive contracts
-   Replay Engine
-   Micro Edge entry point
-   feature calculation
-   decision contract
-   configuration authority
-   AI Advisor service/backend
-   AI Advisor knowledge/context mechanism

Deliver:

-   exact reuse map
-   missing adapter list
-   no-code or minimal contract findings

## Phase R2 --- Recorder Replay Adapter

Implement:

-   archive reader
-   manifest/checksum validation
-   deterministic replay ordering
-   ReplayClock
-   full-orderbook reconstruction
-   capability classification

No Evaluator tuning yet.

## Phase R3 --- Micro Edge Replay Bridge

Connect replay state to the existing Micro Edge decision authority.

Deliver:

-   frozen decision records
-   feature snapshot
-   decision reason
-   configuration/version identity

No duplicate Micro Edge implementation.

## Phase R4 --- Python Replay Evaluator

Implement deterministic:

-   forward windows
-   forward bp
-   MFE
-   MAE
-   direction agreement
-   false-entry baseline
-   aggregate metrics
-   canonical result files

## Phase R5 --- Experiment Runner

Implement controlled parameter experiments on the same dataset.

No production mutation.

## Phase R6 --- AI Advisor Read-only Integration

Expose completed evaluator runs to AI Advisor.

Support:

-   run summaries
-   comparison
-   decision drill-down
-   evidence-backed explanations
-   experiment suggestions

## Phase R7 --- Production Usability

Add minimal UI/read model needed to:

-   choose replay run
-   view evaluation summary
-   ask AI Advisor about selected run
-   inspect evidence for a specific decision

Do not build a large analytics dashboard unless actual usage proves it
necessary.

------------------------------------------------------------------------

# 23. Initial Completion Criteria

Replay Evaluator + AI Advisor integration v1 is complete when:

1.  A verified Recorder dataset can be selected.
2.  The dataset replays deterministically.
3.  Modern orderbook state reconstructs correctly.
4.  Existing Micro Edge processes replay state without production
    trading activation.
5.  Decisions are frozen before future evaluation.
6.  +1/+5/+10/+30/+60s evaluation is produced.
7.  MFE/MAE are produced.
8.  Aggregate metrics are produced.
9.  The same run is reproducible.
10. At least two configurations can be compared on the same dataset.
11. AI Advisor can read the result.
12. AI Advisor can explain a specific decision using evidence.
13. AI Advisor can compare experiment results.
14. AI Advisor cannot modify production settings.
15. No live order/execution path is reachable from Replay/Evaluator.
16. Tests and regression pass.

------------------------------------------------------------------------

# 24. Recommended First Real Evaluation

After implementation, do not begin with automatic optimization.

Use one known modern FULL_ORDERBOOK_REPLAY_READY session.

Baseline procedure:

``` text
1. Verify archive + manifest + checksum.
2. Replay with current production Micro Edge configuration.
3. Generate decision records.
4. Evaluate +1/+5/+10/+30/+60s.
5. Generate MFE/MAE.
6. Review false entries.
7. Review missed opportunities only after denominator semantics pass validation.
8. Ask AI Advisor for evidence-backed summary.
9. Select ONE parameter family for experiment.
10. Replay baseline and candidates against exactly the same dataset.
```

This establishes a trustworthy baseline before parameter search expands.

------------------------------------------------------------------------

# 25. AI-assisted Tuning Policy

AI may propose experiments.

Example:

``` text
Current:
scoreThreshold = 0.70

Suggested next experiment:
A = 0.68
B = 0.70
C = 0.72
```

The proposal must include why the experiment is useful based on
evaluator evidence.

AI must not optimize solely for one metric.

At minimum, compare trade-offs among:

-   signal frequency
-   forward response
-   MFE
-   MAE
-   false-entry rate
-   missed-opportunity rate where valid
-   unavailable/data-gap rate

Parameter adoption remains a human/reviewed decision.

------------------------------------------------------------------------

# 26. Future Extensions --- Not v1 Requirements

Possible later phases:

-   execution/fill simulator
-   fee/slippage model
-   PnL approximation
-   regime classification
-   walk-forward evaluation
-   train/validation/test dataset partitions
-   automated nightly replay
-   drift detection
-   scheduled AI Advisor evaluation report
-   parameter search algorithms
-   Bayesian/Optuna-style optimization
-   shadow-mode comparison against live Micro Edge

These must not delay the initial deterministic Evaluator.

------------------------------------------------------------------------

# 27. Development Rules

All implementation tasks must:

1.  inspect existing architecture before creating abstractions;
2.  reuse Recorder archive/manifest authority;
3.  reuse existing Micro Edge logic;
4.  keep Evaluator deterministic;
5.  prevent look-ahead leakage;
6.  keep AI Advisor read-only;
7.  avoid production trading activation;
8.  avoid duplicate scoring/feature engines;
9.  version evaluator semantics;
10. preserve evidence from AI explanation back to replay decisions.

No broad redesign unless the current architecture proves incapable of
satisfying a concrete requirement.

------------------------------------------------------------------------

# 28. Recommended Next Task

Task ID:

`TR-REPLAY-EVAL-AUDIT-1A`

Purpose:

Before implementation, inspect the current TradingAI and Recorder
repositories and produce the exact integration map for:

``` text
Recorder Archive
→ Replay Adapter
→ Existing Micro Edge
→ Evaluator
→ AI Advisor
```

The audit must identify:

-   existing reusable Replay code
-   archive access boundary
-   Micro Edge production entry point
-   feature/state dependencies
-   configuration authority
-   current AI Advisor backend/service/context architecture
-   exact missing interfaces
-   proposed file ownership
-   test boundaries

No large implementation should begin until this narrow audit establishes
what already exists.

------------------------------------------------------------------------

# 29. Final Architectural Principle

The system must preserve this separation:

``` text
Recorder = what actually happened in the market

Replay = reproduce what TradingAI could have observed at that time

Micro Edge = decide using only information available at that time

Evaluator = measure what happened afterward

AI Advisor = explain the measurements and propose what to test next

Human / separately authorized process = decide whether production configuration changes
```

This separation is the foundation for trustworthy Micro Edge
improvement.
