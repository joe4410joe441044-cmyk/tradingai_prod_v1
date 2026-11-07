# BB-MM-F1 Money Management Freshness Policy Design

Design only. No freshness policy is implemented. No runtime module was
changed. Production runtime is not connected. The project-spec
`HASH_MISMATCH` is a separate problem and is not used as evidence here.

## Canonical Reconciliation

Comparison base is `30ea89d48b0510de3fe943d34fa04ab2ad4a742c`.
merge-base with origin/main is
`39273a115637edaba42ea49bde732f1ae6436399`.

| Path | Class |
| --- | --- |
| backend/supervisor/snapshot_builder.py | SHARED_PATH_REVIEW_REQUIRED. Not copied |
| backend/supervisor/runtime_snapshot_adapter.py | SHARED_PATH_REVIEW_REQUIRED. Not copied |
| backend/money_management/loss_http_api.py | MAIN_ONLY change. Not copied |
| backend/money_management/loss_execution_integration.py | MAIN_ONLY change. Not copied |
| backend/runtime/cycle_diagnostics.py | MAIN_ONLY change. Not copied |
| backend/bot_manager/owner_snapshot.py | BB publication path on this branch |
| backend/context/runtime_evidence.py | BB reader on this branch |

origin/main has a preview gate that labels metrics `FRESH`, `STALE`, or
`UNKNOWN` by comparing ages with a constructor value
`_maximum_metrics_age`. That gate is not on this branch. Its age value is
not adopted. The provisional 30-second `DEFAULT_FRESHNESS_POLICY` in
`runtime_snapshot_adapter.py` is also not adopted. Its comment says no
shared producer threshold exists.

## Producer Inventory

The held runtime owner is `BotManager.money_management_runtime_metrics`, an
`AuthoritativeLossRuntimeMetricsState` in
`backend/money_management/loss_authoritative_runtime_metrics.py`.
`snapshot()` copies under the state lock. It does not observe again.
`owner_snapshot._held_money_management` reads that copy. It does not
calculate equity, drawdown, or peak.

| Field | Source | Owner | Update | Observation time | Publication | Cache | Side effect of the read |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Equity | `observe` stores `current_equity` | BotManager metrics state | Verified observe paths below | `as_of` of that observe | `equity`. Null stays null | metrics state | Lock copy only |
| Available capital | `available_balance` | same | same | same | `availableCapital` | same | same |
| Exposure | `open_exposure` from the position argument | same | same | same | `exposure` | same | same |
| Drawdown | `current_drawdown_pct` already on the snapshot | same | same | same | `drawdown`. Not recomputed by the reader | same | same |
| Position size | `position_count` | same | same | same | `positionSize` | same | same |
| Revision | increments on observe, session begin, stopped-paper maintenance, and validated peak recovery | same | those writes | the `as_of` passed into that write | `revision` | same | same |
| Peak equity | accumulator inside `observe` and `apply_validated_peak_recovery` | same | those writes | that `as_of` | Not published. Do not synthesize it | same | same |
| Risk state | No field on the held fragment | UNKNOWN | UNKNOWN | UNKNOWN | Absent. Do not invent `riskState` | UNKNOWN | none |
| Capital | No separate held field. Equity is not renamed into capital | UNKNOWN | UNKNOWN | UNKNOWN | Absent | UNKNOWN | none |
| Recovery state | No held field | UNKNOWN | UNKNOWN | UNKNOWN | Absent | UNKNOWN | none |
| MM configuration | Not this metrics object | UNKNOWN for this fragment | UNKNOWN | UNKNOWN | Absent | UNKNOWN | none |
| MM statistics | Daily, weekly, and monthly PnL and trade counts exist on the metrics object | metrics state | close-event path inside `observe` | that `as_of` | Not published | metrics state | none |

Publication time is `publishedAt` on the owner document. It is not `as_of`.

## as_of Semantics

`as_of` is not one producer clock.

