# BB-MM-F1.6 MM Producer Instrumentation Design

Read-only design. No runtime code, test, account sync, risk evaluation, or
order was run. The project-spec `HASH_MISMATCH` is a separate gap.

`EVALUATION_COMPLETION=NOT_AVAILABLE` for
`BotManager.money_management_runtime_metrics`. `evaluate_sizing` and the loss
runtime `risk_state` are different objects. They do not complete this metrics
write. This design does not invent an evaluation completion point and does
not select `mmEvaluationCompletedAt`.

## Canonical Reconciliation

Base `2bb211d19ca06959c8c9e058170f486ccafb51dd`. merge-base with origin/main
is `39273a115637edaba42ea49bde732f1ae6436399`.

| Path | Class |
| --- | --- |
| backend/money_management/loss_http_api.py | MAIN_ONLY preview age and execution-entry preview. Not copied |
| backend/money_management/loss_execution_integration.py | MAIN_ONLY. Not copied |
| backend/runtime/cycle_diagnostics.py | MAIN_ONLY. Not copied |
| backend/supervisor/snapshot_builder.py | SHARED_PATH_REVIEW_REQUIRED. Not copied |
| backend/supervisor/runtime_snapshot_adapter.py | SHARED_PATH_REVIEW_REQUIRED. Not copied |

origin/main compares a metrics age with `_maximum_metrics_age` inside the
loss HTTP preview. That age is not an observation completion clock and is
not adopted. No merge and no cherry-pick.

## Evaluation Lifecycle

| Stage | What exists | Result |
| --- | --- | --- |
| Entry | `_observe_money_management_runtime_metrics` | Metrics observation. Not a risk evaluation |
| Input observation | PAPER `_capture_account_snapshot`. LIVE read of `real_account_snapshot` | LIVE read does not sync |
| Risk state | Not assigned by `observe` | `EVALUATION_COMPLETION=NOT_AVAILABLE` |
| Metrics construction | `observe` assigns balance, equity, position metrics, peak rules, then `_as_of` and `_revision` | Cache write even when `observation_valid` is false |
| Successful completion | `observe` returns `_snapshot_locked` | This is observation return, not risk-evaluation completion |
| Failure | `engine is None` returns before `observe`. Capture exception keeps the previous paper snapshot and `observe` still runs. `observe` raises on session mismatch and on an invalid close id after some fields are already assigned | Existing mutation is unchanged by this design |
| Publication | `_publish_context_snapshot` calls `held_runtime_domains`, which calls `snapshot()` | Read. `publishedAt` is the publication clock |

`begin_runtime_session`, `restore`, and `apply_validated_peak_recovery` also
move `_as_of` and `_revision`. They are not observation completions.

## Producer Timestamp

| Candidate | Decision | Meaning |
| --- | --- | --- |
| `mmEvaluationCompletedAt` | Rejected | No evaluation completion exists on this producer |
| `mmInputsCapturedAt` | Not selected | PAPER `last_update` and LIVE `lastSync` are earlier clocks. `lastSync` can advance on a partial sync |
| `mmObservationCompletedAt` | Selected | Time after a qualifying `observe` return. It does not replace `as_of` |

Selected clock:

| Item | Rule |
| --- | --- |
| Owner | `AuthoritativeLossRuntimeMetricsState`, written only by a new note method |
| Write point | After `observe` or `observe_stopped_paper_maintenance` returns |
| Caller | `_observe_money_management_runtime_metrics`, and the stopped PAPER maintenance caller |
| Success | Return without an exception, `observation_valid` is true, and input completeness is `COMPLETE` |
| Failure | Do not write the clock. Do not change the existing `as_of` |
| Read | `snapshot()` and `runtime_evidence` do not write it |
| Existing `as_of` | Unchanged. PAPER remains the wall clock taken before `observe`. LIVE remains `lastSync` or the fallback wall clock |
| Scope | The account and position fields that this call passed into `observe` |
| CURRENT | The clock alone does not make any status `CURRENT` |

The published copy is valid only when the stored evidence revision equals
the metrics revision. Session start, restore, peak recovery, and an
`observe` that increments revision without a new note leave the clock
unpublished. `publishedAt` is not this clock.

## Input Scope

Only inputs that this producer reads are in scope.

