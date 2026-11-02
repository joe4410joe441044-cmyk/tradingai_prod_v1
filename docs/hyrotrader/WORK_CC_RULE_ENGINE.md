# Work CC synthetic PROP rule engine and provenance foundation

## Scope and authority boundary

The CC-3A engine is a pure, offline calculation component. It accepts immutable account identity, the existing v1 rule definition and observation DTOs, an explicit daily baseline, an explicit evaluation time, and an explicit policy. It does not read a clock, file, registry, credential, API, runtime, UI, Money Management state, or Bollinger Band context. Its `entry_allowed` value means only compatibility of an explicitly configured non-empty risk-gate set for the supplied inputs; every evaluation carries `RULE_COMPATIBILITY_ONLY_NO_EXECUTION_AUTHORITY` and grants no execution authority. Profit target is never an entry gate. Empty and target-only ENTRY policies produce UNKNOWN with `ENTRY_RISK_GATE_SET_MISSING`.

No HyroTrader operational profile is activated. The legacy `VERIFIED_OFFICIAL` Engine path now always returns `ACCOUNT_RULES_SNAPSHOT_REQUIRED`; a generic verified enum cannot create an operational result. Account verification, active selection, runtime authority, and calculation remain separate.

## Supported synthetic formulas

All money and percentages are finite `Decimal` values. Percent fields use 0–100 units. Engine calculation v2 accepts at most 64 significant digits with adjusted exponent from -128 through 128. Accepted arithmetic runs inside a local 384-digit context with traps for rounding, inexact arithmetic, overflow, division by zero, and invalid operations. The caller's precision, rounding, traps, and sticky flags are not modified. Financial boundary comparison uses the unrounded calculation value; no display quantization occurs. Out-of-contract inputs and arithmetic failures become UNKNOWN, never PASS.

- Static maximum loss: `limit = initial_balance × maximum_loss_limit_pct / 100`; `floor = initial_balance − limit`; compare the policy-selected current balance or equity with the floor.
- Daily loss: `limit = initial_balance × daily_loss_limit_pct / 100`; `floor = explicit_daily_baseline.reference_value − limit`; compare the policy-selected current value with the floor.
- Profit target: `target = initial_balance × profit_target_pct / 100`; `progress = policy-selected current value − initial_balance`.

`BREACH_BELOW` and `BREACH_AT_OR_BELOW` are explicit policies because a rule name alone does not establish an equality boundary. `INCREASES_HEADROOM` preserves signed loss used, so profit increases headroom; `LOSS_USED_FLOOR_ZERO` clamps loss used at zero. Calculation and display rounding are separate; the engine does not round.

Profit target not reached is `NOT_APPLICABLE` with `TARGET_NOT_REACHED`, not a loss-rule breach. Target reached is a progress result only and does not authorize entry or certify challenge completion.

## Daily baseline and time boundary

`DailyBaseline` v1 records account, rule-set id/revision, trading day, IANA timezone, local boundary time, effective time, value basis, Decimal reference value, currency, source, and verification status. It is supplied by the caller; there is no baseline store. The engine rejects cross-account, cross-version, cross-currency, basis/timezone mismatch, previous-day, unverified, and future baselines as `UNKNOWN`. Crossing a day boundary never creates a baseline from the current observation.

Trading-day calculation uses the supplied timezone-aware evaluation time and `zoneinfo`. DailyBaseline v1 has no fold field, so an ambiguous local reset is rejected as `BASELINE_BOUNDARY_AMBIGUOUS`; a nonexistent reset is rejected as `BASELINE_BOUNDARY_NONEXISTENT`. The new Baseline Source contract requires fold 0 or 1 for ambiguous boundaries and verifies the resolved UTC instant. It rejects a fold for unambiguous boundaries. The OS clock is never read.

## Aggregation and data quality

Required `BLOCK` has precedence over required `UNKNOWN`; either prevents overall `PASS`. Unsupported required rules are `UNKNOWN`. An unverified profile, wrong account/phase/revision, currency mismatch, invalid/stale/future observation, incomplete rule definition, or missing required per-rule value is never replaced with zero or another field.

Partial observations may be evaluated when the fields needed by each requested rule are present. Balance and equity are never substituted for each other. USD and USDT remain different currencies.

## Account-bound provenance contracts

CC-3C adds three immutable, strict-serialization schemas without changing the existing rule definition, observation, daily baseline, or evaluation v1 wire schemas:

- `tradingai-prop-rules-snapshot/v1` binds the existing `PropRuleDefinition` to account id/revision, mode, venue, program, plan, phase, applicability, evidence, verification state, unresolved requirements, lineage, and canonical content digest.
- `tradingai-prop-daily-baseline-source/v1` records account and snapshot binding, rule version, trading day, resolved reset/fold, effective/observed/captured times, Decimal reference, currency, source kind, evidence, completeness, verification, revision, lineage, and digest.
- `tradingai-prop-evaluation-evidence-link/v1` binds observation digest, Rules Snapshot, optional required Baseline Source, policy digest, evaluation id/time, and evaluator/result schema for either historical replay or current-entry purpose.

SHA-256 content digests use deterministic canonical JSON and detect content changes; they are not signatures or authenticated tamper prevention. Deserialization recomputes them. The v1 Evaluation Evidence Link is retained as a legacy historical contract, but it does not bind the complete evaluation result and must not be treated as complete evidence or silently promoted to v2.

CC-3E adds isolated pure schemas without changing the rule definition, observation, daily baseline, evaluation, Snapshot, or Baseline Source wire versions:

- `tradingai-prop-evaluation-evidence-link/v2` binds the complete serialized evaluation digest and Complete Bundle digest in addition to observation, snapshot, baseline, policy, purpose, evaluation time, information cutoff, and evaluator version.
- `tradingai-prop-active-rules-selection/v1` records an explicit immutable selection revision and exact account/snapshot binding. It never chooses “latest”, applies a default profile, persists a selection, activates an account, or grants authority.
- `tradingai-prop-required-rule-coverage/v1` binds a required-rule inventory to a snapshot and the fixed calculation-v2 capability set. A caller cannot label an unknown rule as supported. Missing, unsupported, or unresolved requirements prevent operational-candidate compatibility.
- `tradingai-prop-complete-evaluation-bundle/v1` holds one account, optional purpose-appropriate selection, snapshot, baseline, observation, policy, coverage, evaluation time, and knowledge cutoff without copying financial values into another source of truth.
- `tradingai-prop-complete-evaluation-outcome/v1` is generated by the pure wrapper from the validated Bundle. The wrapper does not accept a caller-supplied result; it calculates once and creates the result digest and Link v2 in the same function call.

`HISTORICAL_AS_OF`, `READ_ONLY_CURRENT`, and `OPERATIONAL_CANDIDATE` require evidence to have been observed/captured/verified by `evaluated_at`. `RETROACTIVE_ANALYSIS` permits later evidence only up to an explicit `knowledge_cutoff_at` and remains distinguishable from the original as-of decision. Snapshot applicability/effective time remains tied to the evaluated instant; evidence availability uses the cutoff. Ambiguous reset fold validation remains unchanged.

Bundle validity, calculation PASS, candidate compatibility, runtime readiness, and execution authority are distinct. Every Complete Outcome fixes `execution_authority_granted=false`. Synthetic selection and a complete synthetic Bundle remain non-operational. Unsupported coverage returns UNKNOWN; profit-target progress remains separate from risk gates.

The read-only account context schema remains `tradingai-prop-account-context/v2`. Complete Bundle/Link v2 is not wired into that projection, so it continues to report `RULES_SNAPSHOT_REQUIRED`, stays PARTIAL, and never promotes calculation output to READY.

## Official evidence and unresolved items

Checked 2026-11-01 (Asia/Tokyo) against HyroTrader public pages:

- Daily drawdown FAQ: daily floor is start-of-day equity minus a fixed initial-balance percentage; reset is 00:00 UTC; equity includes floating PnL and fees; the page describes breach as falling below the floor.
- Static drawdown FAQ and 2026 relaunch material: current public challenge families are Zero-Step, One-Step, and Two-Step, with static limits and plan-specific percentages.
- Evaluation page: public profit targets are 10% for the evaluation and 5% for Two-Step verification.
- Terms: exact parameters are governed by the Trading Rules applicable when the program is entered.

Public pages do not identify this repository's target account, purchased plan, phase, account-specific rule revision/effective date, baseline provenance, or whether funding is included in every relevant equity calculation. Public wording around equality at a loss floor is not sufficiently uniform to hard-code a universal boundary. Those items remain unverified, so there is no default real-account profile.

Official sources:

- https://www.hyrotrader.com/faq/rules/how-is-the-5-daily-drawdown-calculated/
- https://www.hyrotrader.com/faq/rules/what-is-the-difference-between-standard-trailing-and-swing-fixed-daily-drawdown/
- https://www.hyrotrader.com/evaluations/
- https://www.hyrotrader.com/pages/terms-and-conditions/

## Unsupported work

Trailing high-water persistence, consistency/profit-distribution caps, minimum trading-day qualification, funded exposure warnings, payout eligibility, official pass/fail certification, order sizing, stop placement, automatic close, runtime/MM/execution wiring, UI calculations, and BB context integration are not implemented. If any unsupported rule is required, the engine returns `UNKNOWN` rather than a complete pass.

## CC-3G temporal and outcome hardening

Complete Bundle temporal validation treats `PropAccountObservation.received_at` as
the time at which every required observation value became available to the evaluator.
For an aggregate assembled from multiple endpoints or pages, producers must set it to
the last required receipt time, not the first page or venue source timestamp.
`observed_at` and `received_at` must both be no later than
`knowledge_cutoff_at`; equality is accepted. Non-retroactive purposes keep
`knowledge_cutoff_at == evaluated_at`. `RETROACTIVE_ANALYSIS` may use later-received
evidence only when the explicit cutoff includes it, and remains non-operational. The
lower-level Engine's small future tolerance remains an input clock-skew rule and cannot
weaken Complete Bundle as-of provenance.

Complete Outcome now rederives `operational_candidate_status` with the same pure
function used by the wrapper and rejects a constructor or deserialized payload whose
status disagrees with Bundle purpose, Coverage, or evaluation state. Recomputing an
unkeyed digest cannot make a semantically inconsistent derived status valid. This
semantic check does not authenticate who calculated or supplied an otherwise
self-consistent graph; trusted wrapper origin and evidence authenticity remain external
requirements.

No wire schema version changed. Rule DTOs remain v1, calculation remains v2, context
remains v2, Evidence Link remains v2 with isolated legacy v1, and Selection, Coverage,
Bundle, and Outcome remain v1. No official profile, runtime authority, UI consumer, BB
consumer, durable store, real source, API, credential, or order connection was added.


## CC-3H read-only Outcome projection

The Complete Outcome wire schema remains v1. A new derived schema, `tradingai-prop-outcome-read-only-context/v1`, exposes synthetic purpose, account scope, cutoff, evidence references, coverage, calculation/candidate state, Decimal strings, units, safe reason codes, and explicit false authority flags. Projection requires strict Complete Outcome deserialization and reuses CC-3G temporal and semantic checks. It does not assert evidence authenticity, official-rule validity, real-account eligibility, Challenge completion, runtime readiness, or trading authority.
