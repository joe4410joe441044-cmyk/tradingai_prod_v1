# AMS-6B-R1 Extended Live Calibration & Live Account Authority Validation

## Git

- branch: `main`
- HEAD / origin/main: `d57de0439576c1134a67ce6055f65fc4a1c084e0`
- ahead / behind: `0 / 0`
- working tree: dirty before R1; existing changes preserved

No commit, push, deploy, production scheduler change, or production calibration
change was performed.

## Extended Campaign

- requested: `102` (`100` primary + `2` supplemental)
- completed: `101 valid` (`99` primary + `2` supplemental)
- primary duration: `610.420695s`
- supplemental duration: `6.700103s`
- interval: `5s`
- network failures: `1`
- rate-limit issues / 429: `0`
- active symbol: `BTCUSDT`

The failed observation took approximately 20.9 seconds and was retained as a
missing observation. No previous candidate was reused. The two supplemental
observations brought the total to more than 100 valid observations.

The distributions below are the internally consistent 99-valid primary
campaign distributions. The supplemental score advantages were 0.4174287 and
0.4174562 and do not alter the conclusions. They are not silently merged into
percentiles after the primary process exited.

## Score Advantage

| Statistic | Value |
|---|---:|
| min | 0.4162625139 |
| p10 | 0.4179810505 |
| p25 | 0.4203493172 |
| median | 0.4230383988 |
| p75 | 0.4243999221 |
| p90 | 0.4251785613 |
| p95 | 0.4253362403 |
| max | 0.4256210615 |

Top-1 versus Top-2 gap: min `0.0096011513`, p10 `0.0605349448`, p25
`0.1456607499`, median `0.2586676283`, p75 `0.3293145411`, p90
`0.3519382230`, p95 `0.3628696767`, max `0.3888334119`.

## Candidate Persistence and Dwell

- run count: `9`
- run length min / p10 / p25: `1 / 1 / 2`
- run length median / p75 / p90 / p95 / max: `3 / 13 / 26.8 / 36.4 / 46`
- dwell median / p75 / p90 / p95 / max: `11.57s / 69.59s / 157.62s / 228.19s / 298.75s`
- final run: `RIGHT CENSORED`

## Oscillation

- unique Top candidates: `3`
- Top changes: `8`
- count: `6`
- compressed-transition opportunity rate: `85.71%`
- shortest / median / p90 interval: `17.38s / 73.09s / 117.23s`
- Top-1 change rate: `8.16%`
- Top-3 / Top-5 membership change rate: `70.41% / 85.71%`

Patterns were five MOVE/DYM reversals and one `MOVE → CHZ → MOVE` reversal.

## Hypothetical Anti-Flapping Simulation

- parameter combinations: `256`
- score thresholds: `0.40, 0.41, 0.42, 0.43`
- consecutive wins: `3, 5, 7, 10`
- minimum active duration: `15, 30, 45, 60s`
- cooldown: `30, 60, 90, 120s`
- hypothetical switch count range: `0–1`
- runtime/config mutations: `0`

The high-churn region was the low score threshold (`0.40`) with permissive
persistence/duration, although even this produced only one switch in the short
ten-minute window. The `0.43` region produced zero switches because the observed
maximum advantage was only 0.42562; this region risks suppressing every
persistent candidate and is not supported as a safe production choice.

Candidate next validation range, not final configuration:

- `selectionObservationInterval`: `5–15s`
- `minimumScoreAdvantage`: `0.41–0.425`
- `requiredConsecutiveWins`: `5–10`
- `minimumActiveDuration`: `30–60s`
- `switchCooldown`: `60–120s`

Confidence remains `LOW–MEDIUM`; a multi-hour/multi-regime observation is still
needed before calling these values final.

## Live Account Authority Audit

Existing source identified:

- `KucoinTrade.get_account_overview()` → signed GET `/api/v1/account-overview`
- `KucoinTrade.get_positions()` → signed GET `/api/v1/positions`
- `KucoinTrade.get_open_orders()` → signed GET `/api/v1/orders?status=active`

Runtime availability at validation time:

- running TradingAI process: `NO`
- `KUCOIN_API_KEY`: `UNSET`
- `KUCOIN_API_SECRET`: `UNSET`
- `KUCOIN_API_PASSPHRASE`: `UNSET`
- private read attempted: `NO — safety preflight ABORT`
- real equity / available capital: `UNCONFIRMED`
- Live position / pending orders / exposure / freshness: `UNCONFIRMED`

No fixture, paper equity, guessed zero, or manual fallback was presented as a
real Live authority.

The new adapter reuses only those existing GET methods, distinguishes
`FLAT/OPEN/UNKNOWN` and `NONE/EXISTS/UNKNOWN`, validates source and freshness,
and rejects missing authoritative exposure. When all inputs are authoritative,
it delegates to the existing MM `build_capital_eligibility_contract`; AMS does
not duplicate sizing or exposure math.

## Live MM Contract

- `LiveAccountAuthoritySnapshot`: implemented and unit validated
- `CapitalEligibilityContract`: generation path unit validated through MM builder
- `PerMarketEligibility`: existing contract remains reusable
- real Live instance: `NOT GENERATED`
- reason: `LIVE MM AUTHORITY NOT READY`

## Safety

- activeSymbol mutations: `0`
- SafeSwitch commits: `0`
- real orders: `0`
- order cancellation: `0`
- private mutation API calls: `0`
- execution/governance/emergency changes: `0`
- credential leakage: `0`

## Verification and Decision

- focused AMS-5B/6B/R1 tests: `27 passed`
- full AMS tests: `190 passed`
- diff whitespace validation: `PASS`

Findings:

- HIGH: real Live account credentials/runtime authority were unavailable, so
  Live equity, available capital, exposure, positions, orders, and freshness
  could not be confirmed against the exchange.
- HIGH: Live MM contract generation is validated structurally but not with a
  real authoritative snapshot.
- MEDIUM: 101 valid observations cover about ten minutes, not multiple market
  regimes; calibration values remain non-final.
- MEDIUM: compressed Top transitions oscillated in 6 of 7 opportunities.
- LOW: five-second public polling produced no 429 and only one fail-closed
  network observation.

Decision:

- AMS-6B-R1: **PASS WITH FINDINGS**
- Market calibration: **READY for further specification work, with non-final ranges**
- Live Account/MM authority: **BLOCKED**
- AMS-6C: **BLOCKED**
- Live AUTO implementation: **STILL BLOCKED**