| Write | What the code does | Meaning | Producer timestamp |
| --- | --- | --- | --- |
| `AuthoritativeLossRuntimeMetricsState.__init__` | `datetime.now(timezone.utc)` while `source_state` is `NOT_INITIALIZED` | Construction clock | No. The owner reader drops `NOT_INITIALIZED` and `observation_valid` false |
| `begin_runtime_session` | Caller passes `datetime.now(timezone.utc)` at session start | Session-boundary clock | Not an equity observation completion time |
| `observe` from `_observe_money_management_runtime_metrics`, PAPER | `datetime.now(timezone.utc)` after `_capture_account_snapshot()` returns | Wall clock of the observation function | Read clock. Not publication time and not a timestamp stored inside the paper snapshot |
| `observe`, LIVE | `real_account_snapshot.lastSync` when that value is a finite non-negative number, otherwise `datetime.now(timezone.utc)` | Account sync time, or a read clock when sync time is missing | `lastSync` is not MM calculation completion. The fallback is a read clock |
| `observe_stopped_paper_maintenance` | `paper_account_store.observe(..., observed_at=datetime.now(timezone.utc))` | Clock passed into the paper account observation during restore | Not MM calculation completion |
| `apply_validated_peak_recovery` | `as_of = max(previous as_of, caller as_of)` | Later of the stored clock and the recovery caller clock | Not a new market observation |
| `to_runtime_mapping` | Puts the same `as_of` under the key `capturedAt` | Alias for another MM consumer | The owner fragment uses `as_of`, not this alias, as `producerObservedAt` |

An existing `as_of` is therefore not, by itself, a verified MM producer
timestamp. `publishedAt` and a context read clock are not substitutes.

## Update Triggers

| Trigger | Status | Owner | Path | Timestamp write | Cache invalidation | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Trading-cycle callback | VERIFIED | BotManager | `_observe_money_management_runtime_metrics` after the observation-authority check | PAPER wall clock or LIVE `lastSync` / wall clock | Authority check refuses the write after the lifecycle leaves `STARTING` or `RUNNING` | `bot_manager.py` call near the orderbook callback |
| RUNNING baseline | VERIFIED | BotManager | `_handoff_money_management_runtime_baseline` when the snapshot is incomplete | same observe clock | Incomplete fresh snapshot is not dispatched | same module |
| Manual close | VERIFIED | BotManager | `_finalize_manual_close_money_management` | same observe clock | Exception is logged. The previous snapshot remains | same module |
| Emergency operation | VERIFIED | BotManager | emergency path calls the same observe method | same observe clock | No separate MM invalidation flag was found | same module |
| PAPER capital reset | VERIFIED | BotManager | reset publishes the paper snapshot, then observes | PAPER wall clock | No TTL invalidation | same module |
| Stopped PAPER maintenance | VERIFIED | BotManager | `initialize_money_management_runtime_metrics` | paper observation `observed_at` | Refuses a non-PAPER equity authority before mutation | metrics `observe_stopped_paper_maintenance` |
| Session start | VERIFIED | BotManager | `begin_runtime_session` | `datetime.now` at start | New session id. A later observe with another session raises | `bot_manager.py` start path |
| Validated peak recovery | VERIFIED | metrics state | `apply_validated_peak_recovery` | max of the two clocks | Refuses a raise of the peak and an authority mismatch | metrics module |
| Scheduled refresh | NOT_VERIFIED | UNKNOWN | No scheduler was found on these paths | UNKNOWN | UNKNOWN | hypothesis only |
| Configuration change | NOT_VERIFIED | UNKNOWN | No direct observe call was found | UNKNOWN | UNKNOWN | hypothesis only |
| Position open as its own trigger | NOT_VERIFIED | UNKNOWN | Open is not a separate named observe call | UNKNOWN | UNKNOWN | hypothesis only |
| Account sync as an MM write | NOT_VERIFIED as a sync | BotManager observe reads `lastSync` | LIVE observe does not call a sync | uses the stored sync time | `stale is True` changes `source_state` to `UNAVAILABLE` but still calls `observe` | read of an existing snapshot, not a new sync |

`TRADE_CLOSE` is verified when the classifier or the manual-close path sets
that event type. The close then updates period statistics inside `observe`.

## Invalidation

Verified refusals and gates:

- `observation_valid` is false: `_held_money_management` returns no fragment.
- `source_state == NOT_INITIALIZED`: no fragment.
- Session authority mismatch inside `observe`: the write raises.
- A cycle callback that no longer owns `STARTING` or `RUNNING` returns before observe.
- Stopped PAPER maintenance refuses a non-PAPER accounting authority before mutation.
- Peak recovery refuses a higher peak and a different authority.

Not a sufficient invalidation set:

- LIVE `stale is True` changes the observation `source_state` to
  `UNAVAILABLE`, but `observe` still runs. The owner fragment does not copy
  `source_state` or `stale`. A stale account can still publish equity.
