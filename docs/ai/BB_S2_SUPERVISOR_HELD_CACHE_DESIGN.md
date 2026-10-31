# BB-S2 Supervisor Held Cache Design

Design only. No held cache is implemented. No source module was changed.
No production runtime is connected.

## Current Architecture

`SupervisorConversationService.respond` builds a snapshot, then evaluates MM
shadow, then evaluates Master shadow when the caller is Master.

`RuntimeSnapshotAdapter.build` reads live sources. `get_status` returns
`get_result`. Governance and health `sourceEvaluatedAt` are the adapter
`capturedAt` read clock. `build_supervisor_snapshot` only maps payloads it
is given.

The returned `MMShadowRuntimeResult` and `MasterShadowRuntimeResult` live
for that response. BotManager does not store them. `held_runtime_domains`
does not publish `supervisor`, so runtime evidence stays `UNAVAILABLE`.

`backend/ai_context/` does not exist. The context path is `backend/context/`.

Canonical comparison against origin/main, merge-base
`39273a115637edaba42ea49bde732f1ae6436399`:

| Path | Class |
| --- | --- |
| backend/supervisor/snapshot_builder.py | SHARED_PATH_REVIEW_REQUIRED |
| backend/supervisor/runtime_snapshot_adapter.py | SHARED_PATH_REVIEW_REQUIRED |
| backend/supervisor/conversation_service.py | BB conversation context; not in the main-only name list |
| backend/bot_manager/owner_snapshot.py | BB_ONLY |
| backend/context/ | BB_ONLY |

Main changes are not copied. They are not required for this design.

## Evaluation Lifecycle

| Point | What happens |
| --- | --- |
| Entry | `respond` validates the shadow conversation capability |
| Snapshot | `snapshot_adapter.build(app)` reads runtime. This is not the cache write |
| MM evaluation | `evaluate_mm_shadow` returns `MMShadowRuntimeResult` |
| Master evaluation | `evaluate_master_shadow` returns `MasterShadowRuntimeResult` only for Master |
| Completion | A result with `status=COMPLETED` and `failureCode=None` is a finished evaluation |
| Lifetime | The Python return value. It is not retained for a later publication |
| Conversation scope | One response. Shadow mode. `operationalEffect=NONE` |
| Runtime scope | Not a continuous supervisor runtime. A later publication of this result is historical conversation output, not `CURRENT` runtime |

Clocks already on the result:

| Field | Meaning | Cache use |
| --- | --- | --- |
| snapshot.capturedAt | Read clock inside `build` | Do not use |
| assessment.sourceEvaluatedAt / decision.sourceEvaluatedAt | Required to match the snapshot clock | Do not use |
| assessment.assessedAt / decision.decidedAt | The `now` passed into the evaluator before the provider work finishes | Do not use as completion time |
| audit.runtimeEvaluatedAt | That same passed-in clock | Do not use |
| audit.snapshotCapturedAt | Read clock | Do not use |

A conversation result does not make supervisor runtime `CURRENT`.

## Held Cache Owner

| Option | Decision |
| --- | --- |
| A. Conversation owner retains the completed result | Recommended |
| B. A supervisor runtime owner retains it | No such owner holds a result today |
| C. BotManager retains a received result | Rejected as the owner. Publication may copy the held JSON, but BotManager does not evaluate and must not call `build` |
| D. Stay UNAVAILABLE | Required until the write below exists. It is the current code state, not the target design |

Recommended owner: `SupervisorConversationService`, storing bytes in a new
leaf module `backend/supervisor/held_evaluation_cache.py`.

`supervisor/__init__.py` already imports the conversation service. The leaf
module must not import `bot_manager`, `owner_snapshot`, or `backend.context`.
`owner_snapshot.held_runtime_domains` may import the leaf module inside the
function. That avoids a cycle.

| Item | Design |
| --- | --- |
| OWNER | SupervisorConversationService |
| WRITE_POINT | Immediately after `evaluate_mm_shadow` or `evaluate_master_shadow` returns `COMPLETED` |
| READ_POINT | `held_runtime_domains` copies the leaf JSON. It does not receive the BotManager as the supervisor owner |
| LIFETIME | Process memory. Last successful MM slot and last successful Master slot |
| THREAD_SAFETY | One lock inside the leaf module |
| TIMESTAMP | New `evaluationCompletedAt` taken at the write, after return |
| PROVENANCE | `evaluationKind=CONVERSATION_SHADOW`, `sourceOwner=SupervisorConversationService`, audit `eventId` |
| SIDE_EFFECT_RISK | None on the read. The write does not call `build`, `get_status`, or `get_result` |
| MAIN_CONFLICT_RISK | Low if snapshot builder and adapter are not edited |
| TESTS | Fake completed results and failed results. No live provider |

