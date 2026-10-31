# Canonical AI Context Pack Specification (`tradingai-context/v1`)

Status: Phase 1 foundation. Not an external-sharing acceptance.
Authority: read-only. See the SAFETY section of every Context Pack.

## 1. Purpose

The Canonical Context Pack gives AI Advisor and Supervisor one deterministic,
auditable view of three independent truth systems:

| Truth system | Owner | Phase 1 source |
| --- | --- | --- |
| SOURCE TRUTH | Git repository state | `backend/context/source_truth.py` (READ-ONLY) |
| RUNTIME TRUTH | Existing runtime authorities | existing Supervisor `ReadOnlySupervisorSnapshot` |
| PROJECT TRUTH | Workstream registry | `docs/ai/PROJECT_STATE.yaml` |

The builder never invents a value. A fact is either `PRESENT`, `ABSENT`,
`NULL`, `UNKNOWN`, or `UNAVAILABLE`.

## 2. Schema

`schemaVersion` is fixed to `tradingai-context/v1`.

Top-level sections, in canonical order:

```
schemaVersion, generatedAt, generator,
source,
runtime, marketSelection, executionControl, market, moneyManagement,
governance, tradingCycle, position, orders, smallAccount, account,
emergency, health,
contracts, workstreams, knownIssues, acceptedTests,
safety, freshness, provenance
```

Each observation section carries a `meta` object:

- `source` - producer or reader name
- `observedAt` - timezone-aware timestamp or `null`
- `freshness` - `FRESH` / `STALE` / `UNKNOWN` / `NOT_APPLICABLE`
- `availability` - `AVAILABLE` / `STALE` / `UNKNOWN` / `UNAVAILABLE`
- `provenance` - ordered list of `{source, reader, observedAt, detail}`
- `detail` - bounded explanation

Each field carries `{name, value, state, source, observedAt, freshness}` and a
`state` of `PRESENT` / `ABSENT` / `NULL` / `UNKNOWN` / `UNAVAILABLE`.

## 3. Source Truth rules

- Git inspection uses fixed argument vectors, `shell=False`, and a timeout.
- No HTTP request or caller input is interpolated into a command.
- `HEAD`, `origin/main`, ahead/behind, dirty state, and worktrees are read-only.
- `deployedCommit` is populated only from explicit caller-supplied Production
  evidence. The local `HEAD` is never reported as the deployed commit. When
  evidence is absent, `deployedCommit` is `null` and
  `deployedCommitState` is `UNKNOWN`.

## 4. Project Truth rules

- Workstreams are registered for A, A1, A2, A-INTEGRATION, B, C, D, F, G, H,
  J, AA, MM, BB.
- A missing status defaults to `UNKNOWN`, never to `COMPLETE`.
- `status: COMPLETE` or `DEPLOYED` is rejected unless `verification: VERIFIED`.
- `verification: VERIFIED` requires `lastVerified` and at least one
  `evidenceReferences` entry.
- Duplicate identifiers are rejected.
- A missing registry file is reported as `UNAVAILABLE`; a malformed file is an
  error.

## 5. Builder purity

`build_canonical_context` is a pure function. It performs no network access, no
LLM call, no order submission, no runtime mutation, no file write, and no Git
mutation. All time is caller-supplied through `generated_at`.

`RuntimeTruthSource` wraps the existing `ReadOnlySupervisorSnapshot`; existing
Supervisor and Advisor contracts are unchanged. Optional extra sections can be
supplied only for the canonical section names.

## 6. Serialization

- `to_canonical_json` emits sorted keys, compact separators, UTF-8, and no NaN.
- Identical inputs produce identical bytes.
- `to_markdown` renders a deterministic read-only view.
- No HTTP endpoint or external publication exists in Phase 1.

## 7. Safety boundary

```
contextRead: true
sourceWrite: false
runtimeWrite: false
orderWrite: false
liveOrder: false
productionDeploy: false
secretsIncluded: false
paperLiveAuthorityUnchanged: true
botManualAuthorityUnchanged: true
emergencyStateUnchanged: true
```

Secret-like field names are excluded and secret-like string values are replaced
with `[REDACTED:SENSITIVE]`. `.env` content is never read or emitted.

## 8. Phase boundary

