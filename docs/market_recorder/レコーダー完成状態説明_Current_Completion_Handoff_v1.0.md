# TradingAI Market Recorder --- Current Completion & GPT Handoff v1.0

作成日: 2026-08-10\
Status: CURRENT PRODUCTION HANDOFF\
目的: 新しいChatGPTセッションへMarket
Recorderの現在地点を正確に引き継ぐための基準文書

------------------------------------------------------------------------

# 0. 新しいGPTへの最重要指示

この文書は、TradingAI Market Recorder開発の「現在の完成地点」を示す。

新しいセッションでは、Recorderを未実装・mock-only・read-only・START/STOP不可の古い状態として扱ってはならない。

現在は production で以下まで実証済みである。

``` text
TradingAI UI
    ↓
TradingAI Backend Recorder Proxy
    ↓ HTTPS / authenticated control
Recorder Read / Control API
    ↓
systemd narrow execution authority
    ↓
market-recorder.service
    ↓
Recorder Runtime
    ↓
Recording / Finalization / Archive / Manifest
```

実Production E2Eで、

``` text
RUNNING
→ REAL STOP
→ STOPPED
→ active files finalized
→ archives/manifests created
→ REAL START
→ RUNNING
→ connected
→ recording resumed
```

まで成功している。

したがって、Recorder本体の次フェーズは「録画機能を作ること」ではない。

次の主目的は、

``` text
Recorded Data
→ Replay
→ Micro Edge
→ Evaluator
→ AI Advisor
```

として録画データをTradingAIの検証・改善へ利用することである。

------------------------------------------------------------------------

# 1. Environment / Repository Boundary

## 1.1 Recorder Contabo

Role:

-   Recorder Runtime
-   Recording Pipeline
-   Storage
-   Archive
-   Manifest
-   Read API
-   Control API
-   systemd live execution authority

Repository:

``` text
/opt/market-recorder
```

Recorder service:

``` text
market-recorder.service
```

Read/Control API service:

``` text
market-recorder-read-api.service
```

## 1.2 TradingAI Contabo

Role:

-   TradingAI Backend Recorder Proxy
-   Market Recorder frontend tab
-   UI START/STOP
-   Read projection
-   Future Replay Evaluator / AI Advisor integration

Repository:

``` text
/home/joe4410joe/tradingai_prod_v1
```

These are separate repositories/hosts. Do not confuse the work boundary.

------------------------------------------------------------------------

# 2. Recorder Runtime Completion

Recorder Runtime foundation is implemented.

Major existing components include:

-   runtime coordinator
-   recording session
-   lifecycle state machine
-   event validation
-   normalization
-   recording pipeline
-   JSONL writer
-   manifest handling
-   storage repository
-   Binance market-data adapter
-   runtime health authority
-   graceful shutdown/finalization
-   archive generation

Supported event families observed in production archives include:

-   ticker
-   trade
-   orderbook
-   orderbook_snapshot
-   system

Modern orderbook recording supports snapshot + delta replay semantics.

------------------------------------------------------------------------

# 3. Production Recording State

Recorder has been proven to establish a real Binance public WebSocket
connection and record real market data end-to-end.

The production runtime has been observed:

``` text
status = running
connection = connected
message counters advancing
byte counters advancing
active recording files present
last error = none
```

The system continues recording while RUNNING.

STOP does not merely change UI state; it reaches the live Recorder
runtime.

START does not merely change API state; it starts the live Recorder
runtime and recording resumes.

------------------------------------------------------------------------

# 4. Read API

Recorder Read API is implemented and production-used.

Main read surfaces include:

-   health
-   status
-   storage
-   archives

TradingAI consumes these through its backend proxy.

Read status and Control state were previously found to use different
authorities. This was repaired.

Current state authority:

``` text
runtime/health.json
```

is the shared cross-process runtime state authority when the API does
not own a local orchestrator.

Unknown/inconsistent state must fail closed.

------------------------------------------------------------------------

# 5. Control API

Recorder Control foundation is no longer 501-only.

Production control path is operational.

Control supports START/STOP with dry-run and real execution semantics.

The state machine validates transitions.

Examples:

``` text
RUNNING + STOP dry-run
→ valid running → stopping → stopped plan
```

``` text
RUNNING + START dry-run
→ rejected / invalid_state_transition
```

Structured Control responses preserve operation/result/state
information.

------------------------------------------------------------------------

# 6. Live Execution Authority

A major production blocker was previously identified:

``` text
CONTROL_EXECUTION_NOT_BOUND_TO_LIVE_RUNTIME
```