- There is no maximum age on the held fragment.
- A newer cycle does not mark the previous document `STALE`. The next
  successful observe replaces the metrics object. A missed update leaves the
  old `as_of` in place with no stale mark.
- `publishedAt` changing does not invalidate `as_of`.

Invalidation coverage is incomplete. That is why a stored MM fragment cannot
become `CURRENT`.

## Status Semantics

`CURRENT` requires all of the following:

1. The producer is the metrics state above, read through `snapshot()`.
2. The timestamp is a verified observation completion time for that equity
   authority. A PAPER wall clock, a LIVE `lastSync`, a session-start clock,
   a construction clock, and a recovery `max` do not qualify today.
3. A freshness policy is stored with the fragment and its limit comes from
   that producer, not from a guessed duration.
4. The observation scope matches the published account authority and session.
   PAPER equity and REAL_LIVE equity stay separate.
5. No verified invalidation applies.
6. Provenance says the value was copied from the held snapshot.

No current observation meets item 2 and item 3. `CURRENT` is not granted.

`STALE` requires a previously valid observation plus either an expired
producer policy or a verified invalidation. A missing policy is not expiry.
The current reader returns `STALE` only when the fragment label is `STALE`
or a real `moneyManagement` policy says the age is past
`maximumAgeSeconds`. This design does not add that label or that number.

`UNKNOWN` is the result when the producer clock is ambiguous, the policy is
absent, the scope is not proven, or invalidation is unknown. The held
fragment with a parsed `as_of` and no `freshnessPolicy` is `UNKNOWN`. A
missing clock on a present fragment is also `UNKNOWN`.

`UNAVAILABLE` is the result when the fragment is absent: metrics missing,
`snapshot()` failing, `observation_valid` false, or `NOT_INITIALIZED`. The
runtime reason remains `NOT_PUBLISHED` or `NOT_IN_OWNER_SNAPSHOT`.

When a case is not clearly `UNAVAILABLE` or `STALE`, the status stays
`UNKNOWN`.

## Null, Zero, and Booleans

The owner copy already preserves null equity and a numeric position count.
This design does not turn `UNKNOWN` into `0` or `false`. Peak equity stays
unpublished. Equity is not inferred from balance. Drawdown is not
recalculated by the context reader.

## Owner Snapshot

`tradingai-owner-snapshot/v1` can stay unchanged.

The `money_management` allowlist already allows `capital`, `equity`,
`availableCapital`, `riskState`, `positionSize`, `exposure`, `drawdown`,
`recoveryState`, and `revision`. The held reader fills only equity,
available capital, exposure, drawdown, position size, revision, and
`producerObservedAt` when `as_of` parses. Missing allowlist names stay
absent. `freshness` becomes `UNKNOWN` because the fragment does not supply
`STALE`, `FRESH`, or `HISTORICAL`.

`freshnessPolicy` is already accepted for `money_management` only, and only
when `source` is `moneyManagement` and the age fields are finite and
non-negative. `_held_money_management` does not set it. No schema change is
required to keep the domain `UNKNOWN`.

A future policy, if a producer later defines one, fits this existing object.
It must not be invented in the reader.

## Runtime Evidence and Answer Path

The reader is `backend/context/runtime_evidence.py`.

```text
held metrics snapshot
    -> owner fragment
    -> tradingai-owner-snapshot/v1
    -> collect_runtime_evidence
    -> shared operator context
    -> Advisor prompt and Supervisor canonical context
```

Judgement belongs to the reader, and only from fields the owner already
stored. The reader does not call `observe`, does not sync an account, and
does not evaluate risk. `datetime.now` inside `_policy_status` runs only
after a `moneyManagement` policy is present. With no policy, a parsed
timestamp stays `UNKNOWN`.

Advisor and Supervisor already receive that `UNKNOWN` domain through the
shared operator context. No new reader and no new response field are
required. `UNKNOWN` is not rewritten to `CURRENT` on either path.

Other domains are not promoted because MM is `CURRENT`. An MM risk value is
not live-order permission. A supervisor recommendation is not MM authority.
Execution authority, the live account, the paper account, position,
supervisor runtime, and market selection keep their own clocks and policies.

## Security

This design does not run MM calculation, risk evaluation, account sync, or
an order. It does not change emergency stop, position, or execution
authority. Operator publication remains behind the existing operator
session. `build_public_context_view` does not copy runtime evidence. The
held fragment does not add secrets. Peak equity and account identifiers stay
out of the published MM fragment.

