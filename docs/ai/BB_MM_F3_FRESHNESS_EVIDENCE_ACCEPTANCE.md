# BB-MM-F3.2 Money Management Freshness Evidence Acceptance

TASK_ID: TRADINGAI-WORK-BB-MM-F3-FRESHNESS-EVIDENCE-ACCEPTANCE-1

VERDICT: BB_MM_F3_FRESHNESS_EVIDENCE_ACCEPTANCE_PASS

Acceptance only. No application code was changed. CURRENT was not
enabled. No TTL was added. Reason codes were not turned into STALE.

CANONICAL_HEAD_START: `294f7d35c952d47921ffe09c442a3d3f88bad7f6`

CANONICAL_HEAD_END: `294f7d35c952d47921ffe09c442a3d3f88bad7f6`
at commit time of this document. This acceptance does not commit on
canonical main. The external copy repeats the value read after the
commit.

ORIGIN_MAIN: `f344864344b0b99a598f674b3e2e4a367bc9fb25`

WORKTREE: `/home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-freshness-evidence-acceptance`

BRANCH: `test/ai-mm-freshness-evidence-acceptance`

BASE_COMMIT / HEAD_BEFORE: `df4544adb0ed565ce4a33d4374627e543e494066`

HEAD_AFTER: the commit whose message is
`work-bb: accept mm freshness evidence`.
The hash is recorded only in the external audit copy.

CHANGED_FILES: `docs/ai/BB_MM_F3_FRESHNESS_EVIDENCE_ACCEPTANCE.md`

## Canonical reconciliation

Merge-base of this branch with `origin/main` and with local `main`:
`39273a115637edaba42ea49bde732f1ae6436399`.

`origin/main` is `f344864344b0b99a598f674b3e2e4a367bc9fb25`.
Local `main` is `294f7d35c952d47921ffe09c442a3d3f88bad7f6`,
`feat(work-aa): prepare isolated observation OIDC backend release`.
That difference is work-aa only. Its files are observation OIDC, nginx
fixture, and work-aa tools. They do not include:

- `backend/context/runtime_evidence.py`
- `backend/money_management/loss_authoritative_runtime_metrics.py`
- `backend/bot_manager/bot_manager.py`
- `backend/bot_manager/owner_snapshot.py`
- `tests/test_ai_context_runtime_producer.py`
- `tests/test_mm_freshness_evidence_gap.py`

Since the merge-base, both `origin/main` and local `main` change
`backend/money_management/loss_execution_integration.py` and
`loss_http_api.py`. This acceptance does not edit those files.
No focus function is changed on both sides. Main was not merged.

## CURRENT guard

`_judge` returns UNKNOWN for money management after an explicit
freshness label and before any age policy. The age helper that could
return CURRENT is not in the file.

Checked on this worktree:

- Missing fragment: UNAVAILABLE.
- Present fragment, including a valid completion and a matching
  revision: UNKNOWN.
- Injected `freshnessPolicy`, a current `producerObservedAt`, and a
  current `publishedAt`: UNKNOWN. `as_of` is published as
  `producerObservedAt`. The judge does not read a second age clock.
- A fragment that also carries completion names and a reason: UNKNOWN,
  not CURRENT, not STALE.
- Execution domain `freshness=STALE`: STALE.
- Execution domain `freshness=HISTORICAL`: HISTORICAL.
- Market selection with a money-management policy object: UNKNOWN, not
  CURRENT.

## Invalidation reason

On `df4544a`, a real invalidation records one allowed reason, advances
revision once, and leaves `as_of`, the completion timestamp, equity,
peak equity, and drawdown unchanged. The second call does not advance
revision and does not replace the reason. A successful note clears the
reason. A failed observe keeps the reason on the metrics snapshot.
A reason does not select STALE. A fragment with no reason stays UNKNOWN.

## PAPER

Price update, auto entry, and auto close share `PAPER_INPUT_MUTATION`.
Manual entry is `PAPER_MANUAL_ENTRY` and leaves the old completion
unpublished. Manual close, emergency flatten, and capital reset record
their own reasons before the existing observe, and the successful note
clears the reason. Stop records `PAPER_RUNTIME_STOP` and publishes
lifecycle `STOPPED`. Rejected manual entry and rejected manual close do
not invalidate. None of these states are CURRENT.