The Read API process did not own the live Recorder orchestrator, so real
STOP could pass planning but fail before reaching the runtime.

This has been resolved with narrow systemd execution authority.

Implementation direction:

-   fixed target: `market-recorder.service`
-   fixed argv
-   `shell=False`
-   bounded timeout
-   no unsafe retry
-   post-action state confirmation
-   fail closed

A narrow polkit rule was installed and verified.

The delegated identity may start/stop only:

``` text
market-recorder.service
```

No broad sudoers/NOPASSWD authority was introduced.

Manager-level systemd operations remain outside this authority.

------------------------------------------------------------------------

# 7. Production Control E2E --- Proven

Production E2E classification:

``` text
PASS_RECORDER_PRODUCTION_CONTROL_E2E
```

Verified sequence:

## STOP

Exactly one real STOP succeeded.

Result:

``` text
HTTP 200
running → stopped
```

Five active recording files were finalized.

Five corresponding archives/manifests were produced.

Integrity verification passed.

## Finalization

For the verified STOP session:

-   5 active files finalized
-   5 archives/manifests created
-   1,422 total records verified
-   zstd decompression passed
-   JSONL validation passed
-   SHA-256 verification passed

## START

Exactly one real START reached systemd and started a new Recorder
process/session.

A transient health confirmation race initially caused the START response
to return 503 despite successful systemd start.

This was fixed using bounded post-start health polling.

No second real START was required for the fix.

Afterward the Recorder was observed:

``` text
running
connected
new PID
new connection identity
messages increasing
no last error
```

------------------------------------------------------------------------

# 8. TradingAI Backend Recorder Proxy

TradingAI Backend has a production Recorder proxy.

It reuses:

-   router
-   service
-   HTTP client
-   URL builder
-   DTO validation
-   configuration
-   error normalization

Read Proxy supports:

-   health
-   status
-   storage
-   archives

Control Proxy supports:

``` text
POST /api/market-recorder/start
POST /api/market-recorder/stop
```

Control requests require explicit:

``` json
{"dry_run": true}
```

or:

``` json
{"dry_run": false}
```

Control metadata includes unique request identity/timestamp/nonce
according to the established contract.

Unsafe POST retries are disabled.

Redirect behavior is restricted.

TLS verification remains enabled.

------------------------------------------------------------------------

# 9. TradingAI UI --- Current Production State

The TradingAI frontend contains a MARKET RECORDER tab.

Production browser verification has passed.

Current UI includes:

-   Recorder Operation
-   Recorder Status
-   Storage
-   Archives
-   Runtime / Diagnostics where applicable

Current control behavior:

``` text
Recorder RUNNING:
    START disabled
    STOP enabled

Recorder STOPPED:
    START enabled
    STOP disabled

Loading / unavailable / unknown / mutation in-flight:
    START disabled
    STOP disabled
```

Duplicate control requests are guarded.

Successful control refreshes:

-   status
-   storage
-   archives

The browser has been verified against production assets.

------------------------------------------------------------------------

# 10. Production UI Asset Activation Finding

A production frontend issue was found after the control UI was
implemented.

The generated bundle existed but nginx could not read the current hashed
assets because of filesystem permissions.

Observed bad state:

``` text
dist/assets = 700
generated files = 600
```

Result:

``` text
JavaScript bundle → HTTP 404
```

Corrected production build permissions:

``` text
directories = 755
files = 644
```

After correction:

-   JS HTTP 200
-   CSS HTTP 200
-   served/local bundle hashes matched
-   Playwright production browser verification passed

Future frontend activation must preserve nginx-readable build
permissions.

------------------------------------------------------------------------

# 11. Current UI Visibility Gaps

The Recorder UI is functional, but not every desirable metric exists
upstream.

Authority-backed/currently usable include:

-   Recorder RUNNING/STOPPED
-   connection state
-   recording time while running
-   event families
-   current file
-   storage
-   active recording size
-   archives
-   reconnect count where exposed
-   last error where exposed

Not currently exposed authoritatively include some fields such as:

-   Exchange
-   Trading Symbols
-   Events/sec
-   per-file Current File Size
-   Queue
-   Dropped Events
-   Heartbeat
-   Latency
-   Buffer

The UI must not fabricate these values.

Use `Unknown`, `Unavailable`, or `Not exposed` as appropriate until the
Recorder contract exposes them.

------------------------------------------------------------------------

# 12. Archive Inventory

Archive inventory exists and is exposed through the Read API.

A global ordering bug was found because mixed timestamp formats were
sorted lexically.

