# AI Advisor Exact Release Manifest Candidate

- Manifest ID: `AI-ADV-EXACT-RC-20260730-03`
- Repository: `/home/joe4410joe/tradingai_prod_v1`
- Branch: `main`
- Base HEAD: `20e7cdcae0dfc457040a793e222b71e0ac5eb192`
- Base versus `origin/main`: ahead 0 / behind 0
- Generated at: `2026-07-30`
- Scope: exact manifest only
- Committed RC HEAD: `8a18b2f58bf02f1b69ac3ab67de6cb8ad3e71ac6`
- Committed RC versus `origin/main`: ahead 0 / behind 0
- Working tree: dirty; the unrelated three-path inventory remains excluded
- Status: RC committed and pushed; not deployed, live-validated, or activated
- Live Validation 03: `INCONCLUSIVE / EXECUTION_PROCEDURE_GAP`
- `IMPLEMENTATION_COMPLETE`: `YES`
- `LIVE_VALIDATED`: `NO`
- `PRODUCTION_ACTIVATED`: `NO`
- New Live execution: not authorized; a new explicit approval is required

## Post-RC Safe Result Contract follow-up

The offline `AI-ADV-LIVE-SAFE-RESULT-CONTRACT-FIX-01` delta is based on the
committed RC HEAD above. It was committed and pushed as
`fdb5f731a0b94538e4badddb360889c3af3c01dd`; it has not been deployed,
live-validated, or activated. Its exact ten paths are:

```text
backend/ai_advisor/isolated_smoke_runner.py
backend/ai_advisor/openai_sdk_transport.py
backend/ai_advisor/production_composition.py
backend/ai_advisor/usage_observation.py
docs/ai_advisor/AI_ADVISOR_EXACT_RELEASE_MANIFEST_CANDIDATE.md
docs/ai_advisor/systemd-credential-smoke-runbook.md
tests/test_ai_advisor_isolated_smoke_runner.py
tests/test_ai_advisor_openai_sdk_transport.py
tests/test_ai_advisor_systemd_credential.py
tests/test_ai_advisor_systemd_unit_contract.py
```

This follow-up adds only the safe `request_id`, `model`, `provider`, and
`endpoint_classification` evidence contract, its fail-closed sanitizer rules,
offline tests, and authoritative documentation. It grants no Live authority.
The committed RC file set remains 110 unique paths.

## Post-follow-up Runner Detection delta

The offline `AI-ADV-LIVE-RUNNER-DETECTION-FIX-01` delta is based on
`fdb5f731a0b94538e4badddb360889c3af3c01dd`. It is not staged, committed,
pushed, deployed, live-validated, or activated. Its exact five paths are:

```text
backend/ai_advisor/runner_process_detection.py
docs/ai_advisor/AI_ADVISOR_EXACT_RELEASE_MANIFEST_CANDIDATE.md
docs/ai_advisor/systemd-credential-smoke-runbook.md
tests/test_ai_advisor_runner_process_detection.py
tests/test_ai_advisor_systemd_unit_contract.py
```

This delta replaces unstructured standalone `pgrep -f` detection with a
read-only, fail-closed, independently executed preflight based on fixed-unit
state and exact process metadata. It grants no Live authority. A future Live
retry requires separate explicit approval.

All paths in this manifest are repository-relative. No wildcard or directory
path represents release authorization.

## Exclusive required files

Every file below is `AI_ADVISOR_EXCLUSIVE / Required`. Its committed RC delta
against Base HEAD is defined by the exact tables below. Any required path not
present in a delta table was `tracked-unchanged` in that committed RC delta; no
path was implicitly `untracked-new`.

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
backend/ai_advisor/provider_failure_observation.py
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

The following are `tracked-unchanged / AI_ADVISOR_EXCLUSIVE / Required`:

```text
frontend/src/pages/AIAdvisorPage.jsx
frontend/src/pages/AIAdvisorPage.test.js
frontend/src/styles/ai-advisor.css
```

Dependency: shared App, API and WebSocket integration files. Coverage:
component, page, client, model, hook, full Frontend and isolated-build checks.

### Tests