Phase 1 completes the Canonical Context Foundation. Automated sharing with an
external AI is explicitly out of scope and not claimed.

## 9. Runtime truth integration

`compose_tradingai_context` is an in-process composition entry point. It keeps
`build_canonical_context` pure and keeps `schemaVersion` at
`tradingai-context/v1`. There is still no HTTP route, MCP server, WebSocket, or
external-AI publication.

The composer accepts an existing `ReadOnlySupervisorSnapshot` plus injected
projections:

- bot status mapping
- account projection
- money-management projection
- trading-cycle diagnostics
- current-position view, or an account snapshot plus an observation clock
- execution-control projection
- source truth and project truth

Injected values are normalized by read-only readers. The readers do not call
the exchange, do not calculate a new risk figure, and do not change bot,
order, money-management, or emergency authority. `generated_at` is only the
context stamp. A runtime section is `FRESH` only when the producer timestamp
and an explicit fresh claim are both present. A missing producer timestamp
makes `freshness=UNKNOWN`. `HISTORICAL` diagnostics stay historical.

Position status remains `OPEN`, `FLAT`, or `UNKNOWN`. Multiple or contradictory
positions are not collapsed into one `OPEN`. PAPER and LIVE balances stay in
separate fields. `realOrderAllowed` is true only when the injected projection
explicitly says so; otherwise it stays fail-closed and does not override an
explicit Supervisor boolean.

Fields the existing projections do not carry stay `UNAVAILABLE`. That includes
position `avgExit`, `exitTime`, `pnlPercent`, and exit-parameter fields unless
the injected position view already contains them, plus `takeProfitPercent`,
`trailingPercent`, and `timeExitSeconds` unless the injected MM projection
contains them, and `currency` unless the account projection contains it.

## 10. Read-only collector and context views

`collect_runtime_context` (also exported as `collect_tradingai_context`) is an
in-process entry point. It calls `compose_tradingai_context` with values that
the caller injects. It does not create a BotManager, call `get_status` or
`get_result`, contact an exchange, or start a scheduler. A missing reader
stays `UNAVAILABLE` with category `READER_NOT_INJECTED`. A reader exception is
recorded as `READER_FAILED` without the exception text.

`current_position` runs only when the caller supplies an account snapshot and
an observation clock. `generated_at` remains the context stamp.
`freshness.evaluatedAt` is that stamp, not a runtime observation.
`section.meta.observedAt` is the producer time when one was proven.
`diagnosticScope=UNKNOWN` is not rewritten to `CURRENT`.

`trailing_stop_distance_percent` is not copied into `trailingPercent`.

Two views are pure projections of the canonical pack:

- `PUBLIC_CONTEXT` is an allowlist: schema version, safety flags, freshness
  vocabulary, public project status, safe `docs/ai/` references, and source
  availability. It omits balances, positions, authority, emergency state,
  credentials, and absolute paths.
- `OPERATOR_CONTEXT` can include runtime, position, account, MM, trading
  cycle, and execution sections that are already on the canonical allowlist.
  It still removes credentials, raw exceptions, and absolute paths. Building
  the view does not mean the caller was authenticated.

Unknown field names are dropped. Secret-like keys are dropped at every depth.
Oversized strings and lists are replaced with an unavailable reason. They are
not truncated. A view larger than the payload limit is replaced by
`PAYLOAD_LIMIT_EXCEEDED` and the original body is not returned.

There is still no MCP server, WebSocket, or external-AI client.
`production_runtime_connected` is false. The read-only HTTP router in section
11 is not mounted on the Production application.

## 11. Authenticated read-only context router

`backend/context/api_router.py` defines `GET /api/ai-context/operator` and
`GET /api/ai-context/operator.md`. Both routes depend on the existing
`require_operator_session`. A missing, invalid, or expired operator session
returns HTTP 401 with `{"status":"UNAUTHENTICATED"}` and no context body.
The router does not inspect a cookie or an API key itself. Session validation
stays in `OperatorSessionMiddleware`.

GET is a safe method under the existing CSRF policy, so this read router does
not add a new authenticator or a new CSRF scheme. It also does not add a
write route.

