# BB-MM-F3 Money Management Runtime Freshness Policy Design

TASK_ID: TRADINGAI-WORK-BB-MM-F3-FRESHNESS-POLICY-DESIGN-1

VERDICT: BB_MM_F3_FRESHNESS_POLICY_DESIGN_PASS

This document designs the freshness judgment. It does not implement it.
`CURRENT` must not be emitted from the evidence that exists at base
`06fb04c work-bb: accept mm observation invalidation`.

The requested branch name `design/ai-mm-freshness-policy` is already
checked out, clean, at `372d181` in
`/home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-freshness-design`.
That commit is an older F1 freshness design
(`docs/ai/BB_MM_F1_FRESHNESS_POLICY_DESIGN.md`). It was not reset and was
not used as this baseline. This design lives on
`design/ai-mm-f3-freshness-policy` in
`/home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-freshness-policy-design`,
created from the F2 acceptance commit.

HEAD_BEFORE: `06fb04c work-bb: accept mm observation invalidation`

HEAD_AFTER: the commit whose message is
`work-bb: design mm runtime freshness policy`.
The hash is recorded only in the external audit copy.

## Canonical reconciliation

Canonical HEAD and `origin/main`: `f344864344b0b99a598f674b3e2e4a367bc9fb25`.

Merge-base of this branch and `origin/main`:
`39273a115637edaba42ea49bde732f1ae6436399`.

MAIN_ONLY since that merge-base. This branch did not edit them:

- `Bot/engine/execution_engine.py`
- `backend/api/money_management.py`
- `backend/money_management/loss_execution_integration.py`
- `backend/money_management/loss_http_api.py`
- `backend/runtime/cycle_diagnostics.py`
- `backend/supervisor/runtime_snapshot_adapter.py`
- `backend/supervisor/snapshot_builder.py`
- frontend diagnostics and `dashboard.css`
- `tests/test_contract_quantity_projection_repair.py`
- `tests/test_manual_cycle_diagnostics.py`
- `tests/test_money_management_execution_entry_preview.py`
- `tests/test_paper_trade_pipeline.py`

BB_ONLY for this policy. These exist on this branch and are the contract:

- `backend/money_management/loss_authoritative_runtime_metrics.py`
- `backend/bot_manager/bot_manager.py`
- `backend/bot_manager/owner_snapshot.py`
- `backend/context/runtime_evidence.py`
- `backend/context/shared_answer_context.py`
- `backend/context/context_views.py`

Advisor and Supervisor both read `load_shared_operator_context`. Their
modules are not a second freshness writer. No focus path is changed on
both sides. Classification of the focus set: MAIN_ONLY, BB_ONLY, or
already the same tree. No CONFLICTING path. No SHARED_PATH_REVIEW_REQUIRED
path inside the freshness projection. Main was not merged.

`backend/supervisor/runtime_snapshot_adapter.py` on this branch still
says no shared producer threshold exists and keeps a provisional
30-second supervisor observation age. That comment is on the BB side of
the file as it exists at this base. Main's copy of that file differs
and was not read as authority. The provisional 30 seconds is not an MM
completion TTL.

## Preserved F1 and F2 contract

`note_mm_observation_completed` writes `mmObservationCompletedAt`,
input completeness, input scope, and evidence revision only when the
stored metrics revision equals the revision returned by the observe,
`observation_valid` is true, completeness is `COMPLETE`, and scope is
`PAPER_ENGINE_ACCOUNT` or `LIVE_ACCOUNT_CACHE`. It does not change
equity, drawdown, peak, `as_of`, or revision.

Owner publication copies those four names only when the timestamp is
present, evidence revision equals metrics revision, observation is
valid, completeness is `COMPLETE`, and scope is one of those two names.
Otherwise the four names are absent. `producerObservedAt` remains
`as_of`. `publishedAt` is the owner document clock. The fragment
freshness label stays `UNKNOWN`. No `freshnessPolicy` is attached.

`invalidate_mm_observation_evidence` increments `_revision` by one only
when the timestamp exists, the evidence revision equals `_revision`,
observation is valid, completeness is `COMPLETE`, and scope is one of
the two names. It does not move the timestamp, `as_of`, equity, peak,
scope, or completeness. A second call is a no-op. There is no
invalidation reason, flag, or invalidation clock.

Runtime evidence today: a missing money-management fragment is
`UNAVAILABLE`. A present fragment without a money-management
`freshnessPolicy` is `UNKNOWN`. Matching revisions do not mean
`CURRENT`.

