# BB-MM-F4 Advisor and Supervisor MM Runtime Acceptance

TASK_ID: TRADINGAI-WORK-BB-MM-F4-ADVISOR-SUPERVISOR-RUNTIME-ACCEPTANCE-1

VERDICT: BB_MM_F4_ADVISOR_SUPERVISOR_RUNTIME_ACCEPTANCE_PASS

Acceptance only. No application code was changed. CURRENT remains
disabled. No TTL was added. Reason codes were not turned into STALE.

CANONICAL_HEAD_START: `294f7d35c952d47921ffe09c442a3d3f88bad7f6`

CANONICAL_HEAD_END: `294f7d35c952d47921ffe09c442a3d3f88bad7f6`
at the time this document was written. This acceptance does not commit
on canonical main. The external copy repeats the value read after the
commit.

ORIGIN_MAIN: `f344864344b0b99a598f674b3e2e4a367bc9fb25`

WORKTREE: `/home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-advisor-supervisor-acceptance`

BRANCH: `test/ai-mm-advisor-supervisor-acceptance`

BASE_COMMIT / HEAD_BEFORE: `fe02790c31cdd74f96117ce6e7fb2e2e31f657ea`

HEAD_AFTER: the commit whose message is
`work-bb: accept advisor supervisor mm runtime evidence`.
The hash is recorded only in the external audit copy.

CHANGED_FILES: `docs/ai/BB_MM_F4_ADVISOR_SUPERVISOR_RUNTIME_ACCEPTANCE.md`

## Canonical reconciliation

Merge-base with `origin/main` and local `main`:
`39273a115637edaba42ea49bde732f1ae6436399`.

Local `main` is ahead of `origin/main` by the work-aa OIDC commit.
That commit does not touch `backend/context`, `backend/bot_manager`,
`backend/money_management`, Advisor, or Supervisor.

Since the merge-base, both `origin/main` and local `main` differ on:

- `backend/money_management/loss_execution_integration.py`
- `backend/money_management/loss_http_api.py`
- `backend/supervisor/runtime_snapshot_adapter.py`
- `backend/supervisor/snapshot_builder.py`

This branch does not edit those four files. Classification: MAIN_ONLY.
The MM runtime evidence files are BB_ONLY relative to that merge-base.
No focus function is edited on both sides. Classification of the
canonical context path: not CONFLICTING and not
SHARED_PATH_REVIEW_REQUIRED. Main was not merged.

`snapshot_builder.py` is a separate supervisor snapshot. It is not the
writer of `runtimeEvidence`. The conversation route does not use it to
rejudge the MM fragment.

## Canonical context

Schema constant: `tradingai-context/v1`.

`load_shared_operator_context` keeps four evidence objects apart:

- `sourceEvidence` truthKind `SOURCE_TRUTH`
- `runtimeEvidence` truthKind `RUNTIME_TRUTH`
- `projectEvidence` truthKind `PROJECT_TRUTH`
- `decisionEvidence` truthKind `DECISION_TRUTH`

On the checked PAPER and LIVE documents, project availability was
`NO_MATCHING_PROJECT` while the MM runtime status stayed UNKNOWN or
UNAVAILABLE. `HASH_MISMATCH` is produced only inside project evidence.
It is not copied onto the MM runtime status.

Advisor `browser_gateway._attach_canonical_context` and the supervisor
conversation route both call `load_shared_operator_context`. Neither
recomputes MM freshness after that call.

## Producer, owner, runtime evidence

The F1 completion gate, the F2 revision bump, and the F3 reason,
lifecycle, and LIVE source fields are unchanged. After invalidation the
completion names and LIVE source fields are absent together. A reason is
present only when the completion is hidden. A failed or incomplete
observe does not republish the old completion or the old LIVE source.
A missing fragment is UNAVAILABLE. A present fragment is UNKNOWN.
`freshnessPolicy`, a fresh `producerObservedAt`, and `publishedAt` do
not make it CURRENT. A reason does not make it STALE. Other domain
labels STALE and HISTORICAL stay on those domains.

The same owner document produces the same `runtimeEvidence` for the
Advisor question and the Supervisor question. The reader does not call
an exchange or refresh an account.

## Advisor and Supervisor

Compared on one owner document at a time:

