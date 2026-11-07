# BB-S1 Canonical Supervisor Reconciliation

Read-only audit. No supervisor runtime was implemented. No canonical merge
was performed. No production runtime was connected.

1. TASK_ID
TRADINGAI-WORK-BB-S1-CANONICAL-SUPERVISOR-RECONCILIATION-1

2. VERDICT
BB_S1_SUPERVISOR_RECONCILIATION_PARTIAL

A safe publication path was not found. The current safe state is to keep
Supervisor Runtime UNAVAILABLE. A later held-cache design is required before
any owner-snapshot connection. This audit does not start that design.

3. CANONICAL_HEAD
f344864344b0b99a598f674b3e2e4a367bc9fb25

4. ORIGIN_MAIN
f344864344b0b99a598f674b3e2e4a367bc9fb25

5. BASE_COMMIT
552981c5cf90acbf60ef120c37bb4c4a7b7d7b32

6. WORKTREE
/home/joe4410joe/tradingai_prod_v1.worktrees/ai-supervisor-reconciliation

7. BRANCH
audit/ai-supervisor-reconciliation

8. HEAD_BEFORE
552981c5cf90acbf60ef120c37bb4c4a7b7d7b32

9. HEAD_AFTER
Recorded after the audit document commit. Source code was not changed.

10. CANONICAL_RECONCILIATION
merge-base: 39273a115637edaba42ea49bde732f1ae6436399

`backend/ai_context/` does not exist. The BB context path is `backend/context/`.

| Path | Class |
| --- | --- |
| backend/supervisor/snapshot_builder.py | BOTH_MODIFIED / SHARED_PATH_REVIEW_REQUIRED |
| backend/supervisor/runtime_snapshot_adapter.py | BOTH_MODIFIED / SHARED_PATH_REVIEW_REQUIRED |
| backend/bot_manager/bot_manager.py | BB_ONLY since the merge base |
| backend/bot_manager/owner_snapshot.py | BB_ONLY |
| backend/context/ | BB_ONLY |
| Bot/engine/execution_engine.py | MAIN_ONLY |
| backend/api/money_management.py | MAIN_ONLY |
| backend/money_management/loss_execution_integration.py | MAIN_ONLY |
| backend/money_management/loss_http_api.py | MAIN_ONLY |
| backend/runtime/cycle_diagnostics.py | MAIN_ONLY |
| frontend diagnostics files | MAIN_ONLY / NOT required for this audit |
| tests for contract quantity, manual cycle, MM preview, paper pipeline | MAIN_ONLY |

Main-only snapshot changes are small. They do not add a held cache. They were
not copied.

11. SUPERVISOR_SOURCE_MATRIX

| Item | Finding |
| --- | --- |
| Generation function | `RuntimeSnapshotAdapter.build` calls `build_supervisor_snapshot` |
| Owner | No BotManager-held supervisor snapshot. `get_existing_bot_manager` returns the process instance or None |
| Generation timing | `SupervisorConversationService.respond` calls `build` on each conversation |
| Storage | The return value is used for that response. It is not stored for owner publication |
| Update timing | The next conversation builds again. There is no stored revision for AI context |
| Publication | Not connected to `runtime_domains` |
| Producer timestamp | Not established |
| Snapshot creation time | `capturedAt = self._utc_clock()` after the readers run |
| Read time | Governance and health set `sourceEvaluatedAt` to the captured clock. Bot status comes from `get_status` |
| Publication time | Owner `publishedAt` is separate and must not be reused |
| Freshness | Adapter uses a provisional 30 second source age. The policy comment says no authoritative producer threshold exists |
| Side effects | `build` calls `get_status`, `build_emergency_status`, and Money Management `boundary.get_status` |

`build_supervisor_snapshot` itself maps supplied payloads and does not perform
I/O. The unsafe part is `RuntimeSnapshotAdapter.build`, which gathers those
payloads.