The response is the BB-4A operator view plus the flags
`productionRuntimeConnected=false`, `productionApiAvailable=false`, and
`publicEndpointEnabled=false`. Markdown renders that same envelope.
`to_markdown` on the raw canonical pack is not used. Payload overflow stays
`PAYLOAD_LIMIT_EXCEEDED` and is not truncated.

`backend/main.py` includes `context_router` once. That registration does not
call `get_bot_manager`, `get_status`, or `get_result`, and it does not add a
public route. `create_isolated_context_app` remains a test helper and is not
called from `main.py`.

Source registration is not a Production deploy. `productionRuntimeConnected`
and `productionApiAvailable` stay false. Uninjected readers remain
`READER_NOT_INJECTED`, and `diagnosticScope` is not promoted to `CURRENT`.

No public context endpoint is registered. The application startup hook is not
used to exercise this router, because that hook starts the bot manager and
supervisor control plane.

## 12. Verified runtime reader adapter

`backend/context/runtime_reader_adapter.py` calls three readers whose
implementations were checked for I/O and mutation, and only when the caller
injects their inputs:

- `current_position`, with an explicit observation clock
- `build_trading_cycle_diagnostics`, when a decision, runtime result, or cycle
  context mapping is injected
- `build_supervisor_snapshot`, when at least one status payload is injected
  together with `captured_at` and a freshness policy

The adapter then passes those results to `collect_runtime_context`. It does
not construct a BotManager or Supervisor, and it does not call `get_status`,
`get_result`, `get_bot_manager`, the account runtime, the money-management
HTTP boundary, or an exchange. A supplied bot manager is recorded as skipped.

Account, money-management, and execution mappings are forwarded only when the
caller already holds them. That passthrough does not make their live producers
connected. `trailing_stop_distance_percent` is not aliased. Missing currency,
take-profit, and time-exit values stay unavailable.

`generated_at` remains the pack stamp. It is not used as `captured_at`,
`evaluated_at`, or the position clock. One reader failure does not drop the
other sections, and the exception text is not copied into the pack.

This adapter is not registered on the FastAPI router or on application
startup. `productionRuntimeConnected` stays false.

## 13. Explicit snapshot injection boundary

`inject_verified_runtime_snapshots` in `backend/context/injection_boundary.py`
is the caller-facing hook. It copies JSON-like snapshots and then calls
`collect_verified_runtime_context`. It does not fetch a live runtime.

A slot is copied only when every nested value is `None`, a boolean, a finite
number, a bounded string, a string-keyed mapping, or a list. Locks, sockets,
clients, and managers are rejected. The caller's mapping is not modified.
A matching pair of cycle ids is not treated as `CURRENT` unless the injected
decision, runtime, context, or `cycle_evaluated_at` also carries a producer
timestamp. `generated_at` is not that timestamp.

Account, money-management, and execution mappings are still passthrough.
A non-boolean `realOrderAllowed` is dropped from the copy so the projector
fail-closes. The mounted operator route reads an owner snapshot only through
the bridge in section 15. `productionRuntimeConnected` stays false.

## 14. Non-refreshing snapshot copy

`copy_json_snapshot` and `copy_injection_inputs` in
`backend/context/snapshot_copy.py` copy caller-owned JSON data. The same
copier is used by the injection boundary. Circular references, excessive
depth, non-finite numbers, and non-JSON objects are rejected. The rejection
token does not include the input.

The copy does not read BotManager, Supervisor, account refresh, the
money-management boundary, or an exchange. It does not take a runtime lock.
A running producer can change a mapping while the caller is still holding it,
so a copied mapping is consistent only when the owner already copied it under
the owner's own lock. That live source is `LIVE_SOURCE_NOT_SAFE`. The context
package records `OWNER_PROVIDED_COPY_REQUIRED` and does not acquire the lock.

`copy_injection_inputs(...).values` can be passed to
`inject_verified_runtime_snapshots`. Producer timestamps already inside the
mapping are preserved. A missing timestamp stays missing. The copy time is
not written into `observedAt`, `evaluatedAt`, or `diagnosticsGeneratedAt`.
Matching cycle ids still do not become `CURRENT` without a producer time.
`productionRuntimeConnected` stays false.

## 15. Owner-published BotManager snapshot

`BotManager.export_context_snapshot` returns the last document stored by
`BotManager._publish_context_snapshot`. The document schema is
`tradingai-owner-snapshot/v1`. The initial document is `UNAVAILABLE` and does
not invent a mode, a position side, or a loop state.