## LIVE cache

Balance and positions use `LIVE_ACCOUNT_CACHE_MUTATION`. Source,
authenticated, and stale use their own codes. Generation-only, an
identical copy, and a loading copy that does not change the MM
projection are no-ops. An engine position change does not invalidate.
A LIVE manual entry does not invalidate. No refresh call and no order
call were made by these tests.

## Producer lifecycle and LIVE source

`producerLifecycle` is the existing `lifecycle_state`. STOPPED stays
STOPPED. RUNNING is not turned into ACTIVE and is not CURRENT.
`producerLifecycleChangedAt` is the existing transition clock.

A LIVE completion copies source, authenticated, stale, `lastSync`, and
`generation` only when those values are already on the cache. After
invalidation, and after a later observe that does not complete, the
owner fragment does not contain `liveBalanceSource` or the completion
clock. A later complete observe publishes the new generation. A new
session does not leave a CURRENT completion on the owner fragment.

## Owner, runtime, advisor, supervisor, security

The owner file is `backend/bot_manager/owner_snapshot.py`.
`backend/context/owner_snapshot.py` does not exist. Completion names
use the F1 gate. The reason is copied only when that gate does not copy
the completion. An invalid observation still drops the fragment, and
the reader then sees UNAVAILABLE. Numbers are not rewritten.

Runtime evidence stays UNKNOWN or UNAVAILABLE for MM. Advisor and
Supervisor read one operator context. The shared status is UNKNOWN,
authority NONE, trading control FORBIDDEN. No second freshness judge
was added.

The operator route returns 401 without a session. The public view from
the fixture document does not contain runtime evidence, the reason, the
lifecycle, the LIVE source fields, or the completion timestamp. No
production credential was used.

## Tests

Command, from the acceptance worktree:

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
  tests/test_money_management_loss_authoritative_runtime_metrics.py
