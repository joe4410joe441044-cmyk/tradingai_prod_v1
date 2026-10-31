# BB-MM-F1.5 MM Producer Evidence

Read-only completion of the partial freshness design. No runtime code was
changed. No account sync, risk evaluation, or order was run. The project-spec
`HASH_MISMATCH` is a separate gap and is not freshness evidence.

## Canonical Reconciliation

Base `372d181556135073c256e25f14b3c4f3a4cc1cff`. merge-base with origin/main
is `39273a115637edaba42ea49bde732f1ae6436399`.

| Path | Class |
| --- | --- |
| backend/money_management/loss_http_api.py | MAIN_ONLY. Not copied |
| backend/money_management/loss_execution_integration.py | MAIN_ONLY. Not copied |
| backend/runtime/cycle_diagnostics.py | MAIN_ONLY. Not copied |
| backend/supervisor/snapshot_builder.py | SHARED_PATH_REVIEW_REQUIRED. Not copied |
| backend/supervisor/runtime_snapshot_adapter.py | SHARED_PATH_REVIEW_REQUIRED. Not copied |

origin/main still has a preview age `_maximum_metrics_age`. It is not on
this branch and is not adopted. `account_refresh_interval` (30) and
`account_stale_after` (90) are live-account refresh controls. They are not
an MM evaluation freshness policy.

## Producer Call Graph

The object is created in `BotManager.__init__` as
`AuthoritativeLossRuntimeMetricsState(runtime_instance_id)`.

| Caller | Callee | Mode | Read or write | Side effect | Observation source | Timestamp | Cache owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `BotManager.__init__` | state constructor | SHARED | WRITE | `source_state=NOT_INITIALIZED`, `observation_valid=false` | none | `datetime.now` at construction | metrics state |
| start path | `begin_runtime_session` | SHARED | WRITE | new session id, zero session trade count, `_observed=false`. Equity and `observation_valid` are not cleared | none | `datetime.now` at session start | metrics state |
| `initialize_money_management_runtime_metrics` | `restore` | SHARED | WRITE once | periods and persisted peak. Returns the current snapshot if already initialized | persisted loss state | caller `as_of` | metrics state |
| same initialize, stopped PAPER only | `observe_stopped_paper_maintenance` | PAPER | WRITE | paper equity fields. Refuses a non-PAPER accounting authority before mutation | paper account store observation | `observation.observed_at`, which the caller set from `datetime.now` | metrics state |
| `_observe_money_management_runtime_metrics` | `observe` | PAPER | WRITE | copies engine balance, pnl, and `actual_position` | `_capture_account_snapshot` | `datetime.now` after that capture returns | metrics state |
| same method | `observe` | LIVE | WRITE | copies `real_account_snapshot` fields | stored account cache. This method does not sync | `lastSync` if it is a finite non-negative number, otherwise `datetime.now` | metrics state |
| `loss_http_api` after a persisted peak recovery | `apply_validated_peak_recovery` | SHARED | WRITE | peak only, and only when it does not rise | persisted recovery checkpoint | `max(previous as_of, caller now)` | metrics state |
| owner `_held_money_management` | `snapshot` | SHARED | READ | lock copy. No observe | held fields | existing `as_of` copied to `producerObservedAt` | owner document after `_publish_context_snapshot` |

`snapshot()` is the publication read. It does not update `as_of` or revision.

Callers of `_observe_money_management_runtime_metrics`, all in `bot_manager.py`:

- PAPER capital reset
- manual close finalizer
- trading-cycle callback, after the `STARTING`/`RUNNING` authority check
- RUNNING baseline when the current snapshot is incomplete
- emergency operation path

## PAPER

`_capture_account_snapshot` reads `engine.balance`, `engine.pnl`,
`engine.unrealized_pnl`, and `engine.actual_position`. It stores
`last_update = time.time()` on `account_snapshot`. The MM write does not use
`last_update`. It uses a later `datetime.now`. That clock is the observation
function wall clock. It is not an evaluation completion time.

