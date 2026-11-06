# Work CC-4A offline synthetic PROP workflow

## Boundary

This workflow connects the isolated preview to existing CC calculation contracts. It
does not connect to Production backend, Registry storage, credentials, exchange
clients, LLMs, bot runtime, or order execution.

- Preview: http://127.0.0.1:4187
- Synthetic evaluator: http://127.0.0.1:4188
- Session: process-local memory only; browser reload or evaluator restart loses state
- Account scope: PROP / EXTERNAL_SIMULATION / BYBIT_DEMO / HYROTRADER
- Rule source and provenance: SYNTHETIC, never VERIFIED_FOR_ACCOUNT
- Authority: executionAuthorityGranted=false, runtimeReady=false, tradeReady=false

## Start

From the CC source worktree, use two terminals.

Terminal 1:

    /home/joe4410joe/tradingai_prod_v1/venv/bin/python -m scripts.serve_prop_offline_workflow

Terminal 2:

    cd frontend
    TRADINGAI_FRONTEND_NODE_MODULES=/home/joe4410joe/tradingai_prod_v1/frontend/node_modules /home/joe4410joe/tradingai_prod_v1/frontend/node_modules/.bin/vite --config vite.prop-accounts-preview.config.js

Open only http://127.0.0.1:4187. Stop both processes with Ctrl-C.

## Operation

1. Keep the permanent “隔離デモ / 架空データ / 実口座未接続” banner in view.
2. Enter a label, phase, and currency, then create a sample account.
3. Confirm the opaque Account ID, revision, fixed platform, and synthetic profile.
4. Enter Decimal values as strings for rules, baseline, balance, equity, and PnL.
5. Enter explicit UTC trading-day and RFC3339 observation/evaluation times.
6. Select “サンプル評価”.
7. Review PASS, BLOCK, or UNKNOWN per rule, coverage, remaining allowance/progress,
   evidence references, cutoff, and disabled authority.
8. Change an input to invalidate the old result, then evaluate again.
9. Use revision update to preserve the account ID and increment its immutable
   identity revision. Results from the previous revision are discarded.

An empty balance, equity, or PnL input is sent as explicit null; it is not converted
to zero. The existing engine retains UNKNOWN where required information is missing.

## HTTP safety

Only three JSON POST routes exist:

- /offline/accounts
- /offline/accounts/revise
- /offline/evaluate

The adapter validates Host and the exact preview Origin, rejects wildcard CORS,
requires JSON, caps bodies at 32 KiB, rejects unknown fields, and does not log raw
payloads. It accepts no URL, file path, code, API key, secret, credential reference,
verification status, or caller-provided result. Internal opaque references are
created by the evaluator.

This boundary has no authentication and is intended only for one local development
user. Loopback and Origin validation do not isolate it from every other local
process. Do not proxy it, bind it to another interface, or treat it as a Production
security boundary. Duplicate JSON keys, unsupported methods, malformed or incomplete
bodies, and bodies that do not arrive within one second are rejected with safe JSON
errors. Session account mutation and evaluation are serialized across HTTP threads.

The evaluation route resolves the exact in-memory account and revision, strictly
parses finite Decimal strings, builds existing immutable Snapshot, Baseline,
Selection, Coverage, Observation, and Complete Bundle contracts, invokes the
existing evaluate_complete_bundle wrapper, and returns the existing
project_outcome_read_only_context projection unchanged.

## Display and stale-response rules

The browser does not calculate loss or profit rules. It sends explicit inputs and
renders the returned projection. Every input change, account switch, or revision
change aborts an in-flight request and removes the prior result. A response is
accepted only when request ID, account ID, identity revision, and local input
generation all still match. Controller ownership and component-mounted state are
also required, so an aborted, replaced, or post-unmount completion cannot update the
screen. An evaluation token rejects same-tick double submission.

Every editable field has an associated label and help/error element. Loading and
result changes use a polite status region; validation errors use an alert. The
isolated acceptance browser check covers keyboard focus order, error recovery,
mobile overflow, and stale-result removal.

The fixed-scenario mode remains below the workflow for regression and demonstration.
Neither mode grants runtime or trade authority, and profit-target arrival is not
shown as Challenge completion.

## CC-4D application route (default OFF)

The operational application can expose the same workflow on the independent
`/prop-isolated-demo` route. This does not replace the loopback preview above.
Both switches are strict and accept only the exact lowercase value `true`:

- frontend: `VITE_PROP_ISOLATED_DEMO_ENABLED=true`
- backend: `PROP_ISOLATED_DEMO_ENABLED=true`

Unset, `false`, mixed-case, whitespace-padded, numeric, and other values are OFF.
The frontend switch cannot enable the backend. When the backend switch is OFF, the
dedicated routes return the fixed `PROP_DEMO_DISABLED` response without invoking
the evaluator:

- `POST /api/prop-accounts/synthetic/accounts`
- `POST /api/prop-accounts/synthetic/accounts/revise`
- `POST /api/prop-accounts/synthetic/evaluate`

These routes reuse the validated operator session and the existing double-submit
CSRF cookie/header middleware. They additionally require a same-origin `Origin`,
accept strict UTF-8 JSON only, reject duplicate keys and non-finite JSON numbers,
and apply the 32 KiB limit while streaming even without `Content-Length`. No CORS
permission is added and the browser client uses fixed relative paths only.

The create/revise/evaluate UI requires short-lived mutable account state. It is
therefore stored only in a process-local registry keyed by the validated operator
session ID. Entries inherit the session expiry, expired entries are evicted on
access, and the least-recent entry is removed above 64 sessions. No background
cleanup task, disk persistence, cross-session lookup, registry access, or logout
payload is introduced. A session cannot resolve an account created by another
session.

The application route stops the global trading WebSocket while displayed and has
no polling, automatic evaluation, credential input, START/order control, trading
settings mutation, or fallback outcome. The normal Account Status selector remains
PAPER/REAL only; its optional PROP link is a separate navigation action.