| Input | Owner | Method | Revision | Time | Required | Missing | Invalidation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PAPER balance, equity, available balance, pnl | engine via `_capture_account_snapshot` | attribute read | none. `last_update` is not a revision | `time.time` on the paper snapshot, then a separate wall clock for `as_of` | yes for a complete PAPER observation | capture exception keeps the previous snapshot. No success clock | next successful observe, or revision mismatch |
| PAPER position | `engine.actual_position` | same capture | none | same | yes. `None` is an empty position list, and count `0` stays `0` | same | same |
| LIVE balance, equity, available balance, unrealized pnl | `real_account_snapshot` | stored cache read | account generation, not metrics revision | `lastSync` only if that refresh succeeded for balance or position | yes for `COMPLETE` | failed side keeps the previous value when `stale`, otherwise null | no success clock unless both sides succeeded on that snapshot |
| LIVE position | same cache | `positions` | none on this producer | same `lastSync` | yes for `COMPLETE` | same | same |
| Peak equity | metrics accumulator. PAPER may pass `engine.peak_equity` | inside `observe` | metrics revision | observe `as_of` | no separate input | unpublished | peak recovery moves revision and must not stamp this clock |
| Drawdown | computed in `_snapshot_locked` | derived | same revision | same | output, not an input | reader must not recompute it | same |
| Exposure and position count | `_position_metrics` | derived from the position argument | same | same | output of the same observation | null stays null | same |
| Risk parameters | loss configuration | not read by `observe` | `configuration_revision` on the loss HTTP service | not this clock | no for this producer | not part of this scope | UNKNOWN. Not a global MM revision |
| MM configuration | same service | not read by `observe` | same configuration revision | not this clock | no for this producer | not part of this scope | UNKNOWN |
| Trade mode | `engine.mode` | selects PAPER or LIVE | none found | none | yes as a branch selector | non-paper uses the LIVE cache | in-process mode switch without a new observation is UNKNOWN |

Risk state is outside this scope. A loss-runtime `risk_state` change is not
an input revision of this fragment.

## PAPER

1. Remember the current `account_snapshot` object.
2. Call `_capture_account_snapshot`.
3. A new snapshot object means this call replaced it. The same object means
   the exception path returned the previous snapshot.
4. Call `observe` with the existing arguments. Do not change `as_of`.
5. Note `mmObservationCompletedAt` only when the capture object changed,
   `observe` returned, and `observation_valid` is true.
6. On any other result, do not note the clock.

Stopped PAPER maintenance can note the clock only after
`observe_stopped_paper_maintenance` returns with `observation_valid` true.
Its existing `as_of` stays the caller-supplied observation time.

## LIVE Partial Sync

`balance_ok` and `position_ok` are local to `_refresh_real_account_snapshot`.
The stored signals that a later observe can read are `balanceSource`,
`positionSource`, `stale`, and `authenticated`.

| Result | Status | Completeness | Success clock |
| --- | --- | --- | --- |
| Balance source set, position source absent | `BALANCE_ONLY` | not complete | no |
| Position source set, balance source absent | `POSITION_ONLY` | not complete | no |
| Both sources absent | `NONE` | not complete | no |
| Both sources are `KUCOIN_FUTURES_READ_ONLY`, `authenticated` is true, and `stale` is not true | both sides present on that snapshot | `COMPLETE` for this account input | yes, at the observe return |
| Snapshot shape not recognized | `UNKNOWN` | not complete | no |

`COMPLETE` means both account sides were present on the snapshot that this
observe copied. It does not mean an MM evaluation finished, and it does not
make the domain `CURRENT`. `lastSync` stays the refresh clock. The new clock
is the time after `observe` returns.

A partial or failed refresh may still reach the existing `observe`. This
design does not remove that call and does not change the metrics math. The
revision increment then makes an older success clock unpublished.

## Revisions

| Revision | Covers | Use |
| --- | --- | --- |
| metrics `_revision` | the write that incremented it, including session start and peak recovery | store it beside a success clock. Publish the clock only when the numbers match. Not a global MM revision |
| loss-limit store revision | loss-limit lifecycle | not this fragment |
| `configuration_revision` | loss HTTP configuration | exists, and is not read by `observe`. Not a global MM revision |
| account generation | which refresh commit landed | not this fragment |
| paper `last_update` | one capture | not a revision |
| position revision | none on this producer | candidate only, not an existing control |
| trade-mode revision | none found | candidate only |

No composite account, position, config, and mode revision is adopted. The
missing members would be new controls, not discovered ones.

## Invalidation