Legacy compact timestamps and ISO timestamps did not sort correctly
together.

This has been repaired.

Current archive ordering behavior:

-   timestamps normalized to aware UTC
-   complete filtered set sorted before pagination
-   deterministic tie-break
-   malformed values handled consistently
-   descending page 1 returns newest entries
-   ascending returns oldest entries

Production read-only verification passed after the repair.

------------------------------------------------------------------------

# 13. Archive / Replay Data Handoff Audit

Completed audit classification:

``` text
PASS_ARCHIVE_ORDERING_AND_REPLAY_HANDOFF_AUDIT
```

Replay readiness:

``` text
READY_FOR_RECORDER_REPLAY_ADAPTER
```

Production archive structure contains compressed JSONL plus sibling
manifest.

Modern recorded data provides:

``` text
ticker
trade
orderbook delta
orderbook_snapshot
system
```

Modern epochs are:

``` text
FULL_ORDERBOOK_REPLAY_READY
```

because snapshot + deltas + sequence/epoch semantics are available.

Some legacy 2026-07-29 data is:

``` text
DELTA_ONLY_REQUIRES_SNAPSHOT
```

and must not be silently treated as full-orderbook replayable.

------------------------------------------------------------------------

# 14. Replay Ordering / Temporal Authority

Relevant production evidence supports deterministic temporal replay
using:

-   `recorder_timestamp_ns`
-   per-stream sequence
-   `book_epoch_id`
-   snapshot + delta ordering

Orderbook reconstruction must validate continuity.

Gap/epoch corruption must fail closed.

------------------------------------------------------------------------

# 15. Known Replay Data Limitation

Production Recorder data currently does NOT constitute a full TradingAI
runtime recording.

Recorder does not record all of:

-   Money Management decisions/state
-   Bot decisions
-   complete account state
-   execution state
-   actual order lifecycle
-   fill lifecycle

Therefore:

``` text
Market-data Replay = supported / ready for adapter
Micro Edge market-response evaluation = intended next phase
Exact full TradingAI runtime replay = not currently supported
Exact production PnL simulation = not currently supported
```

This distinction must be preserved.

------------------------------------------------------------------------

# 16. Recording Session Grouping Gap

A known archive-level gap remains:

Production archives do not yet expose a strong session/recording ID
across the full finalized production recording set.

Grouping can currently rely on timestamp/filename/epoch conventions, but
this is weaker than an explicit recording session identity.

This is not a blocker for beginning the Replay Adapter, but should be
considered when formal dataset/session selection is implemented.

Do not invent a session ID retroactively without a defined contract.

------------------------------------------------------------------------

# 17. Archive UI Actions

Current UI shows archive action buttons, but production routes are not
implemented for:

-   Download
-   Replay
-   Delete

Therefore these controls remain disabled.

This is intentional.

Do not enable them merely because the buttons exist.

Replay should be implemented through the next Replay architecture, not
by wiring an undefined archive action.

------------------------------------------------------------------------

# 18. Recorder Completion Verdict

For the purpose of live recording and operator control, the Recorder
feature is considered operational.

The following production chain is complete:

``` text
Market data
→ Recorder runtime
→ active files
→ STOP
→ finalization
→ compressed archives
→ manifests/checksums
→ START
→ new live recording session
```

And from TradingAI:

``` text
Market Recorder UI
→ TradingAI Backend Proxy
→ Recorder Control API
→ systemd authority
→ live Recorder runtime
```

has been proven in production.

Therefore future GPTs should NOT reopen broad Recorder Runtime
construction unless a concrete defect requires it.

------------------------------------------------------------------------

# 19. What Is Not "Recorder Completion"

Recorder completion does NOT mean the overall data-use project is
finished.

The next value-producing layer is still to be built:

``` text
Recorder Data
→ Replay Adapter
→ Existing Micro Edge
→ Python Evaluator
→ AI Advisor
```

This is a new phase, not a repair of basic recording.

------------------------------------------------------------------------

# 20. Evaluator / AI Advisor Direction

A separate specification exists for:

``` text
TradingAI Replay Evaluator + AI Advisor Integration
```

The intended responsibility split is:

``` text
Recorder
= what actually happened in the market

Replay
= reproduce what TradingAI could have observed at that time

Micro Edge
= make the existing decision using only information available at that time

Python Evaluator
= measure what happened afterward

AI Advisor
= explain results, compare experiments, suggest what to test next
```

AI Advisor must remain read-only.

It must not become the canonical metric calculator.

It must not automatically change production Micro Edge settings.

------------------------------------------------------------------------

# 21. Recommended Next Development Sequence