The publisher copies a paper-account mapping only when the caller already
holds that mapping, or when `paper_capital_lock` can be taken without waiting.
It copies a runtime result only when the observation path already received
that result. The JSON copy is `copy_json_snapshot`. The publication lock is
taken only after the paper lock is released. Context code does not take either
lock.

`publishedAt` is the owner store time. `observedAt` and `producerObservedAt`
stay empty unless a later producer clock is supplied inside the payload.
A matching cycle id is not marked `CURRENT` by the owner.

The real-account cache, execution authority, money-management status, and the
supervisor adapter are not published. Their names stay on `unavailable`.

The operator routes call `copied_owner_export` only for an owner that is
already loaded in the process, or for a lookup the isolated app supplies.
The context package does not import the BotManager module and does not call
the constructor helper. `export_context_snapshot` is copied with
`copy_json_snapshot`, then `copy_injection_inputs`, then
`inject_verified_runtime_snapshots`. Paper mode is the only account mode
accepted from the owner document. A stored runtime result is injected without
a new cycle evaluation. `publishedAt` is not written into `observedAt`.
`generated_at` is not written into `cycle_evaluated_at`. A cycle id alone
does not become `CURRENT`.

`PRODUCTION_RUNTIME_CONNECTED`, `PRODUCTION_API_AVAILABLE`, and deployment
stay false. An isolated HTTP 200 is not production connectivity.

## 16. Advisor and Supervisor answer attachment

The authenticated Advisor browser conversation and an authenticated Supervisor
conversation may attach the same operator view as read-only data. The
attachment uses `load_shared_operator_context`. It does not call the operator
HTTP route, and it does not construct a BotManager.

An unauthenticated Supervisor conversation does not receive the operator view.
The existing snapshot, prompt, provider selection, and response fields stay in
place. Context failure is `UNAVAILABLE` and does not replace the existing
answer path.

`contextGeneratedAt` is the attachment clock. It is not `producerObservedAt`
or `producerEvaluatedAt`. Paper account time and a stored runtime result time
stay distinct. REAL account, execution authority, money-management runtime,
and supervisor runtime stay `UNAVAILABLE`. The attachment cannot start or stop
a bot, submit an order, or change execution authority.

`productionRuntimeConnected` and `productionApiAvailable` stay false.

## 17. Source evidence on authenticated answers

`read_source_truth` reads Git coordinates. It does not return source text.
Authenticated Advisor and Supervisor questions add a separate `sourceEvidence`
object through `collect_source_evidence`. The object is read-only answer
data. It is not part of the runtime operator view and it does not change
PAPER account, position, or stored cycle fields.

The reader uses a fixed catalog under `backend/`, `frontend/src/`, and
`docs/`. It does not accept an absolute path or a `..` segment. Symbolic
links are rejected. `.env`, credential, secret, cookie, and key filenames
are rejected. A missing catalog symbol stays `UNKNOWN` or `UNAVAILABLE`.
The reader does not invent a function.

`sourceRevision` is the HEAD returned by `read_source_truth` for the
repository that was read. `productionRevision` stays `UNKNOWN`. A Git
revision is not a runtime producer timestamp and it is not proof that
Production is running that commit. Multiple catalog hits stay multiple
candidates. The evidence does not assert a single order controller.

An unauthenticated Supervisor conversation does not call the source reader.
Source failure leaves the existing answer path in place. Source comments
remain inside `BEGIN_UNTRUSTED_SOURCE_EVIDENCE` and are not instructions.

## 18. Project evidence on authenticated answers

`load_project_truth` reads `docs/ai/PROJECT_STATE.yaml`. A missing registry is
`UNAVAILABLE`. The reader does not upgrade a workstream to `COMPLETE` or
`DEPLOYED`. `load_authoritative_specifications` reads only the hash-pinned
manifest under `docs/`. A filename containing FINAL or APPROVED is not
authority. A Git commit is not a production revision.

Authenticated Advisor and Supervisor questions add `projectEvidence` beside
`sourceEvidence`. The same shared loader serves Advisor, Supervisor Master,
Supervisor MM, and the SHADOW conversation. An unauthenticated Supervisor
conversation does not call the project reader. The operator view is not
replaced.