Every file below is `AI_ADVISOR_EXCLUSIVE / Required`; the exact current state
is defined by the delta tables.

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
tests/test_ai_advisor_provider_failure_observation.py
tests/test_ai_advisor_provider_security.py
tests/test_ai_advisor_response_security.py
tests/test_ai_advisor_response_validation.py
tests/test_ai_advisor_runtime.py
tests/test_ai_advisor_service.py
tests/test_ai_advisor_systemd_credential.py
tests/test_ai_advisor_systemd_unit_contract.py
```

### Documentation

Every file below is `AI_ADVISOR_EXCLUSIVE / Required`; documents with similar
names remain separate artifacts and are not merged by this manifest.

```text
docs/09_AI_Advisor_Master_Specification.md
docs/01_AI_Advisor_Master_Specification.md
docs/01_AI_Advisor_Role_Permission_and_Safety_Boundary_Specification.md
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

`docs/09_AI_Advisor_Master_Specification.md` is the detailed tracked Advisor
specification. `docs/01_AI_Advisor_Master_Specification.md` is the current
top-level design baseline. The root and `docs/ai_advisor/` role/safety
specifications are distinct current candidate copies and remain separately
listed pending later document-governance decisions.

### Committed RC state deltas against Base HEAD

The following 24 required paths are `tracked-modified`:

```text
backend/ai_advisor/advisor_service.py
backend/ai_advisor/isolated_smoke_runner.py
backend/ai_advisor/openai_sdk_transport.py
backend/ai_advisor/production_composition.py
backend/ai_advisor/prompt_builder.py
backend/ai_advisor/prompt_models.py
backend/ai_advisor/response_parser.py
docs/ai_advisor/01_AI_Advisor_Role_Permission_and_Safety_Boundary_Specification.md
docs/ai_advisor/AI_ADVISOR_EXACT_RELEASE_MANIFEST_CANDIDATE.md
docs/ai_advisor/AI_ADVISOR_RELEASE_CONTENT_CANDIDATE.md
docs/ai_advisor/AI_ADV_1F_BATCH2_PRODUCTION_RUNBOOK.md
docs/ai_advisor/FINAL_OFFLINE_PRODUCTION_READINESS_PACKAGE.md
docs/ai_advisor/PRODUCTION_CONFIGURATION_MATRIX_CANDIDATE.md
docs/ai_advisor/systemd-credential-smoke-runbook.md
frontend/src/components/ai-advisor/AdvisorConversation.test.js
frontend/src/features/ai-advisor/conversation/advisorBrowserGatewayClient.test.js
tests/test_ai_advisor_isolated_smoke_runner.py
tests/test_ai_advisor_openai_sdk_compatibility.py
tests/test_ai_advisor_openai_sdk_transport.py
tests/test_ai_advisor_production_composition.py
tests/test_ai_advisor_prompt_builder.py
tests/test_ai_advisor_response_security.py
tests/test_ai_advisor_response_validation.py
tests/test_ai_advisor_service.py
```

The following required path is `tracked-deleted`; deletion is part of the
candidate and the obsolete example must not be restored or treated as a current
unit:

```text
deploy/systemd/tradingai-ai-advisor-smoke.service.example
```

The following six required paths are `untracked-new`:

```text
backend/ai_advisor/provider_failure_observation.py
deploy/systemd/tradingai-ai-advisor-live-validation.service
docs/01_AI_Advisor_Master_Specification.md
docs/01_AI_Advisor_Role_Permission_and_Safety_Boundary_Specification.md
tests/test_ai_advisor_provider_failure_observation.py
tests/test_ai_advisor_systemd_unit_contract.py
```

All other paths in the required Backend, Frontend, Tests, Documentation, and
shared-file lists were `tracked-unchanged` in the committed RC delta. This
yields the exact committed required set: 110 unique paths total — 24
`tracked-modified`, 1
`tracked-deleted`, 6 `untracked-new`, and 79 `tracked-unchanged`.

### Required transient unit contract

```text
deploy/systemd/tradingai-ai-advisor-live-validation.service
docs/ai_advisor/systemd-credential-smoke-runbook.md
```

