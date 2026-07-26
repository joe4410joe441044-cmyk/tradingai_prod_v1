# AI Advisor Exact Release Manifest Candidate

- Manifest ID: `AI-ADV-EXACT-RC-20260726-01`
- Base HEAD: `7a936851bd44bdc5adf004ed8437b7849f9e70c6`
- Generated at: `2026-07-26T06:52:15Z`
- Scope: exact manifest only
- Status: candidate; not staged, committed, pushed, deployed or activated

All paths in this manifest are repository-relative. No wildcard or directory
path represents release authorization.

## Exclusive required files

Every file below is `Untracked / New / AI_ADVISOR_EXCLUSIVE / Required`.

### Backend

```text
backend/ai_advisor/__init__.py
backend/ai_advisor/advisor_service.py
backend/ai_advisor/api_models.py
backend/ai_advisor/api_rate_limit.py
backend/ai_advisor/api_security.py
backend/ai_advisor/browser_gateway.py
backend/ai_advisor/context_builder.py
backend/ai_advisor/conversation_models.py
backend/ai_advisor/conversation_validation.py
backend/ai_advisor/credential_loader.py
backend/ai_advisor/isolated_smoke_runner.py
backend/ai_advisor/knowledge.py
backend/ai_advisor/live_connectivity.py
backend/ai_advisor/mock_provider.py
backend/ai_advisor/models.py
backend/ai_advisor/observability.py
backend/ai_advisor/openai_provider.py
backend/ai_advisor/openai_sdk_transport.py
backend/ai_advisor/production_composition.py
backend/ai_advisor/production_config_loader.py
backend/ai_advisor/production_config_models.py
backend/ai_advisor/production_readiness.py
backend/ai_advisor/prompt_builder.py
backend/ai_advisor/prompt_models.py
backend/ai_advisor/provider_adapter.py
backend/ai_advisor/provider_config.py
backend/ai_advisor/provider_invocation_guard.py
backend/ai_advisor/provider_models.py
backend/ai_advisor/provider_registry.py
backend/ai_advisor/provider_transport.py
backend/ai_advisor/provider_validation.py
backend/ai_advisor/request_safety.py
backend/ai_advisor/response_models.py
backend/ai_advisor/response_parser.py
backend/ai_advisor/response_validation.py
backend/ai_advisor/runtime_reader.py
backend/ai_advisor/service.py
backend/ai_advisor/service_models.py
backend/ai_advisor/systemd_credential_loader.py
backend/ai_advisor/usage_observation.py
backend/api/ai_advisor.py
```

Dependency: shared `backend/main.py` and `requirements.txt`. Coverage: the
complete Backend AI Advisor test set plus full Backend regression.

### Frontend

```text
frontend/src/components/ai-advisor/AdvisorConversation.jsx
frontend/src/components/ai-advisor/AdvisorConversation.test.js
frontend/src/components/ai-advisor/AdvisorGroundedResponse.jsx
frontend/src/components/ai-advisor/AdvisorGroundedResponse.test.js
frontend/src/components/ai-advisor/AdvisorRuntimeStatus.jsx
frontend/src/components/ai-advisor/AdvisorRuntimeStatus.test.js
frontend/src/features/ai-advisor/conversation/advisorApiClient.js
frontend/src/features/ai-advisor/conversation/advisorApiClient.test.js
frontend/src/features/ai-advisor/conversation/advisorAuth.js
frontend/src/features/ai-advisor/conversation/advisorBrowserGatewayClient.js
frontend/src/features/ai-advisor/conversation/advisorBrowserGatewayClient.test.js
frontend/src/features/ai-advisor/conversation/advisorConversationModel.js
frontend/src/features/ai-advisor/conversation/advisorConversationModel.test.js
frontend/src/features/ai-advisor/runtime/advisorRuntimeApi.js
frontend/src/features/ai-advisor/runtime/advisorRuntimeApi.test.js
frontend/src/features/ai-advisor/runtime/advisorRuntimeModel.js
frontend/src/features/ai-advisor/runtime/advisorRuntimeModel.test.js
frontend/src/features/ai-advisor/runtime/useAdvisorRuntime.js
frontend/src/features/ai-advisor/runtime/useAdvisorRuntime.test.js
```

The following are `Tracked / Modified / AI_ADVISOR_EXCLUSIVE / Required`:

```text
frontend/src/pages/AIAdvisorPage.jsx
frontend/src/pages/AIAdvisorPage.test.js
frontend/src/styles/ai-advisor.css
```

Dependency: shared App, API and WebSocket integration files. Coverage:
component, page, client, model, hook, full Frontend and isolated-build checks.

### Tests

Every file below is `Untracked / New / AI_ADVISOR_EXCLUSIVE / Required`.