`designStatus` is `DESIGNED` only when a hash-verified manifest entry matches
the question. `implementationStatus` stays `UNKNOWN` unless the registry
records `COMPLETE` with `VERIFIED`. `deploymentStatus` stays `UNKNOWN` unless
the registry records `DEPLOYED` with `VERIFIED`. `runtimeStatus` stays
`UNKNOWN`. `productionRuntimeConnected` stays false. `productionRevision`
stays `UNKNOWN`. `changeHistory` stays `UNKNOWN` because no changelog reader
is connected.

`projectRevision` is the manifest spec version. It is not a fabricated Git
revision. `projectUpdatedAt` is copied only from the registry `updatedAt`.
Same-rank manifest conflicts select no document. Document text stays inside
`BEGIN_UNTRUSTED_PROJECT_EVIDENCE` and is not an instruction. A project-reader
failure leaves source evidence and the operator view in place.

## 19. Decision evidence on authenticated answers

`KnowledgeHistoryQueryFacade` is the only history reader used here. It reads
existing cycle-evidence and trading-trace records. Constructing the facade
does not perform I/O. A query does not write the store, create a bot, call an
exchange, or call a model provider.

Authenticated Advisor and Supervisor questions add `decisionEvidence` beside
`sourceEvidence` and `projectEvidence`. The same shared loader serves Advisor,
Supervisor Master, Supervisor MM, and the SHADOW conversation. An
unauthenticated Supervisor conversation does not call the history reader.

Every returned record is `HISTORICAL`. `currentApplicability` stays
`UNKNOWN`. A past PAPER, execution, MM, or Supervisor record does not prove
the current runtime. `decisionReason` is copied only from a recorded reason
field. A missing reason stays `UNKNOWN`. `decisionTimestamp` is copied only
from the record time. `SUPERSEDED` and `REVOKED` are used only when the record
says so. A newer record does not supersede an older one by itself.

`decisionId` is the existing evidence or event identifier. No decision id is
invented. The query limit is four items. Recorded text stays inside
`BEGIN_UNTRUSTED_DECISION_EVIDENCE` and is not an instruction. The Money
Management specification hash mismatch remains `HASH_MISMATCH` / `UNKNOWN`.
`productionRuntimeConnected` stays false.

## 20. Runtime evidence on authenticated answers

`copied_owner_export` copies the owner-published snapshot. It does not import
BotManager, call `get_bot_manager`, call `get_result`, or build an execution
engine. `publishedAt` is not a producer timestamp and is not copied into
runtime evidence.

Authenticated Advisor and Supervisor questions add `runtimeEvidence` beside
source, project, and decision evidence. The same shared loader serves Advisor,
Supervisor Master, Supervisor MM, and the SHADOW conversation. An
unauthenticated Supervisor conversation does not build that evidence.

The owner document does not publish money management, execution control, real
account, or supervisor. Market selection and market intelligence are not in
the publication. Those domains stay `UNAVAILABLE`, with `runtimeTimestamp`
`UNKNOWN` and `runtimeFreshness` `UNKNOWN`. None of them is `CURRENT`.
`runtimeValues` stays null. PAPER account, PAPER position, and the stored
cycle result remain on the operator view and are not relabeled as those
domains.

Decision evidence stays historical and is not runtime truth. The Money
Management specification hash mismatch remains `HASH_MISMATCH` / `UNKNOWN`.
`productionRuntimeConnected` stays false.

## 21. Integrated knowledge acceptance

Authenticated Advisor and Supervisor answers can carry source, project,
decision, and runtime evidence together. Each object keeps its own
`truthKind`. A catalog miss stays a source result. A missing specification
stays a project result. Recorded history stays `HISTORICAL`, with
`currentApplicability` `UNKNOWN`. The six runtime domains stay `UNAVAILABLE`
until an owner snapshot publishes a producer timestamp and verified values.

When the operator view exceeds the render budget, the Advisor block keeps the
bounded evidence objects and leaves the oversized view out of that block.
Supervisor payloads still receive the full attachment. An unauthenticated
Supervisor conversation does not collect operator evidence. This acceptance
does not connect production runtime and does not treat the Money Management
hash mismatch as a current runtime failure.

## 22. Explicit owner runtime domains

