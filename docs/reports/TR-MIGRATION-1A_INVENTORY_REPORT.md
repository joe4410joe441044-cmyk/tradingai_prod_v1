# TR-MIGRATION-1A: Google Cloud Migration Inventory Report

**Task ID:** TR-MIGRATION-1A
**Date:** 2026-08-02
**Source:** Google Cloud (tradingai-prod-v1)
**Destination:** New Contabo Cloud VPS 8 (not yet connected)
**Status:** INVENTORY COMPLETE

---

## 1. Safety Verification

| Check | Value |
|---|---|
| Working Directory | `/home/joe4410joe/tradingai_prod_v1` |
| Hostname | `tradingai-prod-v1` |
| User | `joe4410joe` |
| Platform | Linux |
| Branch | `main` |
| HEAD | `d57de0439576c1134a67ce6055f65fc4a1c084e0` |
| Upstream | up to date with `origin/main` |
| No copy/delete/commit | CONFIRMED |

---

## 2. Repository Inventory

### 2.1 Top-Level Directory Structure

```
/home/joe4410joe/tradingai_prod_v1/
├── .agents/                 # OpenCode agents config
├── .codex/                  # Codex config
├── .git/                    # Git repo (40M)
├── .gitattributes
├── .gitignore
├── .env                     # Production env (SECRETS - not tracked)
├── .ipynb_checkpoints/      # Jupyter checkpoints
├── backend/                 # Backend Python application (5.2M)
├── Bot/                     # Trading bot core (640K)
├── deploy/                  # Deployment configs (28K)
├── docs/                    # Documentation (752K)
├── dryrun_logs/             # Dry-run CSV logs (20K)
├── frontend/                # React frontend (185M total, 2.4M src)
├── Live/                    # Telegram bot (36K)
├── logs/                    # Runtime logs (25M)
├── monitoring/              # System monitoring scripts
├── node_modules/            # Root node_modules (20K)
├── scripts/                 # Utility scripts (8K)
├── systemd/                 # Systemd unit files (8K)
├── tests/                   # Test suite (4.0M)
├── tmp/                     # Temporary files (16M)
├── tools/                   # Shell tool scripts (72K)
├── trading_dashboard_old/   # Legacy dashboard (68K)
├── venv/                    # Python virtual env (402M)
├── requirements.txt         # Python dependencies
├── package.json             # Root npm config
├── package-lock.json
├── sample.env               # Env template
├── bot_run.py               # Bot entrypoint
├── config.py                # Legacy config (tracked as deleted)
├── test_orderbook.py        # Standalone test
├── lot_calculator.ipynb     # Jupyter notebook
├── Untitled.ipynb
├── frontend_tree.txt        # Tree dump (567K)
├── structure.txt            # Structure notes (2K)
├── build.log                # Build log
├── monitor.log              # Monitor log
└── (misc root files: 0, 5, BEST, sage, ervice..., udo...)
```

### 2.2 Key Component Details

#### Backend (`backend/` - 5.2M)
| Module | Size | Description |
|---|---|---|
| `money_management/` | 1.4M | Loss-based money management system |
| `ai_advisor/` | 1.0M | AI Advisor service (OpenAI integration) |
| `bot_manager/` | 652K | Bot lifecycle management |
| `runtime/` | 280K | Runtime governance & coordination |
| `execution/` | 208K | Trade execution pipeline |
| `api/` | 188K | FastAPI routes (incl. recorder_proxy) |
| `market/` | 184K | Market data processing |
| `core/` | 152K | Core domain logic |
| `ai/` | 116K | AI/ML pipeline (LSTM, LLM, features) |
| `services/` | 100K | Service layer (http, recorder_proxy) |
| `routers/` | 76K | API routers |
| `aggregation/` | 76K | Market data aggregation |
| `strategy/` | 68K | Trading strategies |
| `ws/` | 60K | WebSocket handlers |
| `cluster/` | 56K | Clustering logic |
| `protection/` | 52K | Safety/protection |
| `scripts/` | 48K | Backend scripts |
| `portfolio/` | 44K | Portfolio management |
| `clients/` | 40K | API clients |
| `models/` | 36K | Data models |
| `storage/` | 32K | Persistence layer |
| `exchange/` | 32K | Exchange adapters |
| `config/` | 32K | New config package (replaces config.py) |
| `utils/` | 28K | Utilities |
| `schemas/` | 28K | Pydantic schemas |
| `websocket/` | 20K | WebSocket infrastructure |
| `common/` | 16K | Shared common code |
| `__pycache__/` | 140K | Python cache |