`runtime_evidence._judge` can return `CURRENT` only when the fragment
carries `freshnessPolicy` with source `moneyManagement` and
`maximumAgeSeconds`, and it ages `producerObservedAt`, not
`mmObservationCompletedAt`. The MM owner fragment does not carry that
policy. A later implementation must not add that policy in order to
obtain `CURRENT`. Aging `as_of` is not observation freshness.

## D01 FRESHNESS_STATUS_MODEL

| Status | Meaning |
| --- | --- |
| CURRENT | Every required proof is present: a complete observation of the current revision, a known live input identity, a known session generation, a known producer heartbeat, and an accepted age bound. None of the STALE proofs are present. |
| STALE | A previously valid observation is withdrawn for a reason the fragment itself names. Revision mismatch without that reason is not STALE. |
| UNKNOWN | The fragment exists, and at least one proof required to choose CURRENT or STALE is missing or ambiguous. |
| UNAVAILABLE | There is no money-management runtime fragment to judge. |

`HISTORICAL` remains the existing runtime-evidence label for a fragment
that already says `freshness=HISTORICAL`. The MM producer does not emit
that label. This policy does not add it.

The reader must not collapse STALE and UNKNOWN. UNKNOWN is the fail-safe
when the expiry reason cannot be named.

## D02 EVIDENCE_INVENTORY

PUBLIC_VISIBILITY is NO for every row. Operator runtime evidence is not
copied into the public context view. Reliability is what a reader of the
published fragment can rely on today.

| ID | Source | Producer | Semantics | CURRENT | STALE | UNKNOWN reason | Reliability |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E01 | `mmObservationCompletedAt` | `note_mm_observation_completed` | Clock of a successful completion note. Not `as_of`. Unpublished when evidence revision differs. | Required, not sufficient | Absence is not a STALE proof | Clock missing while the fragment exists | High for "a note happened". None for "still current". |
| E02 | `inputCompleteness` | same note | `COMPLETE` at note time. Omitted with E01. | Must be `COMPLETE` when published | Absence is not STALE | Missing or any other value | High at note time only |
| E03 | `inputScope` | same note | `PAPER_ENGINE_ACCOUNT` or `LIVE_ACCOUNT_CACHE` at note time. Not `config.TRADE_MODE`. | Must be one of the two names | Absence is not STALE | Any other value, or config mode compared with scope | High as historical input identity |
| E04 | `observation_valid` | metrics snapshot | Owner publishes the fragment only when this is true. The flag itself is not a fragment field. | Fragment presence is the published proxy | Not a STALE signal | Fragment present does not repeat the flag | Medium. The flag is not re-published. |
| E05 | `evidenceRevision` | note | Revision at the successful note. Omitted when it differs from E06. | Must equal E06 | Inequality is not STALE by itself | Omitted, non-integer, or unequal | High for "no detected invalidation since the note" |
| E06 | `revision` | metrics `_revision` | Current metrics revision. Bumped by observe, session start, restore, peak recovery, stopped observe, and F2 invalidation. | Must equal E05 | A bump's cause is not on the fragment | Cause of a bump | High as a counter. Low as a reason. |
| E07 | `producerObservedAt` | metrics `as_of` | Last metrics mutation clock: observe, session, restore, or peak. Not the completion clock. | Must not be used as the completion clock | Must not be aged into STALE | Using it as completion | High as `as_of`. Wrong for freshness. |
| E08 | `publishedAt` | owner document | Time the owner stored the document. | Not input freshness | Not expiry | Using it as input age | High as publication time only |
| E09 | read clock | none on the MM fragment | `runtimeTimestamp` is parsed E07. There is no separate `readAt`. | Not a producer update | Not expiry | Treating the reader clock as the producer | Absent |
| E10 | account snapshot source | LIVE cache fields consumed inside the LIVE note gate | `balanceSource` and `positionSource` must both be `KUCOIN_FUTURES_READ_ONLY` at the LIVE note. Those source strings are not copied onto the MM fragment. | Required at note time. Not re-checkable later. | Not visible as an MM STALE reason | Source no longer on the fragment | Note-time only |
| E11 | `authenticated` | LIVE cache, at the note | Note requires true. The flag lives on the real-account domain, not the MM fragment. | Note-time precondition | A later false is not an MM field | Joining domains across publication delay | Split across domains |
| E12 | `stale` | LIVE cache | `_mark_real_account_stale_if_needed` sets it when `lastSync` is older than `account_stale_after` (90 seconds) and that path runs. F2 invalidates the MM completion when the cache projection changes. The MM fragment does not carry `stale`. | A published MM completion does not prove stale is still false | Real-account domain may already show STALE. That is not MM STALE. | MM reader cannot see the flag | Account-domain only |
| E13 | PAPER account store freshness | stopped PAPER maintenance | Stopped observe notes only when the store observation is FRESH and `observation_valid` is true. Running PAPER does not publish that store label on the MM fragment. | Not a running-PAPER CURRENT proof | Store STALE blocks a new note. It does not label the fragment STALE. | Label absent on the fragment | Indirect |
| E14 | runtime mode | `engine.mode` at observe | PAPER observe notes only for `engine.mode == paper`. LIVE observe notes only on the cache gate. Scope records which input was noted. | Published scope is necessary | Config `/set_mode` does not move revision and must not change status | Comparing scope with `config.TRADE_MODE` | Scope is historical |
| E15 | runtime session | `begin_runtime_session` | A new session increments revision and does not note, so the old completion is unpublished. The fragment has no session id. | Revision match means the note is at the current revision, after the last session bump | Session bump is not STALE | Why the revision moved | Revision encodes the boundary. The reason is hidden. |
| E16 | MM fragment presence | owner `_held_money_management` | Fragment exists only when observation is valid and source state is not `NOT_INITIALIZED`. | Necessary | Absence is UNAVAILABLE, not STALE | Present with no completion | High for presence |
| E17 | input mutation invalidation | F2 call sites | Detected PAPER input change, PAPER manual fill, confirmed close, capital reset, stop snapshot replacement, engine cleared, or LIVE cache projection change increments revision and unpublishes the completion. No reason code is stored. | Match means no such detected write since the note | The reader cannot see that the cause was a mutation | Cause may instead be session start, restore, or peak recovery | Producer-local. Invisible as a reason. |
| E18 | observation failure | note gate and observe exception | A failed observe does not move the completion clock. A later invalidation unpublishes the old clock. The old clock remains in producer memory and is not published while revisions differ. | Failure must not become CURRENT | Failure must not become STALE without a published reason | Clock omitted, numbers may be the previous observe | High that failure is not success |