## Write and Read Points

Write only when `status` is `COMPLETED` and `failureCode` is `None`.
The MM contract already rejects a completed result that has a failure code.

Do not write when evaluation fails, the provider is missing, validation
fails, or an exception leaves the call before a completed result. A failed
call must not replace the previous successful slot.

Do not write the in-progress snapshot. `build` stays where it is and its
return value is not the cache.

A Master call that completes MM and then fails Master updates only the MM
slot when MM completed. It does not clear the previous Master slot.

The read copies the current JSON under the leaf lock and returns. Missing
holder data stays `UNAVAILABLE`. A copy with no `evaluationCompletedAt`
stays `UNKNOWN` and is not `CURRENT`.

Forbidden on the read: `RuntimeSnapshotAdapter.build`, `get_status`,
`get_result`, supervisor reevaluation, account sync, market fetch, MM
recalculation, and order placement.

## Cache Contract

This is a proposed holder shape. These names are not current snapshot fields.

Published through the existing allowlist:

| Holder field | Source that already exists | Published allowlist name |
| --- | --- | --- |
| mmState | `assessment.assessmentState` when MM completed | mmState |
| masterState | `decision.overallPosture` when Master completed | masterState |
| shadowState | `result.mode`, which is `SHADOW` | shadowState |
| currentRecommendation | `decision.tradingRecommendation` when Master completed | currentRecommendation |
| lastEvaluation | the new completion clock of the newer successful slot | lastEvaluation |
| revision | holder counter | revision |

Not published, because the allowlist has no such name or the value must not
be copied:

| Candidate | Treatment |
| --- | --- |
| supervisorState | No source field. Leave it absent. Do not invent it |
| evaluationId | Audit `eventId`. Holder metadata only |
| evaluationCompletedAt | Holder clock. Published only as `lastEvaluation` / `producerObservedAt` |
| evaluationKind | `CONVERSATION_SHADOW`. Provenance, not a new domain field |
| sourceOwner | `SupervisorConversationService` |
| operationalEffect | Existing literal `NONE`. Do not map it to an order field |
| grantsExecutionAuthority | Existing class value `false`. Do not publish a permission |
| reasons, summary, uncertainties, prompts, history | Do not copy. They are not the runtime allowlist |
| capturedAt, assessedAt, decidedAt, sourceEvaluatedAt | Do not copy into the producer time |

Null stays null. An absent Master recommendation stays absent after an
MM-only success.

## Timestamp Semantics

`evaluationCompletedAt` is recorded at the write point by calling the
conversation clock after the evaluator has returned `COMPLETED`.

It is not `capturedAt`, `publishedAt`, `readAt`, `assessedAt`, `decidedAt`,
or `sourceEvaluatedAt`.

If that clock is missing or not timezone-aware, store the completed state
with `evaluationCompletedAt=null`. Evidence then uses `UNKNOWN`. `CURRENT`
is forbidden in either case until a real freshness policy exists.

## Revision and Concurrency

The leaf lock covers the read-modify-write.

Revision starts at 0 and increments by one only when a successful slot
changes. A failed evaluation does not increment it.

Each slot stores its own `evaluationCompletedAt`. A new success replaces
that slot only when its completion time is strictly newer. An equal or
older time does not replace the slot and does not increment revision.
The other slot is left unchanged.

Two completions that contend are serialized by the lock. The later
completion time wins. There is no merge of recommendations.

## Master, MM, and Shadow

Master and MM are separate slots. An MM assessment state is not a Master
posture. An MM risk direction is not `currentRecommendation`.

Shadow is `result.mode` for both. It is not a third agent and it is not
`supervisorState`.

`operationalEffect` remains `NONE`. `orderAction` remains `NONE`.
`grantsExecutionAuthority` remains false. A recommendation string is not
entry permission, live-order permission, or emergency-stop state.

## Owner Snapshot Mapping

`tradingai-owner-snapshot/v1` stays unchanged.

`held_runtime_domains` adds a `supervisor` fragment only from the leaf copy.
Existing publication then allowlists it, applies the JSON copy, and removes
secret-like keys and injection text. `publishedAt` remains the publication
clock and is not the producer time.

`producerObservedAt` comes from `evaluationCompletedAt` when it parses.
`lastEvaluation` uses that same value. No other clock is substituted.

## Runtime Evidence Mapping

The existing `supervisorRuntime` domain already returns `UNAVAILABLE` with
reason `NOT_PUBLISHED` when the fragment is missing.

When the fragment is present:

| Evidence field | Value |
| --- | --- |
| runtimeStatus | `UNKNOWN`, not `CURRENT` |
| runtimeFreshness | `UNKNOWN` |
| runtimeTimestamp | the completion time, or `UNKNOWN` when it is null |
| runtimeValues | allowlisted states and recommendation only |
| reason | `OWNER_PUBLISHED` |

The evidence document already has `authority=NONE` and
`tradingControl=FORBIDDEN`. This design does not add an order effect.

Advisor and authenticated Supervisor receive it only through the existing
shared operator context. No new reader and no new schema are added.

## Freshness

FRESHNESS_POLICY_MISSING.

`DEFAULT_FRESHNESS_POLICY` uses a provisional 30-second age. Its comment
says that age is not an authoritative producer threshold. This design does
not adopt it and does not create a new TTL. A completion timestamp is not
`CURRENT`.

## Security

The cache stores enums, mode, revision, completion time, and an event id.
It does not store the operator context, conversation transcript, prompts,
or provider request body.

Operator publication stays behind the existing operator session. Public view
does not gain this domain. An unauthenticated conversation response does not
gain an operator-evidence field. Writing the shadow result into process
memory does not attach account secrets.

The existing publication filter remains the injection and secret boundary.
`orderEffect` is not granted.

## Implementation Options

Option A is the recommendation above.

Option B has no runtime owner that already retains the result.

Option C would put supervisor state on BotManager. That file is the
publication owner, not the evaluation owner, and a write there is easier to
confuse with `get_status`.

Option D is the behavior of this commit. Implementation has not started.

## Recommended Design

Option A. Conversation completion writes a JSON-safe slot. Publication only
copies it. The live snapshot builder and adapter are not on that path.

## Minimum Implementation Plan

Not implemented here.

1. Owner: `SupervisorConversationService`.
2. Write point: the two return sites in `respond`, only after `COMPLETED`.
3. Read point: lazy copy in `held_runtime_domains`.
4. Contract: the holder table above. `supervisorState` stays absent.
5. Producer time: new completion clock. Never `capturedAt`.
6. Revision: increment only on a strictly newer successful slot.
7. Concurrency: leaf lock and compare-by-completion-time.
8. Owner mapping: existing supervisor allowlist only.
9. Evidence mapping: existing `supervisorRuntime`, status `UNKNOWN`.
10. Advisor and Supervisor: existing shared context path.
11. Authentication: existing operator session and public-view split.
12. Freshness: no new policy. Not `CURRENT`.
13. Tests: completed MM, completed Master, failed result does not replace
    success, older result does not replace newer, missing cache stays
    unavailable, `build`/`get_status`/`get_result` are absent from the read,
    recommendation does not create `liveOrderAllowed`, injection text is
    dropped, unauthenticated response does not expose operator evidence.
14. Shared path: do not edit `snapshot_builder.py` or
    `runtime_snapshot_adapter.py`.
15. Rollback: stop calling the writer and return no fragment. The domain
    returns to `UNAVAILABLE` without a schema change.

Future files:

- `backend/supervisor/held_evaluation_cache.py`
- `backend/supervisor/conversation_service.py`
- `backend/bot_manager/owner_snapshot.py`
- a new isolated test module
- this design's status note, if implementation updates docs

## Acceptance Matrix

| Item | Result |
| --- | --- |
| A01 Evaluation entry identified | PASS |
| A02 Evaluation completion identified | PASS |
| A03 Safe owner identified | PASS |
| A04 Safe write point identified | PASS |
| A05 Side-effect-free read path | PASS |
| A06 Producer timestamp source | PASS |
| A07 Master/MM separation | PASS |
| A08 Shadow mode correctness | PASS |
| A09 Authority boundary | PASS |
| A10 Cache contract | PASS |
| A11 Revision policy | PASS |
| A12 Concurrency policy | PASS |
| A13 Owner snapshot mapping | PARTIAL |
| A14 Runtime evidence mapping | PASS |
| A15 Authentication boundary | PASS |
| A16 Public isolation | PASS |
| A17 Secret exclusion | PASS |
| A18 Prompt safety | PASS |
| A19 JSON safety | PASS |
| A20 Freshness policy status | PARTIAL |
| A21 Shared path reconciliation | PASS |
| A22 Minimum implementation plan | PASS |
| A23 Regression test plan | PASS |
| A24 No runtime mutation | PASS |

A13 is partial because `supervisorState` has no source and is intentionally
omitted. A20 is partial because the policy status is
`FRESHNESS_POLICY_MISSING`; that is not a usable policy. A23 names future
tests. They were not executed.

## Remaining Gaps

- The cache is not implemented.
- `supervisorState` cannot be mapped.
- Completion time is not `CURRENT`.
- The stored result is conversation shadow output, not a live runtime loop.
- Main snapshot files remain a shared-path diff and stay out of scope.