#### Frontend (`frontend/` - 185M total)
| Path | Size | Description |
|---|---|---|
| `node_modules/` | 180M | NPM packages (REGENERATE) |
| `src/` | 2.4M | React source code |
| `dist/` | 1.0M | Production build (REGENERATE) |
| `artifacts/` | 676K | UI/visual artifacts |
| `backup_dist/` | 232K | Old build backup |
| `backup_dist_20260423/` | 232K | Old build backup |
| `e2e/` | 64K | Playwright E2E tests |
| `public/` | 28K | Static assets |
| `_legacy_hooks/` | 24K | Deprecated React hooks |
| `deploy/` | 16K | Frontend deploy scripts |
| `tmp/` | 8K | Frontend temp |
| `.env.production` | - | Vite env config |
| `package.json` | - | React 19 + Vite 8 |
| `package-lock.json` | - | Lockfile |

#### Bot (`Bot/` - 640K)
| Module | Description |
|---|---|
| `TradeCore/` | Trading core (signals, equity curve, trade/signal/bot logs) |
| `ai/` | AI risk filter |
| `api/` | AI router |
| `control/` | Bot state, command handler, telegram controller, duplicate guard |
| `core/` | Trade core, risk manager, price manager, position sizer |
| `datafeeds/crypto/` | Binance feed |
| `engine/` | Execution engine, market engine |
| `exchanges/` | Base exchange, mock exchange |
| `market/` | Candle buffer |
| `monitoring/` | AI logger |
| `strategies/` | FVG, RSI, simple strategies |
| `utils/` | Logger, multi-timeframe, safety, telegram notifier |
| `wrappers/` | Strategy wrapper, test signal generator |
| `dev_main.py` | Dev entrypoint |

#### Tests (`tests/` - 4.0M)
- AI Advisor tests: 25 files (api, security, browser, provider, runtime, etc.)
- Money Management tests: 22 files (loss, execution, runtime, persistence, etc.)
- Recorder Proxy tests: 6 files (client, config, dto, route, service, url_builder)
- Bot tests: 2 files (integration, system)
- Exchange tests: 3 files (live status, orderbook, market payload)
- Telegram tests: 1 file (disabled security)
- Runtime tests: 3 files (ws, health snapshot, ai debug)

#### Docs (`docs/` - 752K)
| Directory | Description |
|---|---|
| `00_CONSTITUTION/` | Project constitution, glossary, DDR, principles, ChatGPT template, init |
| `ai_advisor/` | AI Advisor specs, runbooks, manifest, config matrix |
| `data_model/` | Data model spec (chapters 1-9) |
| `market_intelligence/` | Market Intelligence UI spec |
| `market_recorder/` | Market Recorder specs & reports |
| `money_management/` | Money Management specs |
| `opencode/` | OpenCode dev standards v1.0, v2.0 |
| `reports/` | Project reports |
| `visual_guideline/` | Visual design guidelines (chapters 1-12) |
| `00_SPEC_INDEX.md` | Spec index |