## D03 EVIDENCE_PRIORITY

The judgment reads one published money-management fragment. It does not
invent values from another domain.

1. E16 fragment presence. Absent means UNAVAILABLE. Stop.
2. E01, E02, E03, E05 published together, and E05 equals E06. If any of
   these is missing or E05 differs from E06, the completion is not
   established. Continue at the STALE/UNKNOWN split below. Do not use
   E07, E08, or a reader clock to fill the hole.
3. Named expiry reason, which does not exist yet. If a future fragment
   field names one of the STALE reasons in D05, status is STALE. If the
   field names session start, restore, or peak recovery, status is
   UNKNOWN. If the field is absent, status is UNKNOWN.
4. Only when step 2 holds and step 3 names no expiry: the additional
   CURRENT proofs in D04. If any additional proof is absent, UNKNOWN.

E07 is lower than E01 and must not override it. E08 and the reader clock
are not freshness inputs. E11 and E12 on the real-account domain do not
override the MM status. E10 is not on the MM fragment after publication.

## D04 CURRENT_POLICY

CURRENT requires all of the following at once.

1. E16: the MM fragment exists.
2. E01: completion timestamp is published.
3. E04 proxy: the owner published the fragment, which it does only when
   observation was valid.
4. E02 is `COMPLETE`.
5. E05 equals E06.
6. E03 is `PAPER_ENGINE_ACCOUNT` or `LIVE_ACCOUNT_CACHE`, and that scope
   is the input the note recorded. `config.TRADE_MODE` is not consulted.
7. E17: no detected invalidation since the note. This is the same fact
   as item 5. It does not cover an undetected mutation.
8. The completion was produced by the F1 note on the authoritative
   metrics state. A foreign timestamp is not accepted. The producer
   identity is the existing owner path. No new source string is required
   on the fragment.
9. LIVE: at note time the cache was authenticated, not stale, and both
   sources were the read-only KuCoin futures source. Those facts are not
   on the published MM fragment, so a reader cannot re-check them.
   CURRENT therefore also requires a published LIVE input attestation
   that does not exist yet. See gaps.
10. E15: the completion belongs to the current metrics revision. A new
    session already unpublishes the previous completion. A session id on
    the fragment is not required for that narrow fact.

Items 1 through 8 and 10 can be true on today's fragment after a
successful note, and CURRENT is still forbidden. The following are not
proven:

- Elapsed time. No accepted MM maximum age exists. Do not invent one.
- Undetected input change between cycles. PAPER manual entry already
  shows the shape: the completion is hidden, but a later note is the
  only repair. Before that note, and for any mutation the detectors
  miss, revision match is not freshness.
- Producer liveness. No heartbeat is published. A matching completion
  can outlive a stopped loop when stop did not invalidate.
- LIVE cache progress. `account_stale_after` of 90 seconds and
  `account_refresh_interval` of 30 seconds belong to the account cache
  maintenance path. They are not an MM completion TTL. The stale flag
  is set only when that path runs. Silence is not a published fact.
- `engine.actual_position` is not an MM CURRENT input for LIVE.

Until the gap list is closed, the implementation of this policy must
not return CURRENT. A fragment that meets items 1 through 8 and 10
stays UNKNOWN.

The existing `_policy_status` path must not be armed. Do not set
`freshnessPolicy` on the MM fragment. Do not age `producerObservedAt`
into CURRENT or STALE.

## D05 STALE_POLICY

STALE is allowed only when the MM fragment itself carries a reason from
this set:

- detected MM input mutation after a completion (E17 with a published
  reason)
- published LIVE source staleness on the MM fragment, not merely on the
  real-account domain
- published authentication loss on the MM fragment
- published partial snapshot on the MM fragment
- published observation expiration against an age bound this design does
  not have

The reason field does not exist. Therefore this design defines STALE
and forbids emitting it.

These are not STALE:

- E05 unequal to E06, or E01 omitted, when the cause is not published.
  Session start, first restore, and peak recovery bump revision and
  unpublish the completion without being input expiry.
- Real-account `freshness=STALE` or `stale=true`. That judgment stays on
  the real-account domain.
- A provisional 30-second supervisor age.
- `account_stale_after` of 90 seconds applied to `as_of` or to the
  completion clock.
- PAPER manual entry lag. The cause is known in BotManager and is not
  known to the reader. The reader result is UNKNOWN.
- Producer stop with no published stop reason.
- Config mode differing from engine mode.

`runtime_evidence._judge` already returns STALE when `freshness` is
`STALE`. The MM owner fragment sets freshness to UNKNOWN. A later change
must not set the MM freshness label to STALE to simulate this policy.

## D06 UNKNOWN_POLICY

UNKNOWN when the fragment exists and CURRENT is not proven and STALE is
not proven. That includes:

- completion names absent
- observation validity not established
- source attestation absent
- session reason absent
- revision mismatch whose cause is absent
- producer health absent
- age bound absent or not accepted
- partial observation
- possible undetected mutation
- PAPER manual entry after invalidation and before the next note
- publication delay and reader delay, which are not input expiry
- E07, E08, or the reader clock present while E01 is absent

UNKNOWN is the status of every MM fragment this base can publish.

## D07 UNAVAILABLE_POLICY

UNAVAILABLE only when the money-management domain has no fragment.

That covers:

- metrics snapshot missing, observation not valid, or source state
  `NOT_INITIALIZED`, because `_held_money_management` then returns None
- owner document missing or the domain blocked
- reader not connected to an owner document
- projection failure that drops the domain

A fragment with numbers and no completion is not UNAVAILABLE. It is
UNKNOWN. Producer not initialized and a held fragment are different
states. The existing collector already uses UNAVAILABLE for a missing
domain and UNKNOWN for a published domain without a policy. This design
keeps that split.

## D08 PAPER_POLICY

PAPER inputs are the engine account snapshot, price, and unrealized
PnL, as F2 already detects them. This policy does not add a detector.

| Event | Fragment after the event | Status |
| --- | --- | --- |
| Auto entry, auto close, price or unrealized change that F2 detects | Completion unpublished. Numbers update only if the existing observe notes again. | UNKNOWN until a new completion is published. Then still UNKNOWN, because CURRENT's extra proofs are missing. Never CURRENT on the lag. |
| Manual entry | F2 invalidates. No observe is added. Numbers can remain the previous observe. Completion hidden. | UNKNOWN. Must not be CURRENT. Must not be STALE until a reason is published. |
| Manual close | Invalidate, then the existing finalize observe. | UNKNOWN if the new note does not publish. UNKNOWN even if it does, until CURRENT proofs exist. |
| Emergency flatten | Invalidate only when the paper signature changes, then the existing observe. | Same as manual close. |
| Capital reset | Invalidate when the paper projection changes, then the existing observe. | Same. |
| Stop | Invalidate when the captured snapshot identity changes, and again when the engine is cleared. No new observe. | UNKNOWN if a fragment remains. UNAVAILABLE if the fragment is gone. |
| Session restart | Session bump unpublishes the completion before the new engine observes. | UNKNOWN until a new completion exists, and UNKNOWN after that until CURRENT proofs exist. |
| Loop stopped without a successful invalidation | Old completion may still be published. | UNKNOWN. Missing producer-liveness proof forbids CURRENT. |
| Gap until the next cycle observe | Previous numbers can remain. | UNKNOWN. |