```text
tests/test_ai_advisor_api.py
tests/test_ai_advisor_api_security.py
tests/test_ai_advisor_browser_gateway.py
tests/test_ai_advisor_context_builder.py
tests/test_ai_advisor_contracts.py
tests/test_ai_advisor_conversation_models.py
tests/test_ai_advisor_credential_loader.py
tests/test_ai_advisor_grounding.py
tests/test_ai_advisor_isolated_smoke_runner.py
tests/test_ai_advisor_live_connectivity.py
tests/test_ai_advisor_openai_sdk_compatibility.py
tests/test_ai_advisor_openai_sdk_transport.py
tests/test_ai_advisor_production_composition.py
tests/test_ai_advisor_production_config.py
tests/test_ai_advisor_prompt_builder.py
tests/test_ai_advisor_provider.py
tests/test_ai_advisor_provider_contract.py
tests/test_ai_advisor_provider_security.py
tests/test_ai_advisor_response_security.py
tests/test_ai_advisor_response_validation.py
tests/test_ai_advisor_runtime.py
tests/test_ai_advisor_service.py
tests/test_ai_advisor_systemd_credential.py
```

### Documentation

Every file below is `Untracked / New / AI_ADVISOR_EXCLUSIVE / Required`.

```text
docs/09_AI_Advisor_Master_Specification.md
docs/ai_advisor/01_AI_Advisor_Role_Permission_and_Safety_Boundary_Specification.md
docs/ai_advisor/AI_ADVISOR_EXACT_RELEASE_MANIFEST_CANDIDATE.md
docs/ai_advisor/AI_ADVISOR_RELEASE_CONTENT_CANDIDATE.md
docs/ai_advisor/AI_ADV_1F_BATCH2_PRODUCTION_RUNBOOK.md
docs/ai_advisor/EXTERNAL_CONTEXT_DATA_MINIMIZATION_CANDIDATE.md
docs/ai_advisor/FINAL_OFFLINE_PRODUCTION_READINESS_PACKAGE.md
docs/ai_advisor/PRODUCTION_CONFIGURATION_MATRIX_CANDIDATE.md
docs/ai_advisor/approved_knowledge_manifest.candidate.json
docs/ai_advisor/systemd-credential-smoke-runbook.md
```

## Shared required files and hunk ownership

| Relative path | State | Hunks | AI Advisor | Other | Mixed | Separation | Purpose |
|---|---|---:|---:|---:|---:|---|---|
| `backend/main.py` | Tracked/Modified | 2 | 2 | 0 | 0 | PATCH_STAGE_SAFE | imports; route/composition registration |
| `requirements.txt` | Tracked/Modified | 1 | 1 | 0 | 0 | PATCH_STAGE_SAFE | `openai==2.48.0` |
| `frontend/src/App.jsx` | Tracked/Modified | 4 | 4 | 0 | 0 | PATCH_STAGE_SAFE | Advisor route WebSocket isolation |
| `frontend/src/App.test.js` | Tracked/Modified | 4 | 4 | 0 | 0 | PATCH_STAGE_SAFE | App isolation coverage |
| `frontend/src/api/index.js` | Tracked/Modified | 5 | 5 | 0 | 0 | PATCH_STAGE_SAFE | safe env access and coarse runtime path |
| `frontend/src/runtime/websocketRuntime.js` | Tracked/Modified | 11 | 11 | 0 | 0 | PATCH_STAGE_SAFE | explicit stop/reconnect suppression |
| `frontend/src/runtime/websocketRuntime.test.js` | Untracked/New | 1 | 1 | 0 | 0 | PATH_STAGE_SAFE | WebSocket isolation regression |

No shared hunk contains Money Management, Execution Marker or Dashboard
changes. Shared tracked files should nevertheless be staged interactively,
one reviewed AI Advisor hunk at a time. The untracked shared test can be
reviewed and staged by its exact path.

## Optional files

Every file below is `Untracked / New / AI_ADVISOR_OPTIONAL / Optional`.

```text
deploy/nginx/ai-advisor-browser-gateway.conf.example
deploy/systemd/tradingai-ai-advisor-smoke.service.example
deploy/systemd/tradingbot-loopback.override.conf.example
docs/00_TradingAI_Platform_Master_Specification.md
```

The deployment examples are never auto-installed. The Platform Master
Specification is a candidate cross-platform knowledge source and is kept
optional to avoid coupling the executable release to broader documentation.

## Explicit exclusions

| Relative path | State | Classification | Dependency conflict |
|---|---|---|---|
| `Bot/engine/execution_engine.py` | Tracked/Modified | EXECUTION_MARKER_EXCLUDED | No |
| `backend/bot_manager/bot_manager.py` | Tracked/Modified | EXECUTION_MARKER_EXCLUDED | No; Advisor imports only its existing committed read accessor |
| `backend/execution/execution_marker.py` | Untracked/New | EXECUTION_MARKER_EXCLUDED | No |
| `tests/test_paper_execution_markers.py` | Untracked/New | EXECUTION_MARKER_EXCLUDED | No |
| `docs/01_Money_Management_Master_Specification.md` | Untracked/New | MONEY_MANAGEMENT_EXCLUDED | No |
| `docs/01_Money_Management_Specification_Additions_v1.1.md` | Untracked/New | MONEY_MANAGEMENT_EXCLUDED | No |
| `docs/08_Dashboard_Redesign_Specification.md` | Untracked/New | DASHBOARD_EXCLUDED | No |
| `frontend/dist/index.html` | Tracked/Modified | BUILD_ARTIFACT_EXCLUDED | No |

