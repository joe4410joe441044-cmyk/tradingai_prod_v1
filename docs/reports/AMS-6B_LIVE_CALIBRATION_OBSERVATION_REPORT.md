# AMS-6B Live Calibration Observation Report

Observed 2026-08-09 01:39:29Z–01:41:21Z. This is a market-only, public-data,
read-only calibration result. It is not a production configuration decision.

## Git

- branch: `main`
- HEAD / origin/main: `d57de0439576c1134a67ce6055f65fc4a1c084e0`
- ahead / behind: `0 / 0`
- working tree: dirty before AMS-6B; all existing changes preserved

## Campaign

- requested / completed: `20 / 20`
- duration / interval: `111.733867s / 5s`
- network failures: `0`
- universe per observation: `676 evaluated, 666 eligible, 10 rejected`
- active symbol: `BTCUSDT`; rankable `20`, not-rankable `0`
- active score observed range: approximately `0.5716–0.5733`
- network latency: approximately `0.75–1.05s` in the normal observations
- observation window: `INSUFFICIENT OBSERVATION WINDOW` for final thresholds

The first attempted campaign was excluded: its fixed calibration MM snapshot had
an evaluation timestamp later than the scanner timestamp, so all candidates
correctly failed freshness. It performed no action. The provider contract was
corrected to use the exact observation timestamp before collecting the 20 valid
samples above.

## API Safety and Cadence

KuCoin's official current contract lists Public VIP0 as 2000 weight per 30
seconds. `GET /api/v1/contracts/active` is weight 3 and `GET
/api/v1/allTickers` is weight 5. One observation therefore consumes weight 8;
the tested five-second cadence is approximately 48 weight per 30 seconds.

- tested: `5s`
- network-safe in this campaign: `YES` (no 429, timeout, HTTP, empty, or malformed response)
- candidate next validation range: `5–15s`
- confidence: `MEDIUM` for API safety, `LOW` for selection quality

Sources: [KuCoin rate limits](https://www.kucoin.com/docs-new/rate-limit?lang=en_US),
[Get All Symbols](https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-all-symbols),
[Get All Tickers](https://www.kucoin.com/docs-new/rest/futures-trading/market-data/get-all-tickers?lang=en_US).

## Ranking Evidence

- unique Top candidates: `2` (`DYMUSDT`, `MOVEUSDT`)
- Top changes: `3`
- longest consecutive wins: `14`
- observed run lengths: `2, 3, 14, 1`; median `2.5 observations`
- Top-1 change rate: `15.7895%`
- Top-3 membership change rate: `89.4737%`
- Top-5 membership change rate: `89.4737%`
- transition sequence: `DYM → MOVE → DYM → MOVE`
- oscillations: `2` (`DYM-MOVE-DYM`, `MOVE-DYM-MOVE`)
- approximate oscillation intervals: `29.44s`, `99.10s`
- dwell min / median / p90 / max: `0s / 8.94s / 56.48s / 75.61s`

The zero dwell is a right-censored final Top change at the last observation and
must not be interpreted as a completed dwell period.

## Score Distributions

Top versus current BTCUSDT score advantage:

- min: `0.4149131786`
- median: `0.4243953704`
- p75: `0.4246842905`
- p90: `0.4248247964`
- p95: `0.4248498003`
- max: `0.4249164541`

Top-1 versus Top-2 difference:

- min: `0.0168419566`
- median: `0.0796475840`
- p75: `0.1516879915`
- p90: `0.2204033475`
- p95: `0.3342482097`
- max: `0.3588464926`

## Candidate Calibration Ranges

These ranges are inputs for a longer validation campaign, not final values:

| Parameter | Candidate next range | Confidence | Evidence |
|---|---:|---|---|
| `selectionObservationInterval` | `5–15s` | LOW | 5s was API-safe; only one 112s window was tested |
| `minimumScoreAdvantage` | `0.40–0.43` | LOW | observed Top-vs-current range was 0.4149–0.4249 and is specific to BTCUSDT/current normalization |
| `minimumActiveDuration` | `15–60s` | LOW | short runs lasted roughly 6–18s; one persistent run exceeded 75s |
| `switchCooldown` | `30–120s` | LOW | compressed A-B-A intervals were roughly 29s and 99s |
| `requiredConsecutiveWins` | `3–10` | LOW | run lengths were 2, 3, 14, 1; values around 3 still admit a short transient run |

All five are `REQUIRES MORE OBSERVATION`. A multi-hour, multi-regime campaign
should compare the offline grid before AMS-6C finalization. The implemented
hypothetical evaluator never calls a runtime switch and is covered by tests.

## Market Failures and MM Separation

- `NOT_TRADABLE`: `0` observed for active BTCUSDT
- `DATA_INVALID`: `0` observed for active BTCUSDT
- `MM_BLOCKED`: `0` in the fixed feasibility input
- authoritative Live account used: `NO`
- market calibration: `PARTIAL / COMPLETE FOR THIS SHORT CAMPAIGN`
- Live capital / MM calibration: `BLOCKED`

The fixed MM snapshot is not an authoritative Live account snapshot. No
account-dependent conclusion is made.

## Safety

- activeSymbol mutations: `0`
- SafeSwitch commits: `0`
- real orders: `0`
- execution permission changes: `0`
- governance bypass: `0`
- emergency changes: `0`
- credential leakage: `0`

No production scheduler or calibration configuration was changed.

## Verification and Findings

- AMS test suite: `182 passed`
- focused AMS-5B/6B suite: `19 passed`
- HIGH: authoritative Live capital/MM calibration remains blocked
- HIGH: the 112-second window is insufficient for final dwell/cooldown thresholds
- MEDIUM: Top-3 and Top-5 membership changed in 89.47% of adjacent samples
- LOW: five-second polling was far below the documented Public pool quota

AMS-6B: **PASS WITH FINDINGS**.

AMS-6C Calibration Specification Finalization: **BLOCKED** pending a longer,
multi-regime market campaign and authoritative Live capital/MM observation.
Live AUTO implementation remains blocked.