12. MASTER_MM_SHADOW_MATRIX

| Mode | Runtime owner | Evaluation | Held result | Snapshot source | Timestamp | Side effect | AI context |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Master | Conversation service, not BotManager | `evaluate_master_shadow` after MM shadow | Response and audit event for that call only | The snapshot just built | `sourceEvaluatedAt` follows `snapshot.capturedAt` | Provider call when a provider is connected. `grantsExecutionAuthority` is false | Receives shared context only when the caller already passed it |
| MM | Conversation service | `evaluate_mm_shadow` | Response and audit event for that call only | Same snapshot | Same captured clock | Same provider boundary. No order authority | Same shared context |
| Shadow | Conversation mode, not a third agent | Both Master and MM stay `mode=SHADOW` | None beyond the response | Same | Same | `operationalEffect=NONE` | Advice is not execution authority |

There is no separate Shadow supervisor agent id.

13. SIDE_EFFECT_MATRIX

| Call | Class | Static path |
| --- | --- | --- |
| `get_existing_bot_manager` | READ_ONLY_SAFE | Returns `_bot_manager` or None. Does not construct |
| `get_bot_manager` | SIDE_EFFECT_RISK | Constructs `BotManager` when missing. Not used by the adapter |
| `BotManager.get_status` | REQUIRES_EVALUATION | Returns `get_result` |
| `BotManager.get_result` | SIDE_EFFECT_RISK | Assembles status under `market_snapshot_lock` and copies the market snapshot |
| `build_emergency_status` | READ_ONLY_SAFE | Reads `governance_state` and returns a dict. Does not place an order |
| Money Management `boundary.get_status` | REQUIRES_EVALUATION | Reads configuration, hook registration, and cash-flow status under the boundary lock. Not a publication-safe held fragment |
| `RuntimeSnapshotAdapter.build` | REQUIRES_EVALUATION | Calls the readers above and then the pure builder |
| Shadow `evaluate_mm_shadow` / `evaluate_master_shadow` | REQUIRES_EVALUATION | Depends on a freshly built snapshot and may call a provider |
| Account sync | Not on this path | Owner publication must not add it |
| Market data fetch | Not a direct call, but `get_result` copies the live market snapshot | Do not call it from publication |
| Execution preview | MAIN_ONLY `preview_new_entry` | Not present on this branch's publication path. Do not call it |
| Order placement | Not on the snapshot path | `orderEffect` must stay NONE |

No function was executed for this classification.

14. OWNER_SNAPSHOT_COMPATIBILITY

`tradingai-owner-snapshot/v1` already has a `supervisor` allowlist:

- supervisorState
- masterState
- mmState
- shadowState
- lastEvaluation
- currentRecommendation
- revision

`held_runtime_domains` does not fill that domain. A missing fragment stays
`NOT_PUBLISHED`, and runtime evidence reports `UNAVAILABLE`.
`copy_json_snapshot` drops non-JSON values. Secret-like keys and prompt
injection text are removed by the existing publication filter. The schema
does not need a new version for a future allowlisted fragment. None of those
allowlist names exist on `ReadOnlySupervisorSnapshot`.

15. FIELD_MAPPING

