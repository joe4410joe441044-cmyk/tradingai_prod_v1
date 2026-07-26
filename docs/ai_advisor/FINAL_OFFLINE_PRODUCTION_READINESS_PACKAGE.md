# AI Advisor Final Offline Production Readiness Package

Status: `PREPARATION ONLY / NO PRODUCTION AUTHORITY`

## systemd and Uvicorn candidate

Current service binds Uvicorn to `0.0.0.0:8001`. The candidate drop-in changes
only the host to `127.0.0.1`, preserving the application, port and Nginx
upstream. The isolated one-shot smoke unit remains separate.

Before installation, verify the candidate with systemd tooling, compare the
effective `ExecStart`, and confirm Nginx `/api` and `/ws` both use loopback.
After a separately approved restart, verify HTTP health and WebSocket upgrade.
Rollback removes the candidate drop-in and restores the previously captured
effective unit. No drop-in is installed by this package.

## Nginx candidate review

`deploy/nginx/ai-advisor-browser-gateway.conf.example` is candidate-only.
Static review confirms exact gateway/status locations, browser authentication,
server-owned identity overwrite, discarded Authorization header, loopback
upstream, bounded body/timeouts and rejected preflight. It does not modify the
existing frontend or WebSocket locations. Authentication file and domain
remain placeholders and require separate approval.

## Firewall and direct access

Local inspection found Uvicorn listening on all interfaces at port 8001.
No supported local firewall status utility was available. Repository and local
state cannot establish GCP firewall policy, so external reachability is
`EXTERNAL_REACHABILITY_UNVERIFIED`. Do not infer that the port is externally
closed. Loopback bind is a prerequisite.

## Release modes

| Mode | Candidate state | Blocking conditions |
|---|---|---|
| OFFLINE_UI | Candidate after committed release and deploy approval | Uncommitted release |
| ISOLATED_LIVE_SMOKE | Prepared, not authorized | Credential placement and one-request operator approval |
| BROWSER_GENERAL_GUIDANCE | Not production-ready | Loopback bind, Nginx auth, gateway and external-AI approvals |
| GROUNDED_SPECIFICATION | Not production-ready | Committed approved manifest and external-context approval |
| RUNTIME_EXPLANATION | Out of scope | Dedicated read contract and approval |

## Production change plan

Each phase requires a separate stop/go decision.

1. Phase 0 — capture Git state, test evidence and recoverable backups. Stop on
   dirty ownership ambiguity or failed regression.
2. Phase 1 — review and commit an isolated release candidate. Stop until commit
   and push are independently approved.
3. Phase 2 — prepare systemd credentials without exposing values. Stop unless
   ownership, permissions and credential IDs are verified.
4. Phase 3 — install the reviewed loopback drop-in. Validate effective unit;
   rollback the drop-in on mismatch.
5. Phase 4 — install reviewed Nginx authentication and identity overwrite.
   Validate candidate syntax; rollback before reload on any mismatch.
6. Phase 5 — deploy with Browser Gateway, Knowledge, network and external
   context disabled. Stop on any unexpected enabled state.
7. Phase 6 — run offline production smoke. Roll back the release on regression.
8. Phase 7 — only with explicit approval, run one isolated synthetic OpenAI
   request. Stop after one request; retry remains zero.
9. Phase 8 — only after proxy/bind approval, enable the Browser Gateway.
10. Phase 9 — keep Knowledge and external context disabled.
11. Phase 10 — record safe status and close the change.

## Rollback order

1. Disable Browser Gateway.
2. Disable Knowledge retrieval.
3. Disable external context transmission.
4. Disable network invocation.
5. Activate live kill switch.
6. Disable Advisor endpoint.
7. Withdraw the Nginx candidate and restore the reviewed prior configuration.
8. Withdraw the loopback candidate only if rollback requires the prior unit.
9. Stop the isolated unit and verify no temporary credential remains.
10. Restore previous frontend artifact and backend release independently.
11. Verify the normal trading service state without enabling trading.

## Smoke plans

Offline production smoke:

- start only through separately approved operations;
- verify the frontend route;
- verify Gateway disabled;
- verify authentication and direct access fail closed;
- verify status contains only a coarse state;
- verify provider calls remain zero.

Isolated live smoke:

- model `gpt-4o-mini`;
- fixed synthetic prompt only;
- maximum 512 output tokens;
- exactly one provider call, retry zero;
- second invocation denied;
- no documents, Runtime, conversation or trading data.

Browser smoke is conditional on loopback bind and Nginx authentication. Send
one prompt through the exact Origin and trusted identity path, verify a safe
response, and verify no secret or trading action.

## Operator approval units

The following are independent approvals and must never be collapsed into one:

A. create an isolated commit;
B. push the reviewed commit;
C. create/place systemd credentials;
D. install candidate unit/drop-in and Nginx configuration;
E. run daemon-reload;
F. restart `tradingbot.service`;
G. deploy the reviewed release;
H. perform one OpenAI request;
I. enable Browser Gateway;
J. approve and enable Knowledge;
K. approve external context transmission.