#### Other Directories
| Directory | Size | Description |
|---|---|---|
| `systemd/` | 8K | `tradingbot.service` unit file |
| `deploy/` | 28K | nginx config, systemd unit templates |
| `Live/` | 36K | Telegram bot (production, monitor, UI, utils) |
| `tools/` | 72K | Shell scripts (build,check,deploy,health,logs,start,stop,restart,status) + position_calculator.py + validate_stopped_paper_snapshot.py |
| `scripts/` | 8K | `test_system.py` |
| `monitoring/` | - | `system_monitor.py`, `test_monitor.py` |
| `trading_dashboard_old/` | 68K | Legacy dashboard (possibly unused) |

---

## 3. Git Status Survey

### 3.1 Tracked Modified (16 files)
```
 M backend/ai_advisor/runner_process_detection.py
 M backend/main.py
 M backend/utils/log_buffer.py
 M docs/ai_advisor/AI_ADVISOR_EXACT_RELEASE_MANIFEST_CANDIDATE.md
 M docs/ai_advisor/systemd-credential-smoke-runbook.md
 M frontend/dist/index.html
 M frontend/e2e/runtime-health.spec.js
 M frontend/src/App.jsx
 M frontend/src/components/AppNavigation.jsx
 M frontend/src/components/runtime/AccountRuntimeOverview.jsx
 M frontend/src/main.jsx
 M frontend/src/pages/Dashboard.jsx
 M frontend/src/styles/dashboard.css
 M tests/test_ai_advisor_runner_process_detection.py
 M tests/test_ai_advisor_systemd_unit_contract.py
```

### 3.2 Tracked Deleted (35 files)
```
 D backend/config.py
 D docs/01_AI_Advisor_Master_Specification.md           → docs/ai_advisor/
 D docs/01_MARKET_INTELLIGENCE_UI_SPEC_v1.0.md          → docs/market_intelligence/
 D docs/01_Money_Management_Master_Specification.md      → docs/money_management/
 D docs/01_Money_Management_Specification_Additions_v1.1.md → docs/money_management/
 D docs/02_MARKET_INTELLIGENCE_COMPONENT_SPEC.md        → docs/market_intelligence/
 D docs/03_MARKET_INTELLIGENCE_INTERACTION_SPEC.md       → docs/market_intelligence/
 D docs/03_MARKET_INTELLIGENCE_INTERACTION_SPEC_PART_A-D.md → docs/market_intelligence/
 D docs/04_VISUAL_GUIDELINE.md                          → docs/visual_guideline/
 D docs/04_VISUAL_GUIDELINE_CHAPTER_01-12.md            → docs/visual_guideline/
 D docs/05_DATA_MODEL_SPEC.md                           → docs/data_model/
 D docs/05_DATA_MODEL_SPEC_CHAPTER_01-09.md              → docs/data_model/
 D docs/09_AI_Advisor_Master_Specification.md           → docs/ai_advisor/
```

**Note:** These are doc restructuring moves (deleted from old paths, re-added as untracked in new subdirectories).

### 3.3 Untracked (28 items)
```
?? backend/api/recorder_proxy.py
?? backend/config/                                        # New config package
?? backend/models/recorder_proxy.py
?? backend/services/http/                                 # HTTP client + URL builder
?? backend/services/recorder_proxy/                       # Recorder proxy service
?? docs/00_CONSTITUTION/                                  # New constitution docs
?? docs/OpenCode_User_Quick_Guide.md
?? docs/ai_advisor/*.md (relocated)                       # Relocated spec docs
?? docs/data_model/*.md (relocated)
?? docs/market_intelligence/*.md (relocated)
?? docs/market_recorder/*.md                              # New recorder docs
?? docs/money_management/*.md (relocated)
?? docs/opencode/*.md                                     # New OpenCode standards
?? docs/reports/TR-RECORDER-UI-1E_REPORT.md
?? docs/visual_guideline/*.md (relocated)
?? frontend/RT-UI-1A_REPORT.md
?? frontend/src/components/runtime/RuntimeDiagnosticsDisclosure.jsx
?? frontend/src/components/runtime/RuntimeDiagnosticsDisclosure.test.js
?? frontend/src/features/market-recorder/                 # New recorder UI feature
?? frontend/src/pages/MarketRecorderPage.jsx
?? frontend/src/styles/market-recorder.css
?? tests/test_recorder_proxy_*.py                         # 6 new test files
```