PAPER engine account validity, position, equity, and exposure are the
observe inputs. They become a completion only through the F1 note. Store
freshness for stopped PAPER remains the existing note gate. It is not a
CURRENT window for a running loop.

## D09 LIVE_POLICY

The LIVE MM input is `real_account_snapshot`, not `engine.actual_position`.
This design does not add account sync or an exchange call.

A LIVE completion requires the existing note gate: both sources
`KUCOIN_FUTURES_READ_ONLY`, at least one balance field, positions
present (an empty list is a flat read), authenticated true, stale false.
That gate is note-time. The published MM fragment does not repeat those
fields.

| Event | Status |
| --- | --- |
| Valid LIVE note | UNKNOWN. Not CURRENT. |
| Cache projection change, including balance, positions, source, authenticated, or stale | F2 unpublishes the completion. UNKNOWN. |
| Cache refresh not running | No new invalidation and no new note. A previous completion can remain. UNKNOWN, because silence is not a proof of freshness. |
| Partial snapshot | The note gate does not complete. If a previous completion existed, it stays until a projection change invalidates it. Status UNKNOWN. Partial is not CURRENT. |
| Exchange sync failure | No new exchange behavior is added. Failure to commit a snapshot does not by itself note. Status follows whatever fragment is already published: UNKNOWN. |
| Engine position differs from the cache | Not an MM mutation. Must not set MM CURRENT or MM STALE. |
| Authentication loss or stale true, when the assignment path runs | Completion unpublished. MM status UNKNOWN. The real-account domain may show its own STALE. |
| Producer stop | No LIVE cache observe is added. UNKNOWN unless the fragment disappears. |

Same-snapshot balance and position are a property of the cache object
passed into observe. The fragment does not carry a snapshot id. CURRENT
must not be inferred from the engine position.

## D10 TIME_POLICY

| Clock | Meaning | Allowed use |
| --- | --- | --- |
| `mmObservationCompletedAt` | Successful note | Necessary CURRENT input once the other proofs exist. Not an age TTL by itself. |
| `producerObservedAt` / `as_of` | Metrics revision content time | Identity of the metrics row. Not a completion substitute. |
| `publishedAt` | Owner store time | Publication latency only. Not input freshness. |
| reader time / `runtimeTimestamp` | Parsed `producerObservedAt` inside runtime evidence | Not a producer heartbeat and not `readAt`. |
| real-account `lastSync` | Account cache sync time | Already compared with 90 seconds inside account maintenance. Not an MM clock. |

No MM TTL is chosen. The candidates fail the evidence test:

- Observation age: no accepted maximum age is configured for the
  completion clock.
- Account cache age: 90 seconds and a 30 second refresh interval are
  account-cache maintenance. The stale bit is not on the MM fragment,
  and it is not updated by time alone unless that maintenance runs.
- Producer heartbeat age: no heartbeat timestamp is published. The
  runtime loop's 0.05 second sleep is a poll, not an observation period.
- Runtime session age: session start time is not an MM freshness bound.
- Supervisor provisional 30 seconds: the adapter states that no shared
  producer threshold exists. It must not be copied onto this policy.

If a later task proposes a number, it needs an owner for that number
outside this design. Guessing is rejected.

## D11 REVISION_POLICY

Evidence revision equal to metrics revision means: the completion note
ran at this revision, and no later detected F2 invalidation, session
bump, restore bump, peak bump, or observe bump has moved `_revision`.

It does not mean:

- no undetected mutation
- the producer loop is alive
- the LIVE cache is still being updated
- the completion is young
- the cause of a mismatch is input expiry

A mismatch therefore does not select STALE.

No new revision counter is added. `mmInputRevision` and
`mmInvalidationRevision` stay rejected. The missing fact is a reason,
not another integer. A later observe after invalidation increments
revision twice on those paths. The published evidence revision is the
observe revision. This design does not change that.

## D12 SESSION_POLICY