| Value | Source | Update trigger | Last mutation | Timestamp | Revision | Invalidation |
| --- | --- | --- | --- | --- | --- | --- |
| Equity | `balance + unrealized_pnl` inside the capture | verified observe callers | `observe` | wall clock after capture | metrics revision +1 | not cleared on session begin |
| Balance | `engine.balance` | same | `observe` | same wall clock | same | same |
| Position | `engine.actual_position` | same | `observe` | same wall clock | same | a position change is not visible until a later observe |
| Drawdown percent | already on the metrics snapshot | `observe` | `observe` | same | same | reader does not recompute it |
| Exposure and position count | `_position_metrics` | `observe` | `observe` | same | same | same |
| Peak equity | accumulator in `observe` or validated recovery | those writes | those writes | observe clock or recovery max | +1 | not published |
| Risk state | not this object | UNKNOWN | UNKNOWN | UNKNOWN | not this revision | UNKNOWN |

The capture's `last_update` is not a metrics revision. No separate paper
account revision is copied into the MM fragment.

## LIVE lastSync

`lastSync` is written by `_refresh_real_account_snapshot`.

- `now = time.time()` at the start of that refresh.
- `lastSync` becomes `now` when `balance_ok or position_ok`.
- If both fail, the previous `lastSync` is kept.
- `stale` is true when a previous `lastSync` exists and either balance or
  position failed.
- On the failed side, equity or positions stay at the previous value when
  `stale` is true, and become null when there is no previous sync.
- `KucoinTradeClient` also puts `time.time()` on the parsed overview. The
  snapshot then replaces `lastSync` with the refresh `now` above.
- `_mark_real_account_stale_if_needed` sets `stale=true` when
  `time.time() - lastSync > account_stale_after` (90). It does not change
  `lastSync` and it does not write MM metrics.
- Refresh is skipped when the last attempt is inside
  `account_refresh_interval` (30), unless forced. That skip does not observe
  MM.

The MM LIVE path reads this cache. It does not call the exchange. If
`authenticated` is not true or `stale` is true, `source_state` becomes
`UNAVAILABLE`, but `observe` still runs. The owner fragment does not copy
`source_state` or `stale`.

`lastSync` therefore means "a refresh where balance or position succeeded".
It does not mean both sides are current, and it does not mean an MM
evaluation finished. A partial success advances the clock while one side can
remain old. That clock fails the requirement that one timestamp have one
scope.

## Evaluation Completion

| Candidate | Result | Evidence |
| --- | --- | --- |
| Risk evaluation completion | NOT_VERIFIED as the metrics write | `evaluate_sizing` is a separate function. It is not the metrics `observe` |
| Position size calculation completion | NOT_VERIFIED as a distinct exit | position count is a side result of `observe` |
| Metrics snapshot completion | VERIFIED as a cache write | `observe` assigns fields, sets `_as_of`, increments `_revision`, and returns `_snapshot_locked` |
| Metrics publication | VERIFIED as a later read | `_publish_context_snapshot` copies the snapshot. `publishedAt` is that later clock |
| Account observation | VERIFIED as the input | PAPER capture or LIVE cache. Neither is an MM risk evaluation |

No existing point is a safe producer timestamp for `CURRENT`.

A later instrumentation design could record a new clock only after `observe`
returns a snapshot, and only for that write's scope. This task does not add
that clock. The current `as_of` must not be renamed into that clock, because
PAPER `as_of` is a read clock and LIVE `as_of` is `lastSync` or a fallback
read clock. `begin_runtime_session` also moves `as_of` and revision without
a new equity observation.

## Revisions

| Revision | Owner | Increment | Reset | Covered | Not covered | Publication |
| --- | --- | --- | --- | --- | --- | --- |
| metrics `_revision` | `AuthoritativeLossRuntimeMetricsState` | `observe`, `begin_runtime_session`, `restore`, stopped-paper maintenance, validated peak recovery | starts at 0. Session begin increments. It does not by itself clear equity | the fields that particular write changed | risk evaluation, MM config, loss-limit store, paper `last_update`, live `lastSync` | owner fragment `revision` |
| loss-limit store revision | `LossLimitRuntimeSnapshot` | store update and stop | separate from the metrics revision | loss-limit lifecycle and governance projection | the held equity fragment | not the owner MM fragment |
| account generation | `account_snapshot_generation` | account snapshot generation | exchange change can reject a stale commit | which refresh commit is current | MM evaluation | not the MM fragment |
| paper `last_update` | `account_snapshot` | each successful capture | not a revision counter | the captured paper numbers | not read by the MM `as_of` assignment | not the MM fragment |