### 3.4 Submodules & LFS
- **Submodules:** None
- **Git LFS:** Not configured

### 3.5 .gitignore Coverage
Key exclusions confirmed:
- `.env`, `.env.*` - Secrets
- `venv/`, `.venv/` - Virtual environments
- `__pycache__/`, `*.pyc` - Python cache
- `node_modules/` - NPM packages
- `logs/`, `*.log` - Logs
- `tmp/`, `temp/` - Temp files
- `dist/`, `build/` - Build artifacts
- `react_dashboard/dist/`, `backup_dist/` - Frontend builds
- `*.bak`, `*.bak_*`, `*.bak_step*` - Backup files
- `dryrun_logs/` - Dry-run data
- `trading_logs/`, `execution_logs/` - Trading logs
- `.vscode/`, `.idea/` - Editor configs

---

## 4. Environment Inventory

### 4.1 Python
- **Version:** Python 3.11.2
- **Virtual Env:** `venv/` (402M) at project root
- **Dependencies (system pip):** binance, fastapi, uvicorn, pydantic, websockets, aiohttp, python-dotenv, etc.
- **Requirements:** `requirements.txt` at project root (binary file, cannot read as text)

### 4.2 Node.js
- **Node:** v20.20.2
- **NPM:** 10.8.2
- **Frontend package.json:** React 19.2.4, Vite 8.0.1, Recharts 3.8.1, Playwright 1.61.1
- **Root package.json:** Minimal (no dependencies)
- **Lockfiles:** `package-lock.json` (both root and frontend/)

### 4.3 Key Files
| File | Location | Notes |
|---|---|---|
| `requirements.txt` | Root | Python deps (binary) |
| `package.json` | Root | Minimal npm config |
| `frontend/package.json` | Frontend | React app config |
| `frontend/package-lock.json` | Frontend | NPM lockfile |
| `sample.env` | Root | Env template |
| `.env` | Root | **Contains API keys/secrets** |
| `frontend/.env.production` | Frontend | Vite prod config |

### 4.4 Docker
- **No Dockerfiles detected**
- **No docker-compose files detected**
- **No .dockerignore detected**

---

## 5. Directory Size Survey

### 5.1 Working Tree (excluding .git)

| Directory/File | Size | Category |
|---|---|---|
| `venv/` | 402M | B (Regenerate) |
| `frontend/node_modules/` | 180M | B (Regenerate) |
| `logs/` | 25M | C (Review) |
| `tmp/` | 16M | C (Review) |
| `backend/` | 5.2M | A (Migrate) |
| `tests/` | 4.0M | A (Migrate) |
| `frontend/src/` | 2.4M | A (Migrate) |
| `frontend/dist/` | 1.0M | B (Regenerate) |
| `docs/` | 752K | A (Migrate) |
| `frontend/artifacts/` | 676K | A (Migrate) |
| `Bot/` | 640K | A (Migrate) |
| `frontend_tree.txt` | 567K | C (Review) |
| `frontend/backup_dist*/` | 464K | B (Regenerate) |
| `frontend/e2e/` | 64K | A (Migrate) |
| `tools/` | 72K | A (Migrate) |
| `trading_dashboard_old/` | 68K | C (Review) |
| `Live/` | 36K | A (Migrate) |
| `frontend/public/` | 28K | A (Migrate) |
| `deploy/` | 28K | A (Migrate) |
| `frontend/_legacy_hooks/` | 24K | A (Migrate) |
| `node_modules/` (root) | 20K | B (Regenerate) |
| `dryrun_logs/` | 20K | C (Review) |
| `frontend/deploy/` | 16K | A (Migrate) |
| `systemd/` | 8K | A (Migrate) |
| `scripts/` | 8K | A (Migrate) |
| `.env` + `.env.*` | ~2K | C (Review - SECRETS) |
| `__pycache__/` (all) | ~35M | B (Regenerate) |

