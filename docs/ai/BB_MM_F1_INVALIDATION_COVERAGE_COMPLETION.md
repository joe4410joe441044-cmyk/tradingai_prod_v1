# BB-MM-F1.7 MM Invalidation Coverage

TASK_ID=TRADINGAI-WORK-BB-MM-F1-INVALIDATION-COVERAGE-COMPLETION-1

VERDICT=BB_MM_F1_INVALIDATION_COVERAGE_PARTIAL

CANONICAL_HEAD=f344864344b0b99a598f674b3e2e4a367bc9fb25
ORIGIN_MAIN=f344864344b0b99a598f674b3e2e4a367bc9fb25

BASE_COMMIT=3e42ca647ae9987f41bd8fe6706e38dcfa52c132

WORKTREE=/home/joe4410joe/tradingai_prod_v1.worktrees/ai-mm-invalidation-coverage
BRANCH=audit/ai-mm-invalidation-coverage

HEAD_BEFORE=3e42ca647ae9987f41bd8fe6706e38dcfa52c132
HEAD_AFTER=the docs-only commit that adds this file

Read-only audit of the worktree. No runtime code, test, account sync, mode
switch, risk change, or order was run. Canonical main was not modified.
`PROJECT_SPEC` `HASH_MISMATCH` stays a separate gap.

`EVALUATION_COMPLETION=NOT_AVAILABLE`. This fragment is
`BotManager.money_management_runtime_metrics`. It is not an MM risk
evaluation.

## CANONICAL_RECONCILIATION

merge-base HEAD origin/main = `39273a115637edaba42ea49bde732f1ae6436399`

No file was edited on both sides after that merge-base. There is no
content conflict to merge. No merge and no cherry-pick.

| Path | Class |
| --- | --- |
| `backend/bot_manager/bot_manager.py` | BB_ONLY since the merge-base. This audit uses this file |
| `backend/bot_manager/owner_snapshot.py` | BB_ONLY. Publisher of the held fragment |
| `backend/context/**` | BB_ONLY. Read-only evidence mapping |
| `backend/supervisor/held_evaluation_cache.py` and the BB supervisor edits | BB_ONLY. Not an MM input |
| `Bot/engine/execution_engine.py` | MAIN_ONLY. Quantity-projection delta. Not copied. Position conclusions below use this worktree |
| `backend/api/money_management.py` | MAIN_ONLY. Not copied |
| `backend/money_management/loss_http_api.py` | MAIN_ONLY preview and age logic. Not copied. This worktree's configuration revision and peak recovery were read here |
| `backend/money_management/loss_execution_integration.py` | MAIN_ONLY. Not copied |
| `backend/runtime/cycle_diagnostics.py` | MAIN_ONLY. Not copied |
| `backend/supervisor/snapshot_builder.py` | MAIN_ONLY. Not copied |
| `backend/supervisor/runtime_snapshot_adapter.py` | MAIN_ONLY. Not copied |

`backend/bot_manager/`, the metrics producer, and the context reader are
readable on this branch. The main-only engine delta does not block the
dependency map. It must be reviewed again before any later implementation
is merged toward main.

## MM_FRAGMENT_DEPENDENCY_MAP

Owner publication is `_held_money_management`. It copies `snapshot()` only
when `observation_valid` is true and `source_state` is not
`NOT_INITIALIZED`. It does not read `_observed` or `is_complete`.