| Source field | Owner | Source time | Target | Domain | Provenance | Freshness | Null | Security | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capturedAt | Adapter clock | READ_TIME | none | supervisor | must not become producerObservedAt | provisional only inside the builder | required on the snapshot | observation | NOT_ALLOWED |
| overallFreshness | Builder | derived at read | none | supervisor | not an owner field | provisional 30s | not null | observation | NOT_ALLOWED as CURRENT |
| governance.sourceEvaluatedAt | Adapter | READ_TIME | none | supervisor | stamped from captured clock | provisional | present by construction | observation | NOT_ALLOWED |
| health.sourceEvaluatedAt | Adapter | READ_TIME | none | supervisor | stamped from captured clock | provisional | present when runtime exists | observation | NOT_ALLOWED |
| moneyManagement.evaluatedAt | Builder from MM status | source time only when the payload already has one | none today | money_management already has its own as_of path | do not replace the owner MM observation | provisional 30s is not the owner policy | null stays null | observation, not entry permission | REQUIRES_TIMESTAMP |
| moneyManagement.executionEntryAllowed | MM status, cleared on main when not fresh | not an evaluation completion clock | none | must not become liveOrderAllowed | main-only correction | not owner freshness | true is cleared when not fresh on main | NOT an order grant | NOT_ALLOWED |
| execution.realOrderAllowed | Bot status via get_result | read assembly | none | execution_control already has its own cache | config and status must not be scraped | none | null stays null | authority-sensitive | NOT_ALLOWED |
| market.activeSymbol / selectionMode | Bot status | read assembly | already published from held selection fields | market_selection | existing selection_determined_at | UNKNOWN | null preserved | observation | already mapped elsewhere |
| Master tradingRecommendation | Shadow evaluation | capturedAt | currentRecommendation would be an invention | supervisor | advice only | none | no held value | operationalEffect NONE | REQUIRES_OWNER_CACHE |
| supervisorState, masterState, mmState, shadowState, lastEvaluation, revision | no source field | none | allowlist names | supervisor | absent | UNKNOWN | absent means unpublished | do not invent | UNKNOWN / absent |

No missing field was filled.

16. TIMESTAMP_AUDIT

| Clock | Role |
| --- | --- |
| Adapter `_utc_clock` / `capturedAt` | SNAPSHOT_CREATION_TIME and READ_TIME |
| Governance and health `sourceEvaluatedAt` | Same read clock, not EVALUATION_TIME |
| Master and MM shadow `sourceEvaluatedAt` | Taken from `snapshot.capturedAt` |
| Owner `publishedAt` | PUBLICATION_TIME |
| Bot status timestamps inside `get_result` | Available only by calling `get_status` |

No held supervisor producer timestamp was found. A read clock must not be
stored as one.

17. FRESHNESS_AUDIT
FRESHNESS_POLICY_MISSING for owner publication.

`SnapshotFreshnessPolicy` says the caller supplies the age and that Supervisor
selects no threshold. `DEFAULT_FRESHNESS_POLICY` still installs a provisional
30 second age and a 1 second future tolerance. The adapter comment says this
is not an authoritative producer setting. It must not be copied into runtime
evidence and must not mark Supervisor or Money Management CURRENT.

18. AUTH_BOUNDARY
Operator context remains behind the existing operator session. An
unauthenticated supervisor conversation does not receive operator runtime
evidence. Public context view does not include that operator runtime.
Master, MM, and Shadow share one already-built context when the caller is
authenticated. They do not each build a second runtime reader.

19. SECURITY_AUDIT
The existing owner publication allowlist, JSON copy, secret filter, and
injection filter remain compatible. A future supervisor fragment must use
that path. `ReadOnlySupervisorSnapshot` contains execution and MM permission
fields that must not be copied wholesale. `orderEffect` stays NONE.
`grantsExecutionAuthority` is false on Master and MM contracts. This audit
did not publish a snapshot.

20. IMPLEMENTATION_OPTIONS

OPTION_A. Connect the existing snapshot object to the owner snapshot.
Scope: call or read `RuntimeSnapshotAdapter.build` from publication.
Files: `owner_snapshot.py`, `bot_manager.py`.
Side effect: calls `get_status` / `get_result` and MM `get_status`.
Timestamp trust: capturedAt is a read clock.
Auth boundary: unchanged only if publication stays read-only, which this call is not.
Main conflict: adapter and builder already differ.
Tests: would violate the no-get_status acceptance.
Recommendation: reject.