### 5.2 Total Summary

| Metric | Size |
|---|---|
| Total repository | 678M |
| .git directory | 40M |
| Working tree (no .git) | 638M |
| **Category A: Must Migrate** | **~12-15M** |
| Category B: Regenerate | ~620M |
| Category C: Needs Review | ~42M |

---

## 6. Migration Classification

### Category A: Must Migrate (Source Code & Config)

```
backend/              # Full backend application (5.2M)
  ├── api/            # FastAPI routes (incl. recorder_proxy)
  ├── ai_advisor/     # AI Advisor service
  ├── ai/             # AI/ML pipeline
  ├── money_management/ # Loss-based money management
  ├── runtime/        # Governance runtime
  ├── execution/      # Order execution
  ├── market/         # Market data
  ├── bot_manager/    # Bot lifecycle
  ├── config/         # New config module
  ├── services/       # Service layer (http, recorder_proxy)
  ├── models/         # Data models
  └── ... (all submodules)

frontend/src/         # React source (2.4M)
frontend/e2e/         # E2E tests (64K)
frontend/public/      # Static assets (28K)
frontend/index.html   # Entry HTML
frontend/vite.config.js
frontend/playwright.config.js
frontend/eslint.config.js
frontend/package.json
frontend/package-lock.json
frontend/_legacy_hooks/  # Deprecated code (24K)
frontend/artifacts/      # UI artifacts (676K)

Bot/                  # Trading bot (640K)
Live/                 # Telegram bot (36K)
tests/                # Test suite (4.0M)
docs/                 # Documentation (752K)
scripts/              # Utility scripts (8K)
systemd/              # Systemd units (8K)
deploy/               # Deploy configs (28K)
tools/                # Shell tools (72K)
monitoring/           # Monitoring scripts

package.json          # Root npm config
package-lock.json
requirements.txt      # Python deps
sample.env            # Env template
bot_run.py            # Bot entrypoint
```

### Category B: Regenerate (Build/Runtime Artifacts)

```
venv/                 (402M)  → pip install -r requirements.txt
frontend/node_modules/ (180M) → npm install
__pycache__/ all      (~35M)  → Auto-generated on import
frontend/dist/        (1.0M)  → npm run build
frontend/backup_dist/ (232K)  → Not needed
frontend/backup_dist_20260423/ (232K) → Not needed
node_modules/ root    (20K)   → npm install (if needed)
*.pyc files                    → Auto-generated
.pytest_cache/                 → Auto-generated
```

### Category C: Needs Review (Secrets/Data/Confirm)

```
.env                                    # ★ CRITICAL: Contains API keys, secrets
.env.* (frontend/.env.production)       # Vite build config (keep)
logs/tradingai.log                      # 4.9M (live log - reference only)
logs/tradingai.log.1/2/3               # 26M total (rotated logs - archive?)
logs/runtime/                           # Runtime diagnostic logs (16K)
tmp/chatgpt_reviews/                    # Previous ChatGPT review reports (80K)
tmp/chatgpt_review.md                   # (4K)
tmp/phase5-*/                           # Previous task artifacts (16M)
dryrun_logs/                            # Bot CSV logs (20K)
trading_dashboard_old/                  # Legacy code (68K - keep for reference?)
frontend_tree.txt                       # 567K tree dump (probably stale)
structure.txt                           # 2K structure notes (probably stale)
build.log / monitor.log                 # Build/monitor logs (small)
misc root files (0, 5, BEST, ervice..., udo...) # Artifacts/garbage (?)
```

---

## 7. Estimated Transfer Size (Package Plan)

### 7.1 Size Calculation

| Layer | Subtract | Remaining |
|---|---|---|
| Total repository | - | 678M |
| ─ .git | 40M | 638M |
| ─ venv (B) | 402M | 236M |
| ─ node_modules (B) | 180M | 56M |
| ─ logs (C) | 25M | 31M |
| ─ tmp (C) | 16M | 15M |
| ─ __pycache__ (B) | ~3M | 12M |
| ─ dist/backup_dist (B) | 1.5M | 10.5M |
| ─ misc logs/build artifacts | 0.5M | ~10M |