| Fragment field | Class | Source | Owner | Read | Update | Revision | Timestamp |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `equity` | DIRECT_DEPENDENCY | PAPER `balance + unrealized_pnl`. LIVE `real_account_snapshot.equity` | engine or account cache | `_capture_account_snapshot` or cache copy inside `_observe_money_management_runtime_metrics` | `observe` / stopped PAPER observe | metrics `_revision` | PAPER wall clock after capture. LIVE `lastSync`, else wall clock |
| `availableCapital` | DIRECT_DEPENDENCY | PAPER `balance`. LIVE `availableBalance` | same | same | same | same | same |
| `exposure` | DIRECT_DEPENDENCY | `_position_metrics` from the position argument | PAPER `engine.actual_position`. LIVE cache `positions` | same observe | same | same | same |
| `positionSize` | DIRECT_DEPENDENCY | position count from that same argument. This is not a sizing parameter | same | same | same | same | same |
| `drawdown` | INDIRECT_DEPENDENCY | `(peak - equity) / peak` inside `_snapshot_locked` | metrics accumulator | `snapshot()` | peak rules inside observe, restore, or `apply_validated_peak_recovery` | same revision | observe `as_of`, or the recovery `as_of` |
| `revision` | DIRECT_DEPENDENCY | metrics `_revision` | `AuthoritativeLossRuntimeMetricsState` | `snapshot()` | observe, stopped observe, `begin_runtime_session`, `restore`, peak recovery | itself | not a clock |
| `producerObservedAt` | INDIRECT_DEPENDENCY | copy of metrics `as_of` | publisher | `_held_money_management` | any writer of `_as_of`, including session start and peak recovery | published with the current revision | `as_of`, which is not an observation-completion clock |

Also stored on the metrics object, and not copied by the owner fragment:
balance, realized and unrealized PnL, peak, position side, current risk
amount, period PnL, and trade counts. Current risk amount is derived from
position entry and stop. It is not an owner-fragment field.

| Candidate input | Class | Reason |
| --- | --- | --- |
| `engine.mode` | INDIRECT_DEPENDENCY | selects the PAPER capture or the LIVE cache. It is not stored on the fragment |
| `engine.latest_price` | DIRECT_DEPENDENCY | `mark_price` for exposure. PAPER equity uses `unrealized_pnl`, which `on_price` updates from this price before the cycle observe |
| `engine.peak_equity` | INDIRECT_DEPENDENCY | PAPER peak candidate only. LIVE passes none |
| `real_account_snapshot` balance and position sources, `stale`, `authenticated` | DIRECT_DEPENDENCY | LIVE observe reads this cache and does not sync |
| close event id | DIRECT_DEPENDENCY | only when the caller passes event type `TRADE_CLOSE`. It updates period stats. It does not replace the position argument |
| risk percent, stop percent, take-profit percent, leverage, max drawdown percent | NOT_A_DEPENDENCY | `observe` does not read them. They can affect a later entry quantity. They do not change the current fragment by themselves |
| loss HTTP `configuration_revision` | NOT_A_DEPENDENCY | not read by `observe`. Not a global MM revision |
| strategy `configuredRevision` | NOT_A_DEPENDENCY | not read by `observe` |
| loss-runtime `risk_state` | NOT_A_DEPENDENCY | a different object. The owner fragment does not copy `riskState` |
| `config.TRADE_MODE` and governance mode | NOT_A_DEPENDENCY | the producer branch uses `engine.mode` |
| `set_position_state` | NOT_A_DEPENDENCY | no production caller |

## POSITION_INVALIDATION

PAPER `observe` reads `engine.actual_position` through
`_capture_account_snapshot`. LIVE `observe` reads
`real_account_snapshot["positions"]` and does not read
`engine.actual_position`.

The trading-cycle callback in `on_update` does three things in order:
strategy `process_runtime` (this can `submit_signal` / `try_entry`),
`engine.on_price` (unrealized PnL, trailing stop, SL/TP/strategy close),
then `_observe_money_management_runtime_metrics` while lifecycle authority
is still `STARTING` or `RUNNING`. That observe runs even when the
before/after classifier returns none.