OPTION_B. Store a copy after an evaluation already finishes.
Scope: conversation `respond` after `build` and shadow evaluation.
Files: `conversation_service.py` plus a new held field and `owner_snapshot.py`.
Side effect: the evaluation has already run for the conversation, but the stored snapshot was produced by those reads.
Timestamp trust: the stored clocks are still the read clock.
Auth boundary: must not let an unauthenticated response become operator evidence.
Main conflict: low for the hook, high if the snapshot fields are copied.
Tests: must prove no second build and no CURRENT claim.
Recommendation: not safe until a non-read-clock timestamp exists. This is a design task, not a connection task.

OPTION_C. Reuse the main snapshot during canonical integration.
Scope: take main's builder changes.
Files: `snapshot_builder.py`, `runtime_snapshot_adapter.py`.
Side effect: same live readers remain.
Timestamp trust: main changes MM timestamp preference and clears a non-fresh entry flag. It does not create a producer clock.
Auth boundary: the cleared entry flag is safer, but it is still not an owner cache.
Main conflict: this is the conflict. It must be reconciled deliberately, not copied here.
Tests: main preview tests were not imported.
Recommendation: reject for BB publication. Keep it as a shared-path item.

OPTION_D. Leave Supervisor Runtime UNAVAILABLE.
Scope: no code change.
Files: none.
Side effect: none.
Timestamp trust: no false producer time.
Auth boundary: preserved.
Main conflict: none.
Tests: existing BB6H2 acceptance already expects UNAVAILABLE.
Recommendation: current safe state.

21. RECOMMENDED_OPTION
OPTION_D now. OPTION_B only after `BB_SUPERVISOR_HELD_CACHE_DESIGN` finds a
result that is already stored and whose timestamp is not the read clock,
publication clock, or provisional freshness window.

22. MINIMUM_IMPLEMENTATION_PLAN
Do not implement it in this task.

When a later design finds a safe held result, the smallest connection is:

- Owner: the component that already stored the completed result. Today that owner does not exist on BotManager.
- Publication point: `BotManager._publish_context_snapshot` through `held_runtime_domains`. No new reader.
- Held cache: a JSON object written only after the existing evaluation returns, not by calling `build`.
- Allowlist: only the existing `supervisor` names that the held object actually contains. Do not invent supervisorState or a recommendation.
- Timestamp source: a field written when the evaluation completed. `capturedAt` is excluded.
- Freshness: UNKNOWN unless an existing non-provisional policy is attached. The 30 second provisional age is not that policy.
- Runtime evidence: the existing `supervisorRuntime` domain. Missing cache stays UNAVAILABLE.
- Consumption: the existing shared operator context. Advisor and authenticated Supervisor already read it.
- Security: operator session, public-view exclusion, secret filter, injection filter, `orderEffect=NONE`.
- Regression: the BB6H2 suite plus tests that `get_status`, `get_result`, and `boundary.get_status` are absent from publication.
- Main conflict: do not merge `snapshot_builder.py` or `runtime_snapshot_adapter.py` as part of that hook.

23. CHANGED_FILES
This audit document only. No source code.

24. TEST_RESULTS
TESTS_NOT_RUN=READ_ONLY_AUDIT

BB6H2 baseline remains 667 PASS / 0 FAIL. That baseline was not re-executed
and is not a new PASS.

25. COMMIT
The audit document may be committed. No source commit.

26. REMAINING_GAPS
- No held supervisor snapshot.
- Allowlist names do not match `ReadOnlySupervisorSnapshot`.
- Read clock and provisional 30 second freshness cannot support CURRENT.
- Main builder and adapter differ and must not be copied blindly.
- MM `executionEntryAllowed` and execution `realOrderAllowed` on the snapshot are not live-order authority.

27. NEXT_RECOMMENDED_TASK
BB_SUPERVISOR_HELD_CACHE_DESIGN

`BB_S2_SUPERVISOR_OWNER_SNAPSHOT_INTEGRATION` is not ready.
`BB_CANONICAL_SHARED_PATH_RECONCILIATION` remains a separate later task for
the main snapshot diff. It was not started.