The metrics revision changes on a session start that does not re-observe
equity. It also changes on a peak-only recovery. It does not cover MM as a
whole. It is not a `CURRENT` rule.

## Invalidation

| Event | Code path | MM fields | Revision | Cache invalidation | Timestamp | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Trading-cycle evaluation | callback then observe, if still `STARTING` or `RUNNING` | equity, position, exposure, drawdown inputs | +1 on success | callback returns before observe when authority is gone | PAPER wall clock or LIVE `lastSync` | VERIFIED |
| Manual close | `_finalize_manual_close_money_management` | same, plus period stats when the event is `TRADE_CLOSE` | +1 unless observe raises | failure keeps the previous snapshot | same | VERIFIED |
| Emergency path | emergency observe call | same | +1 on success | no separate MM stale flag | same | VERIFIED |
| PAPER capital reset | publish paper snapshot, then observe | equity and position from the new paper snapshot | +1 | no TTL | PAPER wall clock | VERIFIED |
| LIVE account refresh | writes `real_account_snapshot` only | none until a later observe | account generation, not metrics revision | failed refresh keeps previous `lastSync` | `lastSync` | VERIFIED as an account write, not an MM write |
| LIVE stale mark | `_mark_real_account_stale_if_needed` | none immediately | none | sets account `stale` | does not change `lastSync` | VERIFIED |
| Session start | `begin_runtime_session` | session trade count and `as_of`. Equity remains | +1 | `_observed=false` only. `observation_valid` is not cleared | session `datetime.now` | VERIFIED |
| Mode or restart | new `runtime_instance_id` only when a new BotManager is constructed | new object starts `NOT_INITIALIZED` | 0 | old object is not updated in place by this finding | construction clock, unpublished | VERIFIED for construction. In-process mode switch without a new object is UNKNOWN |
| MM configuration change | no observe call found | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Risk parameter change | no metrics write found | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Position open as its own event | no separate observe name | UNKNOWN until some verified observe reads the engine | UNKNOWN | previous metrics stay published | UNKNOWN | UNKNOWN |
| Position close | manual close and a classified `TRADE_CLOSE` | verified for those paths | +1 | other close paths were not exhaustively proven | observe clock | VERIFIED only for the named paths |

Absence of an invalidation call is not treated as proof that the data stays
fresh.

## Timestamp Candidates

| Clock | Owner | Meaning | Fails |
| --- | --- | --- | --- |
| A. Observation wall clock | PAPER `observe` | time after the engine capture returns | read clock. Not evaluation completion. A read of `snapshot()` does not move it, but the write that creates it is itself a read clock |
| B. Evaluation completion | none | not found | no candidate |
| C. `lastSync` | account refresh | time.time at a refresh where balance or position succeeded | not MM completion. Scope can mix a new balance with an old position. Failure does not advance it, which is necessary but not sufficient |
| D. `publishedAt` | owner document | publication time | not the producer observation |
| E. Reader `datetime.now` | `runtime_evidence._policy_status` | age comparison only after a stored policy | there is no stored policy. This clock must not become the producer time |

`PRODUCER_TIMESTAMP=UNKNOWN`.

No candidate is owned by one producer, tied to one success scope, unique in
meaning, and left unchanged by a read. `snapshot()` itself does not bump the
clock. The clocks that do get written fail the meaning test.

## Policy

| Option | Coverage | Invalidation | False CURRENT | Cost | Side effect | Tests | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A. Use one existing timestamp | no single clock | poor | high | low | none | would lock in the wrong meaning | Rejected |
| B. Event invalidation only | verified events only | position open, config, and risk remain UNKNOWN | high if latest observe means CURRENT | medium | none if read-only | incomplete fixtures | Not sufficient |
| C. Metrics revision | revision exists | session begin and peak recovery also increment it | high | low | none | easy and misleading | Not sufficient |
| D. Hybrid | needs A plus B plus C | not available | high until the clock is unique | high | none if read-only | blocked | Deferred |
| E. Remain UNKNOWN | honest | does not invent coverage | low | none | none | current owner tests already expect UNKNOWN | Selected |