- the whole `runtimeEvidence` object is equal
- MM `runtimeStatus` is equal and is UNKNOWN or UNAVAILABLE
- completion names, reason, lifecycle, and LIVE source fields match
- authority is NONE
- trading control is FORBIDDEN

PAPER valid observation publishes the completion and stays UNKNOWN.
Price, auto entry, and auto close share `PAPER_INPUT_MUTATION` and hide
the completion. Manual entry keeps `PAPER_MANUAL_ENTRY` and hides the
completion. A rejected entry does not invalidate. Manual close and
capital reset reach a new completion and clear the reason. Emergency
flatten stays UNKNOWN. Stop publishes `PAPER_RUNTIME_STOP` and
`STOPPED`. A new session hides the old completion.

LIVE valid observation publishes the cache source and generation and
stays UNKNOWN. Balance mutation is `LIVE_ACCOUNT_CACHE_MUTATION` and
hides the source. Source, authentication, and stale use their own
reasons. A partial cache observe hides the old source. An engine
position change does not invalidate. A new LIVE session hides the old
source. `refresh_calls` stayed 0 and the engine order list stayed empty.

Advisor still has a separate bot-summary clock,
`RUNTIME_FRESHNESS_SECONDS = 10`, based on `last_bot_update`. That
object is not `runtimeEvidence.domains.moneyManagement`. This acceptance
did not change it, and it does not grant trading authority. Supervisor
`snapshot_builder.py` remains the separate MAIN_ONLY snapshot and is
not this MM status.

## Security and authority

The operator route returns 401 without a session. An isolated fixture
app receives the runtime evidence only on the operator attachment.
The public view of the same documents does not contain runtime evidence,
MM numbers, the completion timestamp, the reason, the lifecycle, or the
LIVE source. No production credential was used.

Authority stays NONE and trading control stays FORBIDDEN on both
readers. These checks do not call ExecutionEngine order methods, manual
trading submission, emergency exchange flatten, or a LIVE authority
change.

## Tests

```text
python3 -m pytest \
  tests/test_mm_freshness_evidence_gap.py \
  tests/test_mm_observation_invalidation.py \
  tests/test_mm_observation_completion_evidence.py \
  tests/test_ai_context_runtime_producer.py \
  tests/test_ai_context_runtime_evidence.py \
  tests/test_ai_context_runtime_coverage.py \
  tests/test_ai_context_runtime_reacceptance.py \
  tests/test_ai_context_owner_wiring.py \
  tests/test_ai_context_owner_cache.py \
  tests/test_supervisor_runtime_acceptance.py \
  tests/test_supervisor_held_evaluation_cache.py \
  tests/test_money_management_loss_authoritative_runtime_metrics.py \
  tests/test_ai_context_advisor_supervisor_integration.py \
  tests/test_ai_advisor_mm_authority_preservation.py
```

Result: 199 passed, 2 subtests passed.

Known-failure command, run here and on baseline
`ca52a622a50948ec157d8e35e3d20d4428a6f635`:

```text
python3 -m pytest \
  tests/test_paper_trade_pipeline.py \
  tests/test_mm_stopped_paper_recovery_metrics.py \
  tests/test_mm_baseline_session_transition.py
```

Both commits: 9 failed, 15 passed, 5 subtests passed. The failure ids
and signatures match.

- F01 pipeline line 111: `assert False is True`
- F02 pipeline line 185: `TypeError: NoneType is not subscriptable`
- F03 pipeline line 206: same TypeError
- F04 stopped paper: `False is not true`
- F05 stopped paper: `INCONSISTENT != STALE`
- F06 baseline line 211: `'error' == 'started'`
- F07 baseline line 271: `'error' == 'started'`
- F08 baseline line 621: `RISK_PERCENT_PAYLOAD_MISMATCH_CANONICAL`
- F09 baseline line 722: same reason

Class: PRE_EXISTING_FAILURE. Not fixed. The exchange-live status file
was not run. No related test failed newly.

A read-only comparison on this worktree built both contexts for the
PAPER and LIVE cases listed above. The runtime evidence objects matched
in every case.

## Test matrix