| EVENT | SOURCE_FUNCTION | AFFECTED_MM_FIELDS | EXISTING_REVISION | INVALIDATION_SIGNAL | EVIDENCE |
| --- | --- | --- | --- | --- | --- |
| PAPER auto entry | `ExecutionRuntime.handoff_adapter_output` then `try_entry`, before the cycle observe | PAPER equity, available capital, exposure, position count, drawdown | next cycle `observe` increments metrics revision | no signal at `try_entry`. The same callback re-reads the engine | VERIFIED for that callback order |
| PAPER auto exit | `on_price` calls `close_position`, then the cycle observe | same, plus period stats only if the classifier says `TRADE_CLOSE` | same | same | VERIFIED |
| PAPER position update | `on_price` updates unrealized PnL and may update `sl`, then the cycle observe | equity and drawdown. Exposure changes when mark or quantity changes. Stop-only risk amount is not an owner field | same | same | VERIFIED |
| PAPER manual entry | `_manual_entry_locked` calls `try_entry` and returns. It does not call observe | engine position and balance change immediately. The published fragment stays on the previous snapshot until the next authorized cycle observe | none at the mutation | none until that later observe | PARTIAL. Manual entry requires `RUNNING`, so a later cycle is the normal detector. The gap has no signal |
| PAPER manual close | `_manual_close_locked` then `_finalize_manual_close_money_management` | PAPER fields, and `TRADE_CLOSE` period stats when the classifier does not already return a type | observe increments revision | the close calls observe. There is no separate invalidation timestamp | VERIFIED |
| PAPER emergency flatten | `flatten_paper_position` then observe in the paper branch of the emergency path | same | same | same | VERIFIED |
| LIVE open | `try_entry` assigns `actual_position` from `exchange.get_positions`. It does not write `real_account_snapshot` and does not call observe | owner fragment unchanged until a later observe copies the cache | none on the order | the engine position is not the LIVE fragment input | MISSING for the fragment |
| LIVE update | engine `on_price` can change local unrealized PnL and stop. LIVE observe ignores those engine fields | fragment changes only when the cache equity or `positions` change and a later observe runs | account generation on refresh commit. Not metrics revision | cache refresh is not an MM observe | MISSING at the engine mutation |
| LIVE close | manual close still calls observe. LIVE emergency flatten does not | the manual observe copies the existing cache. It can republish the pre-close positions | manual observe increments revision even when the cache is old | revision moves. The new snapshot is not proof of the close | PARTIAL |
| `set_position_state` | no caller | none | none | none | NOT_APPLICABLE |

No position revision exists on this producer.

## MODE_SWITCH_INVALIDATION

Three mode authorities exist. They are not the same value.

| Authority | Where | Effect on this fragment |
| --- | --- | --- |
| Selected / process mode | `POST /set_mode` writes `config.TRADE_MODE` and `ALLOW_LIVE` | `observe` does not read it |
| Governance mode | `POST /api/governance/mode` | not read by `observe` |
| Runtime / producer mode | `ExecutionEngine` sets `self.mode` from `dry_run` during engine start | this is the branch selector |

`/set_mode` does not change `engine.mode`, does not clear the metrics
object, and does not call observe. An in-process PAPER/LIVE flag change
does not mix the two account reads inside one observe. It also does not
invalidate the already published numbers. The fragment has no mode field,
so a reader cannot see which branch produced them.

`BotManager.start` stops the previous runtime, increments `session_id`,
calls `begin_runtime_session`, then constructs a new engine.
`begin_runtime_session` sets `_observed` false, writes a new `as_of`, and
increments `_revision`. It does not clear equity, exposure, position count,
`observation_valid`, or `source_state`. The owner publisher ignores
`_observed`. After a mode-changing start, the old mode's equity can remain
publishable under the new `as_of` until a later observe replaces it.

| EVENT | RESULT |
| --- | --- |
| PAPER to LIVE, or LIVE to PAPER, through `/set_mode` only | MISSING_INVALIDATION. Producer input is unchanged because `engine.mode` is unchanged |
| Mode change through `start` | revision and `as_of` move without a new account observation. Old equity can remain. MISSING mode clear |
| Cache reuse | LIVE observe reuses `real_account_snapshot` until something else calls `_get_real_account_snapshot`. That call is in account runtime builders, not in observe |

No mode was switched in this audit.

## RISK_PARAMETER_INVALIDATION

`observe` does not read MM risk parameters, risk limits, position-sizing
parameters, drawdown limits, or recovery parameters.

| Change | API / store | Runtime effect found | Fragment dependency | Revision | Snapshot |
| --- | --- | --- | --- | --- | --- |
| Loss configuration, including maximum drawdown percent | loss HTTP configuration update | saves configuration and increments `configuration_revision` | NOT_A_DEPENDENCY | configuration revision only | no MM observe |
| Strategy risk percent, stops, size | settings service `configuredRevision` | next entry can size differently | NOT_A_DEPENDENCY for the current fragment | strategy revision | no MM observe |
| Governance risk profile | governance route | governance state only | NOT_A_DEPENDENCY | none on this fragment | none |