```

Result: 173 passed, 2 subtests passed.

Known-failure command, run on this commit and on baseline
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

Class: PRE_EXISTING_FAILURE. Not fixed.

`tests/test_exchange_live_status.py` was not run. No exchange test in
the related set failed.

One read-only check outside pytest confirmed three paths on this
worktree: an execution fragment marked HISTORICAL stays HISTORICAL; a
LIVE observe that does not complete leaves the old source unpublished; a
following complete observe publishes generation 2 and stays UNKNOWN; a
new session fragment is not CURRENT.

## Test matrix

| ID | Result | Evidence |
| --- | --- | --- |
| T01 Fragment missing | PASS | gap T01 |
| T02 Fragment present | PASS | gap T02, UNKNOWN |
| T03 Policy injection | PASS | gap T03 and producer policy test |
| T04 Recent as_of | PASS | published as `producerObservedAt`; judge has no second clock |
| T05 Recent producerObservedAt | PASS | gap T03 |
| T06 Recent publishedAt | PASS | gap T03 and the fixed `publishedAt` fixture |
| T07 Valid completion | PASS | gap T02, status UNKNOWN |
| T08 Revision match | PASS | same completion, status UNKNOWN |
| T09 Other domain | PASS | STALE and HISTORICAL labels unchanged |
| T10 Invalidation reason | PASS | gap T07 |
| T11 Revision increment | PASS | gap T07 and F2 T01 |
| T12 Idempotence | PASS | gap T08 and F2 T02 |
| T13 Reason kept on second call | PASS | gap T08 |
| T14 Note clears reason | PASS | gap T10 |
| T15 Failed observe keeps reason | PASS | gap T11, on the metrics snapshot |
| T16 PAPER price | PASS | `PAPER_INPUT_MUTATION` |
| T17 PAPER auto entry | PASS | same code |
| T18 PAPER auto close | PASS | same code |
| T19 PAPER manual entry | PASS | reason remains, completion hidden, not CURRENT |
| T20 PAPER manual close | PASS | reason before the note, then cleared |
| T21 PAPER emergency | PASS | `PAPER_EMERGENCY_FLATTEN` |
| T22 PAPER capital reset | PASS | `PAPER_CAPITAL_RESET` |
| T23 PAPER stop | PASS | `PAPER_RUNTIME_STOP` |
| T24 PAPER rejected action | PASS | F2 rejected entry and rejected close |
| T25 LIVE balance | PASS | `LIVE_ACCOUNT_CACHE_MUTATION` |
| T26 LIVE positions | PASS | F2 position-cache test, same code |
| T27 LIVE source | PASS | `LIVE_SOURCE_CHANGED` |
| T28 LIVE authentication | PASS | `LIVE_AUTHENTICATION_CHANGED` |
| T29 LIVE stale | PASS | `LIVE_CACHE_STALE` |
| T30 LIVE no-op | PASS | generation, identical copy, loading copy |
| T31 Engine position only | PASS | F2 T27, no invalidation |
| T32 Producer lifecycle | PASS | RUNNING, not CURRENT |
| T33 Producer stop | PASS | STOPPED, completion hidden, UNKNOWN |
| T34 Session restart | PASS | old reason cleared; fragment not CURRENT |
| T35 LIVE source projection | PASS | cache fields only |
| T36 LIVE source after invalidation | PASS | hidden with the completion gate |
| T37 Owner snapshot | PASS | F1 gate and reason only when completion is hidden |
| T38 Runtime evidence | PASS | UNKNOWN or UNAVAILABLE |
| T39 Advisor | PASS | shared context |
| T40 Supervisor | PASS | same status |
| T41 Operator authentication | PASS | 401 |
| T42 PUBLIC isolation | PASS | fixture public view |
| T43 No account sync | PASS | refresh count stays 0 |
| T44 No exchange API | PASS | no exchange call in these tests |
| T45 No real orders | PASS | engine call list empty |
| T46 No MM calculation change | PASS | equity, peak, drawdown, as_of unchanged |
| T47 No new regression | PASS | same nine signatures on both commits |
| T48 Canonical reconciliation | PASS | work-aa does not touch the focus files |

## Acceptance matrix

| ID | Result |
| --- | --- |
| A01 CURRENT guard | PASS |
| A02 UNKNOWN | PASS |
| A03 UNAVAILABLE | PASS |
| A04 Other domain | PASS |
| A05 Invalidation reason | PASS |
| A06 Revision consistency | PASS |
| A07 Idempotence | PASS |
| A08 Successful note | PASS |
| A09 Failed observe | PASS |
| A10 PAPER mutation | PASS |
| A11 PAPER manual entry | PASS |
| A12 PAPER stop | PASS |
| A13 LIVE cache mutation | PASS |
| A14 LIVE no-op | PASS |
| A15 Producer lifecycle | PASS |
| A16 Session boundary | PASS |
| A17 LIVE source | PASS |
| A18 Owner snapshot | PASS |
| A19 Runtime evidence | PASS |
| A20 Advisor | PASS |
| A21 Supervisor | PASS |
| A22 Operator authentication | PASS |
| A23 PUBLIC isolation | PASS |
| A24 No account sync | PASS |
| A25 No exchange API | PASS |
| A26 No real orders | PASS |
| A27 No trading logic change | PASS |
| A28 No MM calculation change | PASS |
| A29 No false CURRENT | PASS |
| A30 No false STALE | PASS |
| A31 No new regression | PASS |
| A32 Canonical reconciliation | PASS |

A30 means a reason, a policy, or a fresh `producerObservedAt` does not
create STALE. An explicit `freshness=STALE` label still returns STALE
for every domain, including money management. The owner path does not
set that label. That label path was not added by F3.1.

## Remaining gaps

1. CURRENT stays disabled. There is still no producer heartbeat and no
   accepted MM age bound.
2. Reason codes do not select STALE.
3. A failed observe that clears `observation_valid` removes the owner
   fragment, so the retained reason is not on the public operator
   fragment until a valid fragment exists.
4. LIVE engine position and the account cache remain different inputs.
5. The exchange-live status file was not run.

BLOCK_REASON: none.

DEPENDENCY: evidence implementation
`df4544adb0ed565ce4a33d4374627e543e494066`.

RESUME_CONDITION: a later task may accept Advisor and Supervisor use of
this evidence. It must not enable CURRENT or add a TTL.

NEXT_RECOMMENDED_TASK: `BB_MM_F4_ADVISOR_SUPERVISOR_RUNTIME_ACCEPTANCE`

This acceptance does not start that work. Producer heartbeat and an MM
age bound remain separate design work.