`begin_runtime_session` on a new session increments revision and does
not note. The previous completion becomes unpublished. Same-session
begin does not increment again. First restore and peak recovery also
increment and do not note. A second restore of an initialized state does
not increment.

The reader-visible result of a session boundary is the same shape as an
input invalidation: completion names omitted, fragment possibly still
present, `as_of` moved. The reader must return UNKNOWN.

CURRENT may treat "revision matches" as "this note is on the current
side of the last session bump" only after the other CURRENT proofs
exist. That does not make the session boundary itself STALE.

The fragment does not need a new session-id field for that narrow
revision fact. A session id would still not name the mismatch cause.
The gap task should add a reason, not a parallel session revision.

## D13 OWNER_SNAPSHOT_MAPPING

Producer snapshot to owner fragment, unchanged by this design:

| Producer | Owner fragment |
| --- | --- |
| `as_of` | `producerObservedAt` |
| `revision` | `revision` |
| equity, available balance, exposure, drawdown, position count | existing numeric fields |
| completion four-tuple | copied only by the existing F1 gate |
| freshness | `UNKNOWN` |
| `freshnessPolicy` | not set |

The owner does not judge CURRENT or STALE. It copies. Publication delay
is E08 and does not change the status away from UNKNOWN.

## D14 RUNTIME_EVIDENCE_MAPPING

Authority for the status is `backend/context/runtime_evidence.py`,
function `_judge`, because Advisor and Supervisor both consume the one
canonical context built from the owner document. The producer and the
owner snapshot must not each invent a status.

Mapping today, which the future implementation must preserve until the
gaps close:

| Fragment | `runtimeStatus` |
| --- | --- |
| domain missing | UNAVAILABLE |
| domain present, MM, no accepted CURRENT proofs | UNKNOWN |
| `freshness=HISTORICAL` on some other existing path | HISTORICAL, unchanged |
| MM `freshnessPolicy` present | must not be created |

`runtimeTimestamp` remains the parsed producer clock. It is not
relabeled as the completion clock. Completion time, when published,
stays inside `runtimeValues` under its own name.

A future implementation may return CURRENT or STALE only after the gap
task publishes the missing proofs and a later implementation task
changes `_judge`. That implementation is not this task. The judge must
keep ignoring a policy that ages `producerObservedAt`.

## D15 ADVISOR_SUPERVISOR_MAPPING

Both callers use the same `runtimeEvidence` on the operator context.
They must not recompute freshness from raw metrics. Supervisor snapshot
provisional ages are a different snapshot builder and must not be
applied to this MM runtime status.

The public context view continues to omit runtime evidence. No operator
MM freshness is added to the public payload. `authority` stays `NONE`.
`tradingControl` stays `FORBIDDEN`.

## D16 DECISION_MATRIX