## Options

| Option | Cost | Producer reliability | Invalidation coverage | False CURRENT risk | Side effect | Schema | Testability | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. Time TTL | Small reader change | Low. No verified period | A TTL would hide missing events | High if 30s, 60s, or 5m is guessed | Reader clock only | Existing policy object | Easy and misleading | Rejected |
| B. Event invalidation | Medium | Medium for the verified gates | Incomplete for stale LIVE publication and missed cycles | High if the latest observe is called CURRENT | None if read-only | May need an invalidation field | Needs event fixtures | Not sufficient alone |
| C. Version validity | Medium | Revision and session id are real | A new revision does not prove the account is fresh | High if latest revision means CURRENT | None | Revision already exists | Easy | Not sufficient alone |
| D. Hybrid time, event, and version | High | Requires one verified clock and a complete invalidation list | Not available yet | High until both parts exist | None if read-only | Existing policy object might be enough later | Blocked by missing evidence | Deferred |
| E. Remain UNKNOWN until verified | None now | Honest about the split clocks | Does not claim coverage that is absent | Low. CURRENT is withheld | None | None | Current tests already expect UNKNOWN | Selected |

## Recommended Policy

`OPTION_E`.

Do not add a TTL. Do not mark the held MM fragment `CURRENT`. Keep
`producerObservedAt` equal to `as_of` only as a copied clock, with status
`UNKNOWN`. Keep an absent fragment `UNAVAILABLE`. Do not copy origin/main's
preview age and do not adopt the provisional 30-second supervisor policy.

## Minimum Implementation Plan

Not implemented here.

1. Leave `_held_money_management` without `freshnessPolicy`.
2. Leave `runtime_evidence._judge` unchanged. No policy means `UNKNOWN`.
3. Do not edit the metrics accumulator, BotManager observe path, snapshot
   builder, or runtime snapshot adapter.
4. A later evidence task should split the PAPER wall clock, LIVE `lastSync`,
   the missing-sync fallback, and the session-start clock before any
   `CURRENT` rule is proposed again.
5. Rollback of this design is to keep the current reader. No schema change
   has to be undone.

## Regression Test Plan

Not executed. This task is read-only.

When a later change attaches a policy or changes the MM fragment, re-run the
BB6H2 suite and the owner-cache tests that expect MM `UNKNOWN`, null equity
preserved, position size `0` preserved, and no `CURRENT` without a stored
policy. Also assert that a stale LIVE account is not published as `CURRENT`,
and that PAPER and REAL_LIVE peaks are not mixed.

## Acceptance Matrix

| Item | Result |
| --- | --- |
| A01 Producer inventory | PASS |
| A02 as_of source identified | PARTIAL |
| A03 Producer versus read clock | PARTIAL |
| A04 Update trigger inventory | PASS |
| A05 Invalidation inventory | PARTIAL |
| A06 CURRENT definition | PASS |
| A07 STALE definition | PASS |
| A08 UNKNOWN definition | PASS |
| A09 UNAVAILABLE definition | PASS |
| A10 Null preservation | PASS |
| A11 Peak equity not synthesized | PASS |
| A12 Owner snapshot mapping | PARTIAL |
| A13 Runtime evidence mapping | PASS |
| A14 Advisor context mapping | PASS |
| A15 Supervisor context mapping | PASS |
| A16 Authority boundary | PASS |
| A17 Operator authentication | PASS |
| A18 Public view isolation | PASS |
| A19 Canonical reconciliation | PASS |
| A20 Option comparison | PASS |
| A21 Recommended policy | PARTIAL |
| A22 Minimal implementation plan | PASS |
| A23 Regression test plan | PASS |
| A24 No production mutation | PASS |

A02 and A03 are partial because `as_of` has several verified meanings and
the PAPER path is a read clock. A05 is partial because a stale LIVE account
can still be published. A12 is partial because risk, capital, recovery, peak,
configuration, and statistics are not on the held fragment. A21 is partial
because the selected policy is to withhold `CURRENT`, not a positive age
rule. A23 records a future test plan. Tests were not run.

## Remaining Gaps

- No single verified MM observation-completion clock.
- No producer-owned freshness limit.
- LIVE staleness does not remove the held fragment.
- Risk state, recovery state, capital, peak equity, configuration, and
  statistics are not part of the published runtime fragment.
- origin/main's preview freshness gate is a shared-path difference and stays
  out of this design.