| Event | Module | Trigger | Fields | Revision | Point | Required later | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Trading-cycle observe | `bot_manager` | authority still `STARTING` or `RUNNING`, then observe | account and position inputs | +1 | note only on complete success | none for the note | VERIFIED caller |
| Manual close | `bot_manager` | close finalizer | same, plus period stats for `TRADE_CLOSE` | +1 | same | none | VERIFIED |
| Emergency observe | `bot_manager` | emergency path | same | +1 | same | none | VERIFIED |
| PAPER capital reset | `bot_manager` | reset then observe | paper account fields | +1 | same | none | VERIFIED |
| LIVE refresh | `bot_manager` | refresh commit | none until a later observe | account generation | do not note on partial or failed | none in this design | VERIFIED account write |
| Session start | metrics `begin_runtime_session` | new session | `as_of`, session trade count. Equity remains | +1 | do not note | publication must drop the old clock | VERIFIED |
| Peak recovery | `apply_validated_peak_recovery` | persisted lower peak | peak and `as_of` | +1 | do not note | same | VERIFIED |
| Restart | new `BotManager` | constructor | new object starts unpublished | 0 | no carried clock | none | VERIFIED for a new object |
| Position open | no observe name found | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | a later task must find the mutation and either re-observe or clear the clock | UNKNOWN |
| Position close outside the named paths | not exhaustively proven | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | same | UNKNOWN |
| Position update | no separate name | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | same | UNKNOWN |
| Config change | loss HTTP configuration revision | not an observe caller | config, not this fragment | configuration revision only | none | do not treat it as this observation's revision | UNKNOWN for this fragment |
| Risk parameter change | no metrics write found | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | same | UNKNOWN |
| Mode switch | `engine.mode` branch | no in-process invalidation found | branch selection | none | UNKNOWN | same | UNKNOWN |
| Emergency stop as its own event | execution fragment has `emergencyStop` | not shown to clear MM metrics | execution fields | execution cache, not MM | do not infer MM invalidation | UNKNOWN | UNKNOWN |

CURRENT stays forbidden while position open, position update, mode switch,
and risk-parameter invalidation are UNKNOWN. Absence of a call is not
evidence that the old observation remains valid.

## Evidence Contract

Schema version stays `tradingai-owner-snapshot/v1`. No schema file is
changed. The publisher allowlist drops money-management names that are not
in `_DOMAIN_FIELDS`. A later implementation must add only these names:

| Field | Values |
| --- | --- |
| `observationCompletedAt` | UTC timestamp, or absent |
| `inputCompleteness` | `COMPLETE`, `BALANCE_ONLY`, `POSITION_ONLY`, `NONE`, `UNKNOWN` |
| `inputScope` | `PAPER_ENGINE_ACCOUNT` or `LIVE_ACCOUNT_CACHE` |
| `evidenceRevision` | metrics revision that the clock belongs to |

`producerObservedAt` continues to copy `as_of`. `freshnessPolicy` stays
absent. `freshness` stays `UNKNOWN`. Peak equity, risk state, and execution
permission stay unpublished.

Reason for the allowlist addition: without it, the note exists in memory and
the owner document cannot show it. Impact: operator runtime values can carry
the four names. The reader still does not calculate MM values. Public view
does not receive operator runtime evidence. No status becomes `CURRENT`.

## Owner Snapshot and Runtime Evidence

Copy point: `_held_money_management`, after `snapshot()` returns, and only
when `observation_valid` is true, `source_state` is not `NOT_INITIALIZED`,
and `evidenceRevision` equals `revision`. Otherwise omit the new clock and
completeness. Do not read the exchange and do not evaluate risk.

`runtime_evidence._judge` stays as it is. A missing fragment is
`UNAVAILABLE`. A fragment with `producerObservedAt` and no money-management
policy is `UNKNOWN`. `STALE` remains the existing explicit label or a future
policy age. This design sets neither. `CURRENT` requires a later proof of
producer, complete inputs, scope, invalidation, and a freshness policy.
Those conditions are not met.

Advisor and Supervisor receive the operator context. MM `CURRENT` would not
make execution authority, the live account, supervisor runtime, market
selection, or market intelligence `CURRENT`. This observation is not
live-order permission. A supervisor recommendation is not MM authority.

Null stays null. Zero stays zero. False stays false.

## Policy

| Option | Coverage | Cost | False CURRENT | PAPER and LIVE | Side effect | Tests | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A. Observation timestamp alone | one new clock | low | high, because invalidation is incomplete | same clock name, different completeness rules | none if the note is separate | good | Rejected as a CURRENT rule |
| B. Composite revision | config revision exists. Position and mode revisions do not | medium | high if the composite is invented | no shared revision | none | poor | Rejected |
| C. Event invalidation | verified observe paths only | medium | high while position open and mode switch are UNKNOWN | PAPER and LIVE events differ | none if read-only | incomplete | Not sufficient |
| D. Hybrid | needs A, B, and C | high | high until the UNKNOWN rows are resolved | can be consistent only after that | none if the note is separate | blocked | Deferred |
| E. Remain UNKNOWN | honest | none now | low | both modes stay UNKNOWN | none | current tests already expect UNKNOWN | Selected |