A later entry or trailing update can change the position that a future
observe reads. That is a position event, not a reason to invalidate on the
parameter write. MM risk evaluation remains a different object. This audit
does not require invalidation for these parameters. No parameter was
changed.

## CONFIGURATION_INVALIDATION

| Revision | What it covers | Used by `observe` |
| --- | --- | --- |
| metrics `_revision` | one metrics write, including session start, restore, and peak recovery | yes, as its own counter. Not global MM CURRENT |
| loss HTTP `configuration_revision` | loss configuration document | no |
| strategy `configuredRevision` | strategy parameter set | no |
| account `generation` | which refresh commit may land | no. LIVE observe does not compare it |

Configuration changes are not invalidation candidates for this fragment.
`configuration_revision` must not be used as the fragment's global revision.
No configuration was changed.

## ACCOUNT_EQUITY_INVALIDATION

PAPER equity is `engine.balance + engine.unrealized_pnl`, captured inside
observe. A running cycle updates unrealized PnL in `on_price` and then
observes. Paper capital reset writes the engine balance and then observes.
Those two paths re-observe the PAPER account.

LIVE equity and positions come from `real_account_snapshot`.
`_refresh_real_account_snapshot` is the cache writer.
`authenticated = balance_ok or position_ok`. `lastSync` becomes the new
clock when either side succeeds. `stale` is true only when a side failed
and a previous `lastSync` exists. A failed side keeps the previous value
only on that stale path. Otherwise the failed side becomes null.
`lastSync` advancing is not `FULL_SYNC_SUCCESS`.

| LIVE result | `balanceSource` | `positionSource` | `lastSync` | `stale` | Fragment |
| --- | --- | --- | --- | --- | --- |
| Balance only | `KUCOIN_FUTURES_READ_ONLY` | absent | advances | true when an older sync exists | not a complete input. A later observe can still copy the mixed cache and increment metrics revision |
| Position only | absent | `KUCOIN_FUTURES_READ_ONLY` | advances | same | same |
| Both succeeded | set | set | advances | false | complete account input only after a later observe copies it. Refresh itself does not observe |
| Both failed | absent | absent | previous clock kept | true when an older sync exists | no new account fact. The old cache remains |

Refresh callers found: `_build_account_runtime` and the canonical account
status path. The order paths and `observe` do not call refresh. No account
sync was run.

## SESSION_RESTORE_RECOVERY

| EVENT | Metrics revision | `as_of` | New equity observation | Account snapshot | Fragment regeneration | Owner publication |
| --- | --- | --- | --- | --- | --- | --- |
| Session start `begin_runtime_session` | +1, including when equity is unchanged | replaced with the session clock | no. `_observed` becomes false. Equity and `observation_valid` stay | not updated here | no. The old snapshot fields remain | a later `snapshot()` can still publish them because the publisher does not check `_observed` |
| Session restore `restore` | +1 on the first restore | restore clock | no. `_observation_valid` stays false until a later observe | peak comes from persisted high-water mark | snapshot exists, owner omits it while `observation_valid` is false | omitted until a valid observe |
| Stopped PAPER maintenance | +1 inside `observe_stopped_paper_maintenance` | caller observation time | yes, from the paper account store | that store observation | yes | publishable when `observation_valid` is true |
| Peak recovery `apply_validated_peak_recovery` | +1 | `max(old as_of, recovery time)` | no. Peak may fall. Equity argument is a guard, not a new account read | loss HTTP calls this after a persisted recovery | peak and drawdown can change. Position and balance do not | publisher can show the new `as_of` without a new account observation |
| Bot restart | new object starts at revision 0 | constructor clock | no until observe or restore | new `BotManager` | no carried in-memory clock | unpublished until a valid snapshot |

Session start and peak recovery are not new MM observations. This audit
does not create a producer timestamp for them.

## INVALIDATION_SIGNAL_MATRIX