| Case | Input evidence | Expected status | Rationale | Missing evidence | Implementation dependency |
| --- | --- | --- | --- | --- | --- |
| D01 Fragment absent | E16 absent | UNAVAILABLE | Nothing to judge | None for this status | Existing collector |
| D02 Fragment present, no completion | E16, no E01 | UNKNOWN | Numbers are not a completion | None for UNKNOWN | Do not treat revision match as optional |
| D03 Valid PAPER completion | E01–E06 match, scope PAPER | UNKNOWN | Note proves the note only | Age bound, heartbeat, undetected-mutation bound | Must not emit CURRENT |
| D04 Valid LIVE completion | E01–E06 match, scope LIVE | UNKNOWN | Note-time cache gate is not re-published | LIVE attestation on the fragment, cache heartbeat, age bound | Must not emit CURRENT. No account sync. |
| D05 PAPER manual entry invalidation | completion omitted, old numbers may remain | UNKNOWN | Reader cannot see the reason | Published mutation reason | Must not emit CURRENT or STALE |
| D06 PAPER auto mutation invalidation | completion omitted or replaced by a later note | UNKNOWN | Same reason gap. A new note is still not CURRENT. | Published reason; CURRENT proofs | None beyond the gap list |
| D07 LIVE cache mutation invalidation | completion omitted after projection change | UNKNOWN | Detected cache change is not named on the fragment | Published reason | Do not read engine position |
| D08 Revision mismatch, unknown cause | E05 absent or unequal, cause not published | UNKNOWN | Session, restore, peak, and mutation share this shape | Reason code | Forbids mismatch equals STALE |
| D09 Session restart | revision bumped, completion omitted, `as_of` moved | UNKNOWN | New session has not earned CURRENT. The boundary is not expiry. | Reason code if a consumer must explain it | No extra invalidation call |
| D10 Peak recovery | revision bumped, equity fields unchanged, completion omitted | UNKNOWN | Peak recovery is not input expiry | Reason code | Do not call it STALE |
| D11 Producer stopped | stop may invalidate; loop liveness is unpublished | UNKNOWN, or UNAVAILABLE if the fragment is gone | Stop without a published reason is not a named expiry. A surviving completion is not CURRENT. | Producer liveness or an explicit stop reason | No new observe on stop |
| D12 LIVE cache stale | account domain may be STALE; MM completion unpublished if the projection write ran | MM UNKNOWN. Account domain keeps its own status. | MM must not inherit the other domain | MM-level stale attestation if MM STALE is ever required | Do not copy account freshness onto MM |
| D13 LIVE authentication lost | same shape as D12 when the assignment path runs | MM UNKNOWN | Authentication is not an MM field | MM-level auth attestation | No exchange call |
| D14 LIVE partial snapshot | note gate does not complete | UNKNOWN | Partial is not COMPLETE | A partial reason, if STALE is required for this case | No new snapshot builder |
| D15 Observation failure | old clock retained in memory, unpublished while revisions differ | UNKNOWN or UNAVAILABLE | Failure is not success and not a named expiry | None for UNKNOWN | Re-note required before a new completion |
| D16 Observation age unknown | any otherwise complete fragment | UNKNOWN | No accepted TTL | An owner-approved age bound, which this design refuses to invent | Do not arm `freshnessPolicy` |
| D17 Source unknown | LIVE sources not on the MM fragment | UNKNOWN | Note-time source check cannot be repeated | Published source attestation | No exchange call |
| D18 Mode mismatch | scope is historical; config mode can differ | UNKNOWN whenever CURRENT is not proven. Config mismatch alone changes nothing. | Scope is not `config.TRADE_MODE` | None, unless a consumer needs config mode, which this policy does not | Do not invalidate on `/set_mode` |
| D19 Publication delay | E08 later than E01 or E07 | UNKNOWN | Store time is not input age | None | Do not age `publishedAt` |
| D20 Reader delay | reader clock later than the fragment | UNKNOWN | There is no `readAt` producer field | None | Do not age the reader clock into STALE |

## D17 IMPLEMENTATION_FILE_MAP

This task changes only this document. A later implementation, after the
gap task, is limited to the judgment. It must not change trading
behavior.

| File | Later change | Not allowed |
| --- | --- | --- |
| `backend/context/runtime_evidence.py` | After gaps close, judge MM from the completion names, the reason field, and the accepted extra proofs. Until then, do not change it. | Arming `freshnessPolicy`. Aging `producerObservedAt`. Returning CURRENT or STALE early. |
| `backend/bot_manager/owner_snapshot.py` | Pass through a future reason field on the existing allowlist. | Computing a status. Copying operator evidence to a public shape. |
| `backend/money_management/loss_authoritative_runtime_metrics.py` | A future gap task may store a reason beside the existing invalidation. | A new revision counter. Moving `as_of` or the completion clock inside invalidation. |
| `backend/bot_manager/bot_manager.py` | A future gap task may pass the reason already known at today's call sites. | New observe on manual entry. Account sync. Exchange calls. Trading-branch changes. |
| `backend/context/context_views.py` | No change | Publishing runtime evidence |
| `backend/supervisor/runtime_snapshot_adapter.py` | No change | Adopting the provisional 30 seconds as this policy |
| `Bot/engine/execution_engine.py` | No change | Using `actual_position` as LIVE MM freshness |
| Tests | New judgment tests listed in D18, in a later task | Rewriting F01–F09 or the known exchange failures |

## D18 TEST_PLAN

Future tests, not executed as production changes here:

1. Fragment absent returns UNAVAILABLE.
2. Fragment present, completion omitted, returns UNKNOWN, including
   after PAPER manual entry with stale numeric fields.
3. PAPER and LIVE fragments that meet the F1 publication gate return
   UNKNOWN, never CURRENT.
4. Revision mismatch from a simulated session bump and from a simulated
   peak bump returns UNKNOWN, never STALE.
5. A fragment with `freshnessPolicy` is not produced by the owner
   helper. A judge fixture that includes such a policy must not be the
   MM production path. The production owner fragment has no policy.
6. `producerObservedAt`, `publishedAt`, and the completion clock are
   asserted as different fields. Aging `producerObservedAt` is not the
   MM status.