No TTL is selected. The account intervals 30 and 90, and the main-only
preview age, are not reused.

## Minimum Later Change

Not done here. The next task is invalidation coverage, not this
implementation.

| Target | Function | Write | Read | Fields | Failure | Invalidation |
| --- | --- | --- | --- | --- | --- | --- |
| `loss_authoritative_runtime_metrics.py` | new note method | after a qualifying return | included in the locked snapshot | the four contract fields | note is skipped | session start, restore, and peak recovery do not note |
| `bot_manager.py` | `_observe_money_management_runtime_metrics` | after `observe` | capture object identity and LIVE source fields | calls the note | same object, exception, invalid observation, or partial LIVE: no note | does not change the existing observe call |
| `bot_manager.py` | stopped PAPER caller | after stopped observe | returned snapshot | calls the note | invalid or raised: no note | same |
| `owner_snapshot.py` | `_held_money_management` and the money-management allowlist | copy | `snapshot()` | four names, only on revision match | omit the new names | no `freshnessPolicy` |
| `runtime_evidence.py` | none | none | existing judge | none | unchanged | unchanged |

MM arithmetic, execution authority, and order flow stay unchanged.

## Test Plan

Not run.

| Test | Proves |
| --- | --- |
| T01 | PAPER capture replacement plus valid observe notes the clock |
| T02 | PAPER capture exception or invalid observe does not note it |
| T03 | LIVE both sources and not stale notes `COMPLETE` |
| T04 | Balance-only does not note and is not full success |
| T05 | Position-only does not note and is not full success |
| T06 | Both failed does not note |
| T07 | The new clock is after observe returns |
| T08 | `snapshot()`, publication, and the evidence reader do not move it |
| T09 | Session start and peak recovery bump revision and unpublish the old clock |
| T10 | Position open stays UNKNOWN until a real trigger is found |
| T11 | Equity change without observe does not count as a new observation |
| T12 | Configuration revision is not this fragment's revision |
| T13 | Mode switch stays UNKNOWN |
| T14 | A new object does not carry the old clock |
| T15 | Missing completeness stays UNKNOWN |
| T16 | Missing fragment stays UNAVAILABLE |
| T17 | No path returns CURRENT |
| T18 | Null equity stays null |
| T19 | Position count zero stays zero |
| T20 | False stays false |
| T21 | Owner copy happens only on revision match |
| T22 | Runtime evidence stays UNKNOWN without a policy |
| T23 | Advisor context does not turn the clock into authority |
| T24 | Supervisor context does not turn the clock into authority |
| T25 | Operator authentication still gates the operator context |
| T26 | Public view does not receive the operator MM evidence |
| T27 | The reader does not sync an account |
| T28 | The reader does not evaluate risk |
| T29 | No order path is called |
| T30 | Existing metrics numbers are unchanged by the note |

## Acceptance Matrix

| Item | Result |
| --- | --- |
| A01 Evaluation Lifecycle | PASS |
| A02 Producer Timestamp Design | PASS |
| A03 Input Scope | PASS |
| A04 PAPER Observation | PASS |
| A05 LIVE Partial Sync | PASS |
| A06 Revision Coverage | PARTIAL |
| A07 Invalidation Coverage | PARTIAL |
| A08 Producer Evidence Contract | PASS |
| A09 Owner Snapshot Mapping | PASS |
| A10 Runtime Evidence Mapping | PASS |
| A11 Freshness Policy Options | PASS |
| A12 Recommended Design | PARTIAL |
| A13 Minimal Implementation Plan | PASS |
| A14 Regression Test Plan | PASS |
| A15 Canonical Reconciliation | PASS |
| A16 Authority Boundary | PASS |
| A17 Security Boundary | PASS |
| A18 No Runtime Mutation | PASS |
| A19 No Production Connection | PASS |
| A20 No Real Orders | PASS |

A06 is PARTIAL because no revision covers MM as a whole. A07 is PARTIAL
because position open, position update, mode switch, and risk-parameter
invalidation are UNKNOWN. A12 is PARTIAL because the selected policy
withholds CURRENT. Those gaps are not marked PASS.

## Remaining Gaps

- No MM risk-evaluation completion on this producer.
- Position open, position update, mode switch, and risk-parameter
  invalidation have no verified trigger.
- Configuration revision does not cover this fragment.
- The success clock cannot be published until the allowlist is extended.
- `CURRENT` remains unavailable.