| EVENT | AFFECTED_FIELDS | PRODUCER_OWNER | ACTUAL_MUTATION_POINT | EXISTING_SIGNAL | REVISION_SIGNAL | TIMESTAMP_SIGNAL | SNAPSHOT_SIGNAL | DETECTION_COVERAGE | RECOMMENDED_HANDLING |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PAPER cycle entry, exit, price update | equity, exposure, position count, drawdown | metrics state | `try_entry` / `on_price` / `close_position`, then cycle observe | the following observe | metrics +1 | new PAPER `as_of` | next owner publication copies `snapshot()` | VERIFIED | REOBSERVE |
| PAPER manual entry | same, after the next cycle | metrics state | `_manual_entry_locked` | none at the mutation | none until the next cycle observe | none until then | old fragment remains | PARTIAL | KEEP_UNKNOWN across the gap |
| PAPER manual close and paper emergency flatten | same | metrics state | close finalizer or emergency paper branch | observe in that function | metrics +1 | new PAPER `as_of` | publication on the next owner write | VERIFIED | REOBSERVE |
| LIVE engine open, update, or emergency flatten | engine position only | account cache, not the engine | `try_entry`, `on_price`, live emergency | engine mutation is not a fragment input | none | none | cache unchanged | MISSING | KEEP_UNKNOWN |
| LIVE manual close | cache fields, which may still be pre-close | metrics state | `_finalize_manual_close_money_management` | observe reads the cache | metrics +1 | `lastSync` or wall clock | can publish the old positions under a new revision | PARTIAL | KEEP_UNKNOWN |
| LIVE refresh, four results | cache equity and positions | account cache | `_refresh_real_account_snapshot` | `balanceSource`, `positionSource`, `stale`, `authenticated` | account generation, not metrics revision | `lastSync` on any one-side success | MM fragment unchanged until observe | VERIFIED for the cache. PARTIAL for the fragment | REOBSERVE only after both sources succeed. Otherwise KEEP_UNKNOWN |
| `/set_mode` without a new engine | none | none | `config.TRADE_MODE` | none | none | none | old fragment remains | MISSING | NO_ACTION_REQUIRED for the numbers. KEEP_UNKNOWN for mode identity |
| `start` into another mode | old equity remains | metrics state | `begin_runtime_session` | `_observed` false, which the publisher ignores | metrics +1 | new `as_of` without a new account read | old numbers can be republished | PARTIAL | KEEP_UNKNOWN |
| Risk parameter or MM configuration write | none on this fragment | loss HTTP or strategy settings | configuration save | configuration or strategy revision | not metrics revision | none | no MM re-publication from the write | NOT_APPLICABLE | NO_ACTION_REQUIRED |
| PAPER capital reset | paper account fields | metrics state | reset then observe | observe | metrics +1 | new PAPER `as_of` | publication from the reset path | VERIFIED | REOBSERVE |
| Session restore | peak and period values | metrics state | `restore` | `observation_valid` remains false | metrics +1 | restore `as_of` | owner omits the fragment | VERIFIED | NO_ACTION_REQUIRED until a valid observe |
| Peak recovery | peak and drawdown | metrics state | `apply_validated_peak_recovery` | revision and `as_of` | metrics +1 | recovery clock | publication can move `producerObservedAt` | PARTIAL | KEEP_UNKNOWN. Not a new observation |
| Restart | new unpublished object | new metrics state | `BotManager` constructor | revision 0 | none carried | none carried | unpublished | VERIFIED | NO_ACTION_REQUIRED |

`INVALIDATE` is not selected for any row. The rows that need a future clear
do not have a producer-owned invalidation timestamp today. Treating revision
or `as_of` as that clear would mark session start and peak recovery as fresh
observations.

## MINIMUM_IMPLEMENTATION_PLAN

`mmObservationCompletedAt` stays the selected clock. It is still the time
after a qualifying `observe` or stopped PAPER observe returns. It is not
written for session start, restore, peak recovery, a failed capture, an
invalid observation, or a LIVE snapshot that is not both-source,
authenticated, and not stale.

Not added in the minimum set:

| Candidate | Decision |
| --- | --- |
| `mmObservationRevision` | not a second counter. The previous `evidenceRevision` is the metrics revision stored beside the clock |
| `mmObservationMode` | not a separate field. `inputScope` `PAPER_ENGINE_ACCOUNT` or `LIVE_ACCOUNT_CACHE` is the mode scope |
| `mmObservationInputScope` | already represented by that `inputScope` |
| `mmObservationInvalidatedAt` | not added. No safe producer write exists for the LIVE cache gap or the manual-entry gap |
| `mmObservationInvalidationReason` | not added. A reason without a detected event would be a false clear |