### 7.2 Recommendation

**Estimated transfer size: ~10-15 MB** (Category A only)

Given this small size, **tar.gz is recommended** over rsync for the initial transfer:
- Simpler: single archive, easy to verify
- Efficient: text/source compresses well (~3-5MB compressed)
- Atomic: no partial state risk
- Verifiable: sha256sum check

**rsync** should be used for subsequent incremental syncs after the initial migration.

**Package Plan** (for next task TR-MIGRATION-2):
1. Exclude: venv/, node_modules/, logs/, tmp/, __pycache__/, dist/, backup_dist/, build.log, monitor.log, *.pyc, dryrun_logs/, frontend_tree.txt
2. Include: All Category A paths
3. Handle separately: .env secrets, logs for reference

---

## 8. Findings & Notes

### 8.1 Critical Concerns

1. **`.env` contains live API keys/secrets** (Binance, Bitget, KuCoin, Bybit, Telegram). Must NOT be transferred as-is. New `.env` must be created on destination manually.

2. **Docs restructuring in progress**: 35 files deleted from old locations, same files re-added untracked in new subdirectories (market_intelligence/, visual_guideline/, data_model/, money_management/). This is intentional reorganization, not accidental deletion. Note: git history will show these as delete+new rather than move.

3. **Recorder Proxy is untracked**: New feature (backend + frontend + tests) not yet committed. Must be included in migration.

4. **No Docker**: The application runs directly via systemd, not containerized. Destination needs matching Python/Node/systemd setup.

5. **systemd service references old path**: `tradingbot.service` points to `/home/joe4410joe/TradingAI_Bot_Prod_v1/` (different directory name). Must update on destination.

### 8.2 Source of Truth Verification

- Current working directory matches repository path
- Branch `main` is cleanly on `origin/main`
- No stashed changes, no detached HEAD

### 8.3 Miscellaneous Observations

- Root directory contains some garbage files (`0`, `5`, `BEST`, `sage`, `ervice -n 100 --no-pager`, `udo systemctl restart tradingai`) - likely command-line artifacts
- `frontend_tree.txt` (567K) is a stale tree dump and is gitignored (`.txt` not in gitignore, but probably was committed early on)
- `venv/` is at project root (unusual - typically in project root or `.venv/`). Note the systemd file references `venv/` at root level
- No CI/CD configuration detected (no `.github/workflows/`, `.gitlab-ci.yml`, etc.)
- `Live/` contains Telegram bot production code - this is a separate bot process
- `trading_dashboard_old/` may be an old prototype - confirm with team before excluding

---

## 9. Ready for Packaging

```
[✓] Inventory complete
[✓] Size estimated (~10-15 MB transfer)
[✓] Categories classified (A/B/C)
[✓] Git state documented
[✓] Environment documented
[✓] No files modified during inventory
[✓] No commits made
[✓] No push performed
```

**Next Task:** TR-MIGRATION-2 - Create tar.gz package and prepare for transfer.

---

## 10. Git Safety Confirmation

| Rule | Status |
|---|---|
| No git add | ✓ CONFIRMED |
| No git commit | ✓ CONFIRMED |
| No git push | ✓ CONFIRMED |
| No git restore | ✓ CONFIRMED |
| No git reset | ✓ CONFIRMED |
| No git clean | ✓ CONFIRMED |
| No scp/rsync/cp/mv/rm | ✓ CONFIRMED |
| No tar/zip | ✓ CONFIRMED |
| No systemctl/docker | ✓ CONFIRMED |
| No build/install | ✓ CONFIRMED |
| Repository unchanged | ✓ CONFIRMED |

---

*Report generated: 2026-08-02 | Task TR-MIGRATION-1A*