7. Real-account `freshness=STALE` does not change MM `runtimeStatus`.
8. Advisor and Supervisor fixtures that share one operator context show
   the same MM `runtimeStatus`.
9. The public context view has no runtime evidence and no MM fragment.
10. LIVE engine position differing from the cache does not change MM
    status.
11. No test calls an exchange or account sync.
12. Existing F1 completion tests and F2 invalidation tests stay green.
    The known unrelated failures stay classified as pre-existing and
    are not fixed here.

## D19 REMAINING_GAPS

1. No published invalidation reason. Without it, STALE cannot be
   distinguished from session start, restore, and peak recovery.
2. No producer heartbeat or loop-liveness field.
3. No accepted MM age bound. Existing 30 second and 90 second numbers
   belong to other mechanisms.
4. LIVE source, authenticated, and stale are not on the MM fragment
   after the note. They cannot be re-checked, and they must not be
   joined from the real-account domain inside this judgment.
5. Undetected mutations and the PAPER manual-entry window are visible
   only as a missing completion, which is UNKNOWN.
6. `runtime_evidence._policy_status` can still return CURRENT for a
   money-management fragment if some other writer adds `freshnessPolicy`
   and the age of `producerObservedAt` is inside the policy. The owner
   path does not do that today. The gap is that the judge still
   implements a clock this policy rejects. The implementation task that
   follows the gaps should disconnect MM from that `as_of` policy.
7. LIVE cache versus engine position remains unresolved on purpose.
   Closing it would require account sync, which stays forbidden.
8. Pre-existing test failures F01–F09 and the previously compared
   exchange-live failures are outside this design.

## D20 NEXT_RECOMMENDED_TASK

`BB_MM_F3_FRESHNESS_EVIDENCE_GAP_COMPLETION`

The policy is specific enough to implement safely, and the safe
implementation is to keep UNKNOWN or UNAVAILABLE until the gaps close.
CURRENT's missing proofs are producer evidence, so the next task is the
evidence gap, not `BB_MM_F3_FRESHNESS_POLICY_IMPLEMENTATION`. That
implementation task should start only after the gap task lands a reason
code and an explicit decision on heartbeat and LIVE attestation.
It must still not invent a TTL. This design does not start that work.

## Acceptance matrix

| ID | Result | Reason |
| --- | --- | --- |
| A01 F1 contract preserved | PASS | No producer or publication change |
| A02 F2 contract preserved | PASS | Invalidation stays a revision bump without a new clock |
| A03 CURRENT conditions defined | PASS | Conjunction stated. It is not satisfiable today. |
| A04 STALE conditions defined | PASS | Named reasons only. Emission forbidden until a reason exists. |
| A05 UNKNOWN conditions defined | PASS | Default for every present MM fragment |
| A06 UNAVAILABLE conditions defined | PASS | Missing fragment only |
| A07 PAPER conditions defined | PASS | Manual-entry lag is UNKNOWN |
| A08 LIVE conditions defined | PASS | Cache, not engine position. No sync. |
| A09 Revision semantics defined | PASS | Match is detected-invalidation silence, not freshness |
| A10 Session semantics defined | PASS | Boundary unpublishes and is UNKNOWN |
| A11 Timestamp semantics defined | PASS | Five clocks stay distinct |
| A12 Time freshness evaluated | PASS | Existing intervals rejected as an MM TTL |
| A13 Owner snapshot mapping defined | PASS | Copy only |
| A14 Runtime evidence mapping defined | PASS | Single judge. No CURRENT yet. |
| A15 Advisor / Supervisor consistency | PASS | One operator context |
| A16 PUBLIC isolation | PASS | Runtime evidence stays off the public view |
| A17 No false CURRENT | PASS | CURRENT withheld |
| A18 No false STALE | PASS | Mismatch is not STALE |
| A19 No account sync | PASS | Not added |
| A20 No exchange API | PASS | Not added |
| A21 No trading logic change | PASS | Document only |
| A22 Implementation file map | PASS | Listed, including non-changes |
| A23 Test plan | PASS | Future tests listed |
| A24 Canonical reconciliation | PASS | No conflicting focus path. Main not merged. |

BLOCK_REASON: none.

DEPENDENCY: F2 acceptance `06fb04c work-bb: accept mm observation invalidation`.

RESUME_CONDITION: a later task may add the missing reason and liveness
evidence. It may not emit CURRENT until those fields exist and an age
bound has an owner other than a guessed number. This task stops here.