| ID | Result |
| --- | --- |
| T01 Canonical schema | PASS `tradingai-context/v1` |
| T02 Source truth separation | PASS |
| T03 Runtime truth separation | PASS |
| T04 Project truth separation | PASS project reason is not the MM status |
| T05 Decision truth separation | PASS |
| T06 MM owner fragment | PASS |
| T07 Completion evidence | PASS F1 gate |
| T08 Revision consistency | PASS |
| T09 Invalidation reason | PASS |
| T10 Producer lifecycle | PASS |
| T11 LIVE source evidence | PASS |
| T12 Runtime evidence projection | PASS same object for both readers |
| T13 MM UNKNOWN | PASS |
| T14 MM UNAVAILABLE | PASS |
| T15 No false CURRENT | PASS |
| T16 No false STALE | PASS |
| T17 Advisor reader | PASS shared loader |
| T18 Supervisor reader | PASS shared loader |
| T19 Same context | PASS |
| T20 Same freshness | PASS |
| T21 PAPER valid observation | PASS UNKNOWN with completion |
| T22 PAPER mutation | PASS `PAPER_INPUT_MUTATION` |
| T23 PAPER manual entry | PASS completion hidden |
| T24 PAPER manual close | PASS new completion, reason cleared |
| T25 PAPER emergency flatten | PASS UNKNOWN |
| T26 PAPER stop | PASS `PAPER_RUNTIME_STOP`, STOPPED |
| T27 LIVE valid observation | PASS source and generation published |
| T28 LIVE cache mutation | PASS source hidden |
| T29 LIVE source change | PASS |
| T30 LIVE authentication change | PASS |
| T31 LIVE cache stale | PASS |
| T32 LIVE engine position only | PASS no invalidation |
| T33 Operator 401 | PASS |
| T34 Operator authorized context | PASS fixture attachment |
| T35 PUBLIC isolation | PASS |
| T36 Advisor authority NONE | PASS |
| T37 Supervisor authority NONE | PASS |
| T38 Trading control FORBIDDEN | PASS |
| T39 No account sync | PASS |
| T40 No exchange API | PASS |
| T41 No real orders | PASS |
| T42 No trading logic change | PASS document only |
| T43 No MM calculation change | PASS |
| T44 No new regression | PASS same nine signatures |
| T45 Canonical reconciliation | PASS |

## Acceptance matrix

| ID | Result |
| --- | --- |
| A01 Canonical schema | PASS |
| A02 Truth separation | PASS |
| A03 Producer evidence | PASS |
| A04 Owner snapshot | PASS |
| A05 Runtime evidence | PASS |
| A06 UNKNOWN / UNAVAILABLE | PASS |
| A07 No false CURRENT | PASS |
| A08 No false STALE | PASS |
| A09 Advisor reader | PASS |
| A10 Supervisor reader | PASS |
| A11 Advisor / Supervisor consistency | PASS |
| A12 PAPER evidence | PASS |
| A13 LIVE evidence | PASS |
| A14 Revision / invalidation | PASS |
| A15 Producer lifecycle | PASS |
| A16 LIVE source evidence | PASS |
| A17 Operator authentication | PASS |
| A18 PUBLIC isolation | PASS |
| A19 Authority NONE | PASS |
| A20 Trading control FORBIDDEN | PASS |
| A21 No account sync | PASS |
| A22 No exchange API | PASS |
| A23 No real orders | PASS |
| A24 No trading logic change | PASS |
| A25 No MM calculation change | PASS |
| A26 No new regression | PASS |
| A27 Canonical reconciliation | PASS |

An explicit `freshness=STALE` label on any domain, including money
management, still returns STALE. The owner path does not set that
label. A reason does not.

## Remaining gaps

1. CURRENT stays disabled. There is no MM heartbeat and no accepted MM
   age bound.
2. The Advisor bot summary can still be FRESH or STALE from
   `last_bot_update` and a 10 second window. That is not the MM
   `runtimeStatus`.
3. The supervisor snapshot builder remains a separate MAIN_ONLY
   snapshot with its own provisional age. The conversation context does
   not use it for this MM status.
4. LIVE engine position and the account cache remain different inputs.
5. The exchange-live status file was not run.

BLOCK_REASON: none.

DEPENDENCY: F3 acceptance
`fe02790c31cdd74f96117ce6e7fb2e2e31f657ea`.

RESUME_CONDITION: canonical integration readiness can be reviewed.
CURRENT and a TTL stay out of that review unless a separate design
adds a heartbeat and an accepted age bound.

NEXT_RECOMMENDED_TASK: `BB_MM_FINAL_CANONICAL_INTEGRATION_READINESS`

This acceptance does not start that work.