`OTHER_EXISTING_EXCLUDED` and `UNKNOWN_OWNERSHIP` contain zero files.
No excluded file is required to make the exact AI Advisor candidate internally
testable.

## Dependency audit

- Added Backend dependency: `openai==2.48.0`.
- Reason: the offline-guarded OpenAI provider adapter and SDK transport.
- Installed environment: present; `pip check` passes.
- Other-work dependency mixed into the same hunk: none.
- Backend lockfile: none changed.
- Frontend package and lockfile changes: none.
- The UTF-16/CRLF representation of `requirements.txt` makes normal textual
  patch review awkward, but its single changed logical line is independently
  separable and requires explicit review.

## Specification and knowledge status

| Relative path | HEAD | Version | Release inclusion | Candidate source |
|---|---|---|---|---|
| `docs/ai_advisor/01_AI_Advisor_Role_Permission_and_Safety_Boundary_Specification.md` | Absent | 1.1 | Required | Eligible only after commit |
| `docs/09_AI_Advisor_Master_Specification.md` | Absent | 0.2 | Required | Eligible only after commit |
| `docs/00_TradingAI_Platform_Master_Specification.md` | Absent | 1.0 Draft | Optional | Eligible only after separate inclusion and commit |
| `docs/ai_advisor/AI_ADV_1F_BATCH2_PRODUCTION_RUNBOOK.md` | Absent | Release candidate runbook | Required | Eligible only after commit |

After a release commit: re-check the committed HEAD, regenerate content hashes,
revalidate the knowledge manifest, obtain owner approval, and keep external
transmission disabled. This candidate does not activate knowledge.

## Test, build and secret baseline

- Backend full: 584 passed.
- Backend AI Advisor: 292 passed.
- Frontend: 280 passed.
- Python compile, Black, targeted ESLint, `pip check`: passed.
- Isolated Vite build: passed; tracked distribution not used.
- Secret scan: passed; test fixtures are synthetic and non-production.
- `git diff --check`: passed.

## Commit options

### Option A — one atomic commit

Backend, Frontend, tests, required docs and approved optional files are one
commit. It preserves cross-layer testability and makes the security route
change atomic. Risk: large review surface and a larger rollback unit.

### Option B — three commits

1. Backend, Backend tests, dependency and `backend/main.py`.
2. Frontend, Frontend tests and shared Frontend integration.
3. Required docs and separately approved optional examples/source.

This gives smaller rollback units, but the intermediate Backend commit exposes
routes before the Frontend migration is present, and shared-hunk staging is
repeated. Each intermediate commit needs its own regression.

Recommendation: Option A. The runtime authentication change, Trusted Proxy
coarse route and Frontend migration are one security boundary and should remain
atomic.

## Exact staging plan

1. Confirm Base HEAD, zero staged changes and the unchanged dirty inventory.
2. Review and stage each exact exclusive required path listed above separately.
3. Review `backend/main.py`, `requirements.txt`, `frontend/src/App.jsx`,
   `frontend/src/App.test.js`, `frontend/src/api/index.js`, and
   `frontend/src/runtime/websocketRuntime.js` interactively; accept only the
   AI Advisor hunks recorded in the shared-hunk table.
4. Review and stage the exact new path
   `frontend/src/runtime/websocketRuntime.test.js`.
5. Stage optional paths only when each is named in the approval.
6. Do not use repository-wide, all-change, commit-all or unreviewed directory
   staging.
7. Verify the staged name list exactly matches the approved manifest subset.
8. Inspect the complete staged patch, repeat a filename-only staged secret
   scan, and confirm every excluded path remains unstaged.
9. Run the staged-source Backend and Frontend baselines plus an isolated build.
10. Confirm `git diff --cached --check`, then present the staged patch for a
    separate commit authorization.

No index patch is generated or applied by this candidate.

## Post-commit validation

Confirm commit parent equals Base HEAD, the committed file list matches the
approved manifest, excluded files remain dirty and unstaged, full regression
passes, HEAD is one commit ahead of `origin/main`, and no push or deployment
has occurred. Then regenerate candidate knowledge hashes from committed
content; content hashes are identity aids, not security authentication.

## Known findings

- Production Uvicorn still binds to `0.0.0.0:8001`.
- Nginx Trusted Proxy authentication is not applied.
- Direct external reachability is unverified.
- Credential, external-context and knowledge approvals are pending.
- Optional files require independent inclusion approval.