The next main sequence should be:

## Phase 1 --- Integration Audit

Task:

``` text
TR-REPLAY-EVAL-AUDIT-1A
```

Audit both repositories and map:

``` text
Recorder Archive
→ existing Replay components
→ Micro Edge production entry point
→ feature/state dependencies
→ Evaluator boundary
→ AI Advisor service/context boundary
```

Purpose:

Avoid duplicate engines and identify exact reuse points.

## Phase 2 --- Replay Adapter

Build deterministic reading/reconstruction of modern Recorder data.

## Phase 3 --- Micro Edge Replay Bridge

Feed replayed state into the existing Micro Edge authority.

No duplicate strategy implementation.

## Phase 4 --- Python Evaluator

Measure:

-   forward market response
-   +1/+5/+10/+30/+60s movement
-   MFE
-   MAE
-   direction agreement
-   false-entry baseline
-   later, formally-defined missed opportunities

## Phase 5 --- Experiment Runner

Compare multiple Micro Edge parameter configurations against the exact
same dataset.

No automatic production mutation.

## Phase 6 --- AI Advisor Integration

AI Advisor consumes canonical Evaluator results and provides:

-   explanations
-   comparisons
-   anomaly summaries
-   next experiment suggestions
-   decision-level drill-down

------------------------------------------------------------------------

# 22. Development Policy Going Forward

The user has moved away from endlessly expanding preflight-only work.

For Recorder-related next phases:

-   use the production-capable architecture already proven;
-   test real intended behavior where reasonably bounded;
-   fix concrete runtime defects discovered by those trials;
-   do not return to broad redesign unless evidence requires it;
-   do not weaken trading/security boundaries merely for speed.

Replay/Evaluator work must still remain isolated from live order
execution.

------------------------------------------------------------------------

# 23. Git / Change Safety Context

Historical Recorder and TradingAI work has intentionally avoided
automatic commit/push.

Typical task boundary:

``` text
commit = NO
push = NO
preserve existing dirty/untracked work
```

New GPT sessions must inspect current Git state rather than assume the
historical HEAD remains current.

Do not restore/delete unrelated dirty files.

------------------------------------------------------------------------

# 24. New GPT Session Resume Template

Paste or reference this block when resuming:

``` text
We are continuing TradingAI Market Recorder after production completion.

Important current state:

1. Recorder production recording is working.
2. TradingAI UI → Backend Proxy → Recorder Control API → systemd → Recorder Runtime real STOP/START E2E has passed.
3. STOP finalization/archive/manifest/checksum integrity has passed.
4. UI START/STOP is active in production and state-aware.
5. Archive global ordering across mixed timestamps has been repaired.
6. Modern archives are FULL_ORDERBOOK_REPLAY_READY.
7. Legacy delta-only archives require a snapshot.
8. Recorder does not provide exact full-runtime/PnL replay.
9. Download/Replay/Delete archive UI actions remain disabled because production routes are not implemented.
10. Do not rebuild Recorder from scratch.

Next main objective:

Recorder Archive
→ Replay Adapter
→ existing Micro Edge
→ Python Evaluator
→ AI Advisor read-only analysis.

Start from TR-REPLAY-EVAL-AUDIT-1A unless a newer completed task/report supersedes it.
```

------------------------------------------------------------------------

# 25. Final Current-State Summary

Current Recorder status:

``` text
LIVE RECORDING                 COMPLETE / OPERATIONAL
REAL STOP                      VERIFIED
REAL START                     VERIFIED
FINALIZATION                   VERIFIED
ARCHIVE                        VERIFIED
MANIFEST                       VERIFIED
SHA-256 INTEGRITY              VERIFIED
READ API                       OPERATIONAL
CONTROL API                    OPERATIONAL
SYSTEMD EXECUTION AUTHORITY    OPERATIONAL
TRADINGAI BACKEND PROXY        OPERATIONAL
TRADINGAI UI START/STOP        ACTIVE
ARCHIVE GLOBAL ORDERING        REPAIRED
MODERN ORDERBOOK REPLAY DATA   READY
REPLAY ADAPTER                 NEXT PHASE
MICRO EDGE EVALUATOR           NOT YET IMPLEMENTED
AI ADVISOR EVALUATOR LINK      NOT YET IMPLEMENTED
EXACT PNL REPLAY               NOT SUPPORTED
```

The correct next question is no longer:

``` text
“How do we make Recorder record?”
```

It is:

``` text
“How do we turn the recorded market history into deterministic
Micro Edge evaluation and AI-assisted strategy analysis?”
```