## Shared required files and hunk ownership

| Relative path | State | Hunks | AI Advisor | Other | Mixed | Separation | Purpose |
|---|---|---:|---:|---:|---:|---|---|
| `backend/main.py` | tracked-unchanged | 0 | 0 | 0 | 0 | PATH_PRESENT | imports; route/composition registration |
| `requirements.txt` | tracked-unchanged | 0 | 0 | 0 | 0 | PATH_PRESENT | `openai==2.48.0` |
| `frontend/src/App.jsx` | tracked-unchanged | 0 | 0 | 0 | 0 | PATH_PRESENT | Advisor route WebSocket isolation |
| `frontend/src/App.test.js` | tracked-unchanged | 0 | 0 | 0 | 0 | PATH_PRESENT | App isolation coverage |
| `frontend/src/api/index.js` | tracked-unchanged | 0 | 0 | 0 | 0 | PATH_PRESENT | safe env access and coarse runtime path |
| `frontend/src/runtime/websocketRuntime.js` | tracked-unchanged | 0 | 0 | 0 | 0 | PATH_PRESENT | explicit stop/reconnect suppression |
| `frontend/src/runtime/websocketRuntime.test.js` | tracked-unchanged | 0 | 0 | 0 | 0 | PATH_PRESENT | WebSocket isolation regression |

The shared dependencies are already present at Base HEAD and have no current
working-tree delta. They remain required runtime/test dependencies, but this
candidate does not stage them as changes.

## Optional files

The following optional deployment examples are `tracked-unchanged` and are
never auto-installed:

```text
deploy/nginx/ai-advisor-browser-gateway.conf.example
deploy/systemd/tradingbot-loopback.override.conf.example
```

The Live Validation mirror is not optional in this manifest: it is included in
the required transient-unit contract above. The previously referenced
`docs/00_TradingAI_Platform_Master_Specification.md` is absent and is not part
of this candidate.

## Explicit exclusions

| Relative path | State | Classification | Dependency conflict |
|---|---|---|---|
| `backend/utils/log_buffer.py` | tracked-modified | OTHER_WORK_EXCLUDED | No |
| `docs/01_Market_Recorder_Master_Specification.md` | untracked-new | MARKET_RECORDER_EXCLUDED | No |
| `frontend/dist/index.html` | tracked-modified | BUILD_ARTIFACT_EXCLUDED | No |

Money Management, Market Recorder, Execution Marker, Dashboard, and all paths
not explicitly listed in this manifest are outside the release boundary.
No excluded file is required to make the exact AI Advisor candidate internally
testable. The 34 dirty paths are therefore not equivalent to release content.
No credential value, secret, raw response, or raw journal is release content.

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
| `docs/ai_advisor/01_AI_Advisor_Role_Permission_and_Safety_Boundary_Specification.md` | tracked-modified | 1.1 | Required | Current candidate |
| `docs/09_AI_Advisor_Master_Specification.md` | tracked-unchanged | 0.2 | Required | Present at Base HEAD |
| `docs/01_AI_Advisor_Master_Specification.md` | untracked-new | 1.0 | Required | Current top-level baseline candidate |
| `docs/01_AI_Advisor_Role_Permission_and_Safety_Boundary_Specification.md` | untracked-new | current copy | Required | Current root-level candidate |
| `docs/ai_advisor/AI_ADV_1F_BATCH2_PRODUCTION_RUNBOOK.md` | tracked-modified | Release candidate runbook | Required | Current candidate |

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
- Production Readiness: passed for preparation; no Production authority.
- Live Preflight: passed.
- Live Validation 03: `INCONCLUSIVE / EXECUTION_PROCEDURE_GAP`; not passed and
  not live-validated.
- Safe Result Runbook: passed static final review.

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
2. Review the 24 exact `tracked-modified` paths and stage only the approved
   candidate content.
3. Review and stage the one exact `tracked-deleted` path as a deletion; never
   restore the obsolete unit example.
4. Review and stage the six exact `untracked-new` required paths.
5. Do not stage any `tracked-unchanged` dependency. Stage optional paths only
   when each is separately named in the approval.
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
