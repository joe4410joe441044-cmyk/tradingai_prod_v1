# Work CC-3J BB reacceptance preservation

## Status and provenance

This document preserves the user-supplied BB reacceptance of the CC-3J provider
delta. The recorded decision is:

- `CC_PROVIDER_REACCEPTANCE=ACCEPTED`
- `BB_INTEGRATION_STATUS=NOT_READY`
- `BLOCKING_CC_FINDINGS=NONE`

This is `USER_SUPPLIED_BB_REACCEPTANCE`. BB's independent test rerun did not
start because its permission review timed out. Acceptance used the existing
targeted validation evidence plus exact file-hash and generated-sample-hash
matching. It must not be represented as a second successful test run.

The accepted parent/base commit is
`4a93902478fcbb84d66f8ce443f0f48bb99ae58c` on
`feature/hyrotrader-integration`. The provider commit created after this document
is intentionally not embedded here.

## Accepted CC-3J files

| Path | SHA-256 |
| --- | --- |
| `docs/hyrotrader/WORK_CC_BB_READ_ONLY_HANDOFF.md` | `25027fbe5837356c941c10c1b4cab9209b24e285caabe056f0d0676627062648` |
| `docs/hyrotrader/WORK_CC_STATUS.md` | `00564d45330891d76fabe2a878b1e582ab5e02b93fd6bcd530503b65d69cde08` |
| `docs/hyrotrader/WORK_CC_VALIDATION.md` | `ec027cbc272ea29c33a17b0fb4ee3699d2ea5a5c055167ff79f53600be265a2b` |
| `frontend/src/components/prop-accounts/PropAccountsPanel.jsx` | `951b680790c5d597c99cd0800f0d1c68d54ca3a14034861ced4e2caee96b84ae` |
| `frontend/src/features/prop-accounts/propAccountsFixtures.js` | `61f902f564ffbd46059416911966c0b5e07e8d8f73ab5501431c91f7e0d08d76` |
| `frontend/src/features/prop-accounts/propAccountsViewModel.js` | `93dd307fa43a8a72c53edd5f84421f834e171c30e5e8df2b0f8f1939e35537a2` |
| `frontend/src/features/prop-accounts/propAccountsViewModel.test.js` | `b856b9c4af95f138e7d87b4e369084dc7cbba81343f476ca2a2b4cce8c5ec644` |
| `frontend/src/features/prop-accounts/propOutcomeFixtures.js` | `152e94a5402eb1d2eff83fbba563d0c9441ed68e029eb3bed65d35b32f1740f9` |
| `frontend/src/features/prop-accounts/propOutcomeFixtures.test.js` | `709c85097a39d62d398cbd4209976b5ef27f85fb326383ca031dda3d42612c2a` |
| `tests/test_prop_outcome_projection.py` | `cdf9b4e898b54a095bf89034bf90826915bd28492df99ff197144cec841e1342` |

The deterministic generated sample
`frontend/src/features/prop-accounts/generatedSyntheticOutcomes.json` remains
unchanged at SHA-256
`8dd5032ca1a6dce177209cb5aefbe621943ce30d20d27fce9238366a47ffa336`.
It contains six scenarios: five strict Outcome projections and one
pre-evaluation rejection with no fabricated Outcome.

## Accepted contract

- Schema remains `tradingai-prop-outcome-read-only-context/v1`.
- The fixture display binds all eight scope fields from the selected account
  descriptor and rejects missing, null, malformed, or mismatched scope.
- The frontend validator is fixture-display-only and is not BB's production
  exact-shape validator.
- Diagnostic warnings, evidence references, and reference IDs/digests remain in
  the diagnostic projection but are excluded by default from future BB AI context.
- Fixture purposes are limited to `READ_ONLY_CURRENT`, `HISTORICAL_AS_OF`, and
  `RETROACTIVE_ANALYSIS`; `OPERATIONAL_CANDIDATE` and unknown purposes fail closed.
- Every generated Outcome has `executionAuthorityGranted`, `runtimeReady`, and
  `tradeReady` set to false.

## Existing validation evidence

- Frontend view-model and fixture-validator tests: 18 passed.
- Frontend panel tests: 11 passed.
- Backend projection and Complete Outcome tests: 44 passed.
- Isolated PROP preview build: 22 modules built successfully.
- Two deterministic generations were byte-identical and matched the checked-in
  generated JSON.

CC-3K does not rerun those tests, the build, browser checks, or fixture generation
because the accepted hashes match exactly. Visual acceptance remains pending under
the known environment limitation.

## Remaining BB responsibilities

BB still owns the v1 production exact-shape validator, independent request/account
scope binding with no fallback, the minimal AI-context serializer, exclusion of
warnings/evidence references/all reference IDs and digests, current-clock freshness
and max-age enforcement, coverage-subversion/reference/candidate validation,
fail-closed unknown schema/purpose/field handling, safe error presentation, and
integration tests.

No BB implementation, runtime/MM/execution wiring, official account-profile
activation, real venue connection, credential access, Production change, or trading
authority is included. The provider commit depends on its CC ancestry; consuming
only this final delta is not asserted to provide the whole CC module set. BB intake
and integration strategy require a separate authorized task.