Minimum later change, not done here:

| Target | Write | Read | Fields | Failure | Invalidation |
| --- | --- | --- | --- | --- | --- |
| `loss_authoritative_runtime_metrics.py` | note after a qualifying return | locked snapshot | `observationCompletedAt`, `inputCompleteness`, `inputScope`, `evidenceRevision` | skip the note | session start, restore, and peak recovery do not note |
| `bot_manager.py` observe caller | after observe returns | capture identity and LIVE source fields | calls the note | partial LIVE, same paper object, or invalid observation: no note | does not add an account sync |
| stopped PAPER caller | after that observe returns | returned snapshot | calls the note | invalid: no note | same |
| `owner_snapshot.py` allowlist | copy | `snapshot()` | those four names only when `evidenceRevision` equals `revision` | omit them | no `freshnessPolicy` |

Schema version stays `tradingai-owner-snapshot/v1`. The money-management
allowlist currently keeps `capital`, `equity`, `availableCapital`,
`riskState`, `positionSize`, `exposure`, `drawdown`, `recoveryState`, and
`revision`, plus the shared `producerObservedAt`, `freshness`, and
`freshnessPolicy` names. The four evidence names are dropped until that
allowlist grows. Impact of a later allowlist change: operator runtime can
show the clock and the scope. Public view still does not receive operator
runtime evidence. No status becomes `CURRENT`. The reader still does not
calculate MM values, sync an account, or change authority.

`producerObservedAt` continues to copy `as_of`. That copy remains unsafe as
a completion clock because session start and peak recovery move `as_of`.

## STATUS MAPPING

Existing `runtime_evidence._judge` is unchanged.

| Condition | Status |
| --- | --- |
| Fragment absent | `UNAVAILABLE` |
| Fragment present, including a future success clock, while no money-management freshness policy exists | `UNKNOWN` |
| Explicit `freshness=STALE`, or a future policy age | `STALE` only under that existing contract |
| `CURRENT` | not granted. `CURRENT_VERIFIED=NO` |

This audit does not promote the incomplete position and mode gaps to
`STALE`. There is no explicit invalidation label to copy. A producer
timestamp does not make the domain `CURRENT`.

## READINESS

OBSERVATION_INSTRUMENTATION_READY=YES

The qualifying return, the PAPER object-identity check, and the LIVE
both-source check are identified. The note can be stored by the metrics
owner without an MM recalculation, an account sync, or an authority write.
The note must not be treated as proof that later inputs are unchanged.

INVALIDATION_INSTRUMENTATION_READY=NO

PAPER manual entry has no signal until a later cycle. LIVE engine position
changes are not fragment inputs. LIVE manual close can observe a stale
cache. Mode has no fragment field and no clear on `start`. Session start
and peak recovery move revision and `as_of` without a new observation.

FRESHNESS_POLICY_READY=NO

`CURRENT` and `STALE` cannot be assigned from this evidence. Option E
remains: stay `UNKNOWN`. No TTL is selected. The account intervals and the
main-only preview age are not reused.

## TEST_PLAN

NOT_RUN. These checks are for the later observation note. They are not
implemented here.

| Test | Proves |
| --- | --- |
| T01 | PAPER capture replacement plus valid observe notes the clock |
| T02 | PAPER capture exception or invalid observe does not note it |
| T03 | LIVE both sources, authenticated, not stale, notes `COMPLETE` |
| T04 | Balance-only does not note and is not full success |
| T05 | Position-only does not note and is not full success |
| T06 | Both failed does not note |
| T07 | PAPER position open on the cycle is visible to the observe that follows `try_entry` in that callback |
| T08 | PAPER `on_price` unrealized or stop update is visible to the following observe |
| T09 | PAPER `close_position` inside `on_price` is visible to the following observe |
| T10 | PAPER manual entry does not observe inside `_manual_entry_locked` |
| T11 | PAPER manual close does observe inside the close finalizer |
| T12 | `/set_mode` does not change `engine.mode` and does not observe |
| T13 | Risk-parameter and configuration writes do not call observe and do not change this fragment |
| T14 | Configuration revision is not this fragment revision |
| T15 | LIVE refresh without observe leaves the metrics revision unchanged |
| T16 | Session start increments revision and `as_of` with the previous equity |
| T17 | Restore does not make `observation_valid` true |
| T18 | Peak recovery increments revision without a new account read |
| T19 | A later observe that does not note the clock leaves `evidenceRevision` unmatched |
| T20 | Missing producer completion clock stays absent |
| T21 | Missing fragment stays `UNAVAILABLE` |
| T22 | No path returns `CURRENT` |
| T23 | Owner publication copies the four names only on revision match |
| T24 | Runtime evidence stays `UNKNOWN` without a money-management policy |
| T25 | Advisor context does not turn the clock into authority |
| T26 | Supervisor context does not turn the clock into authority |
| T27 | Operator authentication still gates the operator context |
| T28 | Public view does not receive the operator MM evidence |
| T29 | The reader does not sync an account |
| T30 | No order path is called |

