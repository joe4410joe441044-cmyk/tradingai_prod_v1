# AI Advisor Release Content Candidate

Status: `CANDIDATE_ONLY`
Base HEAD: `7a936851bd44bdc5adf004ed8437b7849f9e70c6`
Runtime activation: `false`
Production deployment: `not authorized`

## Required release content

| Category | Relative path | State | Dependency / coverage |
|---|---|---|---|
| Backend | `backend/ai_advisor/*.py` | New | Complete Advisor contracts, safety, provider, runtime and gateway implementation; `tests/test_ai_advisor_*.py` |
| Backend route | `backend/api/ai_advisor.py` | New | Bearer-protected runtime and advice routers |
| Shared application | `backend/main.py` | Modified | Router composition and fail-closed gateway middleware; shared file requires line-level review |
| Requirement | `requirements.txt` | Modified | OpenAI SDK pin; provider compatibility tests and `pip check` |
| Frontend components | `frontend/src/components/ai-advisor/*` | New | Component node tests |
| Frontend features | `frontend/src/features/ai-advisor/*` | New | Gateway/runtime clients, models, hooks and node tests |
| Frontend page | `frontend/src/pages/AIAdvisorPage.jsx` | Modified | Page tests |
| Frontend page test | `frontend/src/pages/AIAdvisorPage.test.js` | Modified | Page regression |
| Frontend style | `frontend/src/styles/ai-advisor.css` | Modified | Isolated Vite build |
| Shared frontend | `frontend/src/App.jsx`, `frontend/src/App.test.js` | Modified | Navigation/route integration; shared files require line-level review |
| Shared frontend API | `frontend/src/api/index.js` | Modified | Same-origin coarse runtime route; API client tests |
| Shared runtime | `frontend/src/runtime/websocketRuntime.js`, `frontend/src/runtime/websocketRuntime.test.js` | Modified/New | Runtime integration tests; shared file requires line-level review |
| Tests | `tests/test_ai_advisor_*.py` | New | Full AI Advisor offline suite |
| Master docs | `docs/00_TradingAI_Platform_Master_Specification.md`, `docs/09_AI_Advisor_Master_Specification.md` | New | Release documentation; currently uncommitted |
| Advisor docs | `docs/ai_advisor/*` | New | Contracts, runbooks and candidate manifests |

The file globs above are release-set notation only. An operator must expand them
against the reviewed working tree and approve every resulting relative path
before staging.

## Optional deployment examples

| Relative path | State | Rule |
|---|---|---|
| `deploy/nginx/ai-advisor-browser-gateway.conf.example` | New | Optional candidate; never auto-install |
| `deploy/systemd/tradingai-ai-advisor-smoke.service.example` | New | Optional candidate; never auto-install |
| `deploy/systemd/tradingbot-loopback.override.conf.example` | New | Optional candidate; explicit bind-change approval |

## Explicit exclusions

- `Bot/engine/execution_engine.py`
- `backend/bot_manager/bot_manager.py`
- `backend/execution/execution_marker.py`
- `tests/test_paper_execution_markers.py`
- `docs/01_Money_Management_Master_Specification.md`
- `docs/01_Money_Management_Specification_Additions_v1.1.md`
- `docs/08_Dashboard_Redesign_Specification.md`
- `frontend/dist/index.html`

No excluded change may be staged, restored, reformatted or deleted as part of
the AI Advisor release.

## Shared-file separation

`backend/main.py`, `requirements.txt`, `frontend/src/App.jsx`,
`frontend/src/App.test.js`, `frontend/src/api/index.js`,
`frontend/src/runtime/websocketRuntime.js`, and its test require an operator
line-level diff review. The current audit found AI Advisor-related hunks, but
the dirty working tree is not authoritative ownership evidence.

## Test baseline

- Backend full suite: at least 581 passing tests.
- Backend AI Advisor suite: all `tests/test_ai_advisor_*.py` tests pass.
- Frontend suite: at least 280 passing tests.
- `py_compile`, Black, targeted ESLint, `pip check`, and `git diff --check`
  must pass.
- Frontend must build only into a temporary directory during approval.

## Known findings and production blockers

- The complete release remains uncommitted.
- Production Uvicorn currently binds to `0.0.0.0:8001`.
- Nginx trusted-proxy authentication is not installed.
- Direct external reachability is unverified.
- Knowledge sources are not eligible until committed and separately approved.
- External-context and systemd credential approvals remain separate gates.

## Rollback scope

Rollback must cover the approved application commit, AI Advisor environment
configuration, optional Nginx/systemd changes, credential attachment, and all
AI Advisor enablement flags. Rollback must not alter the explicitly excluded
Money Management, Execution Marker, Dashboard or tracked frontend distribution
changes.