No TTL is selected. The account intervals 30 and 90 are not reused.

## Owner Snapshot and Runtime Evidence

`_publish_context_snapshot` calls `held_runtime_domains` with no caller
fragment. `_held_money_management` copies the locked snapshot when
`observation_valid` is true and `source_state` is not `NOT_INITIALIZED`.
`as_of` becomes `producerObservedAt`. Metrics revision becomes `revision`.
`freshnessPolicy` is not set. `publishedAt` stays the publication clock.

`runtime_evidence._judge` returns `UNKNOWN` when `producerObservedAt` parses
and no `moneyManagement` policy is stored. A missing fragment stays
`UNAVAILABLE`. The reader does not calculate equity, drawdown, or peak, and
it does not sync.

Advisor and Supervisor receive that `UNKNOWN` domain through the existing
shared operator context. `CURRENT` on MM would not make execution authority,
the live account, supervisor runtime, market selection, or market
intelligence `CURRENT`. An MM value is not live-order permission. A
supervisor recommendation is not MM authority.

Null equity stays null. Position count `0` stays `0`. `UNKNOWN` is not
rewritten to `0` or `false`. Peak equity stays unpublished.

Public context view does not copy operator runtime evidence.

## Minimum Later Change

Not done here.

1. Do not attach a TTL and do not treat `as_of` as evaluation completion.
2. A future instrumentation design can add a separate completion clock at
   the `observe` return, with an explicit scope of the fields that write
   changed, and with no update on `snapshot()` or on `begin_runtime_session`.
3. That design also has to decide whether a stale or partial LIVE refresh
   may call `observe` at all. This audit does not change that call.
4. Until those facts exist, the owner fragment remains `UNKNOWN` when
   present and `UNAVAILABLE` when absent.

## Acceptance Matrix

| Item | Result |
| --- | --- |
| A01 Producer call graph | PASS |
| A02 PAPER producer analysis | PARTIAL |
| A03 LIVE producer analysis | PARTIAL |
| A04 Evaluation completion point | PARTIAL |
| A05 Producer timestamp candidate | PARTIAL |
| A06 Revision inventory | PASS |
| A07 Invalidation matrix | PARTIAL |
| A08 PAPER as_of semantics | PASS |
| A09 LIVE lastSync semantics | PASS |
| A10 Owner snapshot mapping | PASS |
| A11 Runtime evidence mapping | PASS |
| A12 Freshness option comparison | PASS |
| A13 Recommended policy | PARTIAL |
| A14 Minimum implementation plan | PASS |
| A15 Canonical reconciliation | PASS |
| A16 Security boundary | PASS |
| A17 Authority boundary | PASS |
| A18 No runtime mutation | PASS |
| A19 No production connection | PASS |
| A20 No real orders | PASS |

A08 is PASS because the PAPER clock is identified as the observation wall
clock and is rejected as evaluation completion. A09 is PASS because
`lastSync` is identified as the account refresh clock and is rejected as MM
completion. A02 and A03 stay PARTIAL because risk state is outside this
producer and a partial LIVE refresh can still be observed. A04 and A05 stay
PARTIAL because the safe completion timestamp does not exist yet.
`PRODUCER_TIMESTAMP=UNKNOWN`. A07 stays PARTIAL because configuration, risk
parameters, and position open are not verified invalidations. A13 stays
PARTIAL because the selected policy withholds `CURRENT`.

## Remaining Gaps

- No evaluation-completion timestamp.
- Session begin moves `as_of` and revision without a new equity observation.
- LIVE `lastSync` can advance when only balance or only position succeeded.
- Account `stale` does not remove the MM fragment.
- Risk state, configuration, and a general position-open invalidation are
  UNKNOWN.
- Metrics revision does not cover the loss-limit store or MM configuration.