## ACCEPTANCE_MATRIX

| Item | Result |
| --- | --- |
| A01 MM Fragment Dependency Map | PASS |
| A02 Position Open Coverage | PARTIAL |
| A03 Position Update Coverage | PARTIAL |
| A04 Position Close Coverage | PARTIAL |
| A05 Mode Switch Coverage | PARTIAL |
| A06 Risk Parameter Coverage | PASS |
| A07 Configuration Coverage | PASS |
| A08 Account / Equity Coverage | PARTIAL |
| A09 LIVE Partial Sync Coverage | PASS |
| A10 Session / Restore Coverage | PARTIAL |
| A11 Peak Recovery Coverage | PARTIAL |
| A12 Revision Signal Coverage | PARTIAL |
| A13 Timestamp Signal Coverage | PARTIAL |
| A14 Snapshot Publication Coverage | PASS |
| A15 Invalidation Matrix | PASS |
| A16 Minimum Instrumentation Design | PASS |
| A17 Observation Readiness | PASS |
| A18 Invalidation Readiness | PARTIAL |
| A19 Freshness Policy Readiness | PARTIAL |
| A20 Canonical Reconciliation | PASS |
| A21 Authority Boundary | PASS |
| A22 Security Boundary | PASS |
| A23 No Runtime Mutation | PASS |
| A24 No Production Connection | PASS |
| A25 No Real Orders | PASS |

A02, A03, and A04 are PARTIAL because the LIVE cache is not tied to the
engine position mutation. A05, A10, A11, A12, and A13 are PARTIAL because
revision and `as_of` move without a new observation, and mode is unlabeled.
A18 and A19 are PARTIAL because those readiness answers are NO. They are
not PASS.

## TEST_RESULTS

NOT_RUN_READ_ONLY

## CHANGED_FILES

- docs/ai/BB_MM_F1_INVALIDATION_COVERAGE_COMPLETION.md

## COMMIT

Docs-only commit on this branch.

Message: `work-bb: audit mm runtime invalidation coverage`

## REMAINING_GAPS

- PAPER manual entry does not invalidate or re-observe at the mutation.
- LIVE engine position open, update, and emergency flatten do not update the cache that `observe` reads.
- LIVE manual close observes the cache, not the close result.
- The fragment has no mode, and `start` can keep the previous equity under a new `as_of`.
- Session start and peak recovery are not new observations.
- `configuration_revision` does not cover this fragment.
- `CURRENT` remains unavailable.
- Main-only `execution_engine.py` and loss HTTP preview changes were not adopted.

## BLOCK_REASON

NONE

## DEPENDENCY

The observation note can be implemented while status stays `UNKNOWN`.
Invalidation of LIVE cache lag, manual entry, and mode identity is a
separate gap and is not closed by that note.

## RESUME_CONDITION

Resume only in a new task. Do not start the next task from this audit.
Do not promote freshness.

## NEXT_RECOMMENDED_TASK

BB_MM_F1_OBSERVATION_INSTRUMENTATION_IMPLEMENTATION

`OBSERVATION_INSTRUMENTATION_READY=YES` and
`INVALIDATION_INSTRUMENTATION_READY=NO`. The next implementation may add
only the completion clock and its revision, scope, and completeness.
`CURRENT` stays `UNKNOWN`. Freshness policy implementation is not next.
The next task was not started.