`merge_owner_snapshot` accepts `runtime_domains` only when the caller already
holds the fragment. It does not evaluate authority, and it does not use
`publishedAt` as a producer time.
Allowlisted fields are copied. Secret-like keys are dropped. Null stays null.
Peak equity is not created.

A missing producer timestamp stays `UNKNOWN` and is not `CURRENT`. An owner
freshness label of `STALE` stays `STALE`. Money Management can be `CURRENT`
only when the fragment includes a producer timestamp and the existing
`moneyManagement` freshness policy, and the age is inside that policy.
The other domains stay `UNKNOWN` even when a timestamp is present. Omitted
domains stay `UNAVAILABLE`. The Money Management specification hash mismatch
remains `HASH_MISMATCH` / `UNKNOWN`. `productionRuntimeConnected` stays false.

## 23. Held owner cache wiring

The default publication copies a cache only when the owner already stores it.
A live-account cache is included only when `lastSync` is a producer time.
An unsynced placeholder stays unpublished. Money Management is included only
when `snapshot()` reports a valid observation. Its read does not start a new
evaluation, and peak equity is not added. Execution publication copies
`emergencyStop` and a scalar `pendingOrder` from runtime state. It does not
read configuration and does not reevaluate authority. Market selection copies
`selection_mode` and the active symbol. Market intelligence copies the symbol
and data quality from `market_snapshot`, not the order book or trades.
Supervisor has no held snapshot on this path, so it stays unpublished.
`publishedAt` is still not a producer timestamp. Missing timestamps stay
`UNKNOWN` and are not `CURRENT`.

## 24. Runtime coverage acceptance

The default publication path can be verified with an isolated owner. That
verification is a code-path check. It is not a production connection.
Execution authority remains partial: `emergencyStop` and a scalar
`pendingOrder` do not grant entry or a live order. Money Management uses
`as_of` only when the observation is valid, and it is not `CURRENT` without
the existing freshness policy. A live account without `lastSync` stays
unpublished. Supervisor runtime stays unpublished. Market selection has no
producer timestamp. Market intelligence publishes symbol and data quality
only. `productionRuntimeConnected` stays false.

## 25. Safe owner cache completion

Execution authority publication can include booleans already returned by
`_arm_live_order_entry` or `_disarm_live_order_entry`. The cache is written
after that result exists. Publication does not read configuration, call
`preview_new_entry`, or arm the engine. `emergencyStop=false` does not create
`liveOrderAllowed`. `orderEffect` stays `NONE`.

Market selection stores `selection_determined_at` when an existing assignment
of `selection_mode` or the active symbol completes. `lifecycle_changed_at`,
`publishedAt`, and `readAt` are not used as that clock. The timestamp does not
make the domain `CURRENT`.

Supervisor runtime stays unpublished. The snapshot adapter evaluates and
stamps its read clock, and the main-branch snapshot builder is not copied.
Money Management still has no stored freshness age. No TTL is invented, so a
valid observation stays `UNKNOWN` rather than `CURRENT`. A synced live-account
cache and the lightweight market snapshot stay on the previous wiring.
`productionRuntimeConnected` stays false.

## 26. Runtime coverage reacceptance

The BB6G3 caches can be checked through the existing publication path with an
isolated owner. An arm or disarm result already stored in
`execution_authority_cache` is copied into `execution_control` and then into
runtime evidence. `entryAllowed`, `liveOrderAllowed`, `realOrderAllowed`, and
`rootBlocker` keep the stored result. A later disarm result replaces an older
arm result. `emergencyStop=false` and `pendingOrder=false` do not create
`liveOrderAllowed`. The determination time is `producerObservedAt`. Without a
freshness policy the evidence status stays `UNKNOWN`, not `CURRENT`.

`selection_determined_at` is the market-selection producer time.
`lifecycle_changed_at` is not that clock. The time alone is not `CURRENT`.

Supervisor runtime stays `UNAVAILABLE`. Money Management stays `UNKNOWN`
without a stored freshness age. A live account is published only with a
parsed `lastSync`, and `stale=true` stays `STALE`. Market intelligence keeps
the symbol, data quality, and snapshot time, not the order book, trades, or
probability. This check does not connect production runtime.
`productionRuntimeConnected` stays false.

