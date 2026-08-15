# MR-RECORDER-INTEGRATION-1 Recorder Integration Readiness Audit

**Version:** 1.0
**Status:** Complete
**Task ID:** MR-RECORDER-INTEGRATION-1
**Date:** 2026-08-02
**Repository:** `/home/joe4410joe/tradingai_prod_v1`
**Branch:** `main`

> This is a READ-ONLY audit. No code was modified, committed, or pushed.

---

## Executive Summary

The Market Recorder system has **11 integration points** between 6 subsystems. Of these, **3 are fully implemented but not connected**, **3 have contracts defined but no implementation**, and **5 are completely missing**. The Frontend UI → Backend Proxy connection is structurally complete but fail-closed. The core recording pipeline (Runtime → Storage) is entirely missing. This report maps every integration point, identifies exact file:line references, and recommends a safe implementation order.

---

## 1. Current Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LEGEND:  ✓ COMPLETE  ○ PARTIAL  ✗ NOT STARTED                              │
│           ═══ CONNECTED  - - → NOT CONNECTED  ══○══ PROXY STANDING BY       │
└─────────────────────────────────────────────────────────────────────────────┘

                        ✓ FRONTEND (Google Cloud)
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                           │
│  App.jsx:53  ──>  MarketRecorderPage.jsx                                 │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  UI Cards: Status | Storage | Archives                              │ │
│  │                                                                      │ │
│  │  Recorder Control: [START] disabled  [STOP] disabled                 │ │
│  │                                                                      │ │
│  │  Archives Table:  [DOWNLOAD] disabled  [DELETE] disabled             │ │
│  │    (both throw RECORDER_NOT_IMPLEMENTED in client)                   │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────────┐                 │
│  │ useRecorder  │  │ useRecorder   │  │ useRecorder    │                 │
│  │ Status()     │  │ Storage()     │  │ Archives()     │                 │
│  └──────┬───────┘  └───────┬───────┘  └───────┬────────┘                 │
│         └──────────────────┼──────────────────┘                          │
│                            ▼                                              │
│                ┌─────────────────────────┐                                │
│                │  recorderAdapters.js    │  (ViewModel mapping)           │
│                └───────────┬─────────────┘                                │
│                            ▼                                              │
│                ┌─────────────────────────┐                                │
│                │  recorderClient.js      │  (GET-only fetch client)       │
│                │  + recorderApiDtos.js   │  (DTO validation)              │
│                └───────────┬─────────────┘                                │
│                            │                                              │
│           SOURCE: mock     │     SOURCE: api                              │
│           (default)        │     (requires VITE_RECORDER_API_BASE_URL)    │
│           mockRecorderData │       │                                      │
│           (1 status,       │       ▼                                      │
│            1 storage,      │   getHealth()                                │
│            5 archives)     │   getStatus()                                │
│                            │   getStorage()                               │
│                            │   getArchives(query)                         │
│                            │   start()    → NOT_IMPLEMENTED               │
│                            │   stop()     → NOT_IMPLEMENTED               │
│                            │   download() → NOT_IMPLEMENTED               │
│                            │   delete()   → NOT_IMPLEMENTED               │
└────────────────────────────┼──────────────────────────────────────────────┘
                             │
                             │  Same-Origin: /api/market-recorder/*
                             │  (same host, via nginx)
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ✓ BACKEND RECORDER PROXY (Google Cloud, 127.0.0.1:8001)                  │
│                                                                           │
│  main.py:1365-1367                                                        │
│    └── app.include_router(create_recorder_proxy_router())                 │
│                                                                           │
│  Route Layer (backend/api/recorder_proxy.py)                             │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ GET /api/market-recorder/health    → get_health()                   │ │
│  │ GET /api/market-recorder/status    → get_status()                   │ │
│  │ GET /api/market-recorder/storage   → get_storage()                  │ │
│  │ GET /api/market-recorder/archives  → get_archives(query)            │ │
│  │                                                                      │ │
│  │ NO: POST, PUT, DELETE, PATCH, START, STOP, CONTROL                  │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  Service Layer (backend/services/recorder_proxy/service.py)              │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ RecorderProxyService                                                │ │
│  │   ├─ _ensure_ready()      → config check, fail-closed              │ │
│  │   ├─ _make_client()       → RecorderReadOnlyClient                  │ │
│  │   ├─ _fetch()             → client GET + envelope/DTO validation    │ │
│  │   ├─ get_health()         → validate_no_query → _fetch("health")    │ │
│  │   ├─ get_status()         → validate_no_query → _fetch("status")    │ │
│  │   ├─ get_storage()        → validate_no_query → _fetch("storage")   │ │
│  │   └─ get_archives()       → validate_archives_query → _fetch("..")  │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  Config (backend/config/recorder_proxy.py)                               │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ RECORDER_API_ENABLED    = false (default, fail-closed)              │ │
│  │ RECORDER_API_BASE_URL   = (NOT SET)                                 │ │
│  │ RECORDER_API_TIMEOUT    = 5.0  (default)                            │ │
│  │ RECORDER_API_VERIFY_TLS = true (default)                            │ │
│  │                                                                      │ │
│  │ When disabled: returns 503 "market_recorder_proxy_disabled"         │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  HTTP Client (backend/services/http/recorder_http_client.py)             │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ RecorderReadOnlyClient                                              │ │
│  │   ├─ get(endpoint_key, query_params) → httpx AsyncClient GET        │ │
│  │   ├─ 5 MiB response cap                                            │ │
│  │   ├─ No cookies/credentials/auth headers                            │ │
│  │   ├─ No redirects (follow_redirects=False)                          │ │
│  │   ├─ Timeout mandatory                                              │ │
│  │   └─ SSRF-safe URL builder (fixed allowlist only)                   │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  URL Builder (backend/services/http/recorder_url_builder.py)              │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ ENDPOINT_PATHS = {                                                  │ │
│  │   "health":   "/api/recorder/health",                              │ │
│  │   "status":   "/api/recorder/status",                              │ │
│  │   "storage":  "/api/recorder/storage",                             │ │
│  │   "archives": "/api/recorder/archives",                            │ │
│  │ }                                                                    │ │
│  │                                                                      │ │
│  │ Upstream URL = normalized(RECORDER_API_BASE_URL) + fixed_path       │ │
│  │ User input NEVER interpolated into URL                              │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  PROXY IS DISABLED                     PROXY IS ENABLED                  │
│  (current state)                       (future, requires config)         │
│  Returns 503                            │                                │
│                                         ▼                                │
│                              connect to RECORDER_API_BASE_URL            │
│                                         │                                │
└─────────────────────────────────────────┼────────────────────────────────┘
                                          │
                          - - - - - - - - | - - - - - - - -
                          NOT CONNECTED   |   NOT CONNECTED
                          (Contabo unreachable, base URL unknown)
                          - - - - - - - - | - - - - - - - -
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ✗ RECORDER RUNTIME (Contabo / /opt/market-recorder)                      │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ runtime_chain_recorder.py  →  EMPTY (0 bytes, no imports, no refs) │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  NOT IMPLEMENTED:                                                         │
│    ✗ MarketRecorder class                                                │
│    ✗ append_event(event)                                                 │
│    ✗ Sequence counter (global monotonic)                                 │
│    ✗ JSONL Active Writer (.jsonl.part, O_APPEND, fsync)                  │
│    ✗ Market normalizer (exchange-agnostic format)                        │
│    ✗ Hourly rotation                                                    │
│    ✗ Zstd compression (.jsonl.zst)                                      │
│    ✗ Manifest generation (.manifest.json)                               │
│    ✗ Manifest index (manifest_index.json)                               │
│    ✗ Snapshot / Gap Recovery                                             │
│    ✗ Health/Status/Storage/Archives API endpoints                       │
│    ✗ Data Access API (GET manifests, datasets, stream)                  │
│       (this is what the proxy routes would upstream to)                  │
│                                                                           │
│  NOT IMPLEMENTED - Event Recording Hooks:                                 │
│    ✗ Strategy Runtime → STRATEGY_DECISION events                        │
│    ✗ AI/LLM Runtime → AI_DECISION events                                │
│    ✗ Governance Runtime → GOVERNANCE_DECISION events                    │
│    ✗ Execution Runtime → ORDER_SUBMITTED/ACKNOWLEDGED/REJECTED          │
│    ✗ Position Tracker → POSITION_OPENED/UPDATED/CLOSED                  │
│    ✗ WebSocket feeds → MARKET_SNAPSHOT events (no normalizer)           │
│    ✗ Detectors → DETECTOR_SIGNAL events (detectors not implemented)     │
│                                                                           │
│  NOT IMPLEMENTED - Control Operations:                                    │
│    ✗ START recorder                                                      │
│    ✗ STOP recorder                                                       │
│    ✗ Configuration persistence                                           │
│ └──────────────────────────────────────────────────────────────────────────┘
                                          │
                          - - - - - - - - | - - - - - - - -
                          NOT CONNECTED   |   NOT CONNECTED
                          - - - - - - - - | - - - - - - - -
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ✗ STORAGE TIER (data/market_recorder/ — directory does NOT exist)        │
│                                                                           │
│  Specified but not created:                                               │
│    ✗ data/market_recorder/active/*.jsonl.part                            │
│    ✗ data/market_recorder/archive/*.jsonl.zst                            │
│    ✗ data/market_recorder/archive/*.jsonl.zst.manifest.json              │
│    ✗ data/market_recorder/snapshots/*.json.gz                            │
│    ✗ data/market_recorder/index/manifest_index.json                      │
│                                                                           │
│  Reference implementation exists (Money Management only):                 │
│    backend/money_management/timeline.py (607 lines)                       │
│    - JSONL write pattern: json.dumps + \n + O_APPEND + fsync             │
│    - Sequence counter, signature-based deduplication                      │
│    - NOT market recorder compatible (Money Management scope only)         │
└──────────────────────────────────────────────────────────────────────────┘
                                          │
                          - - - - - - - - | - - - - - - - -
                          NOT CONNECTED   |   NOT CONNECTED
                          - - - - - - - - | - - - - - - - -
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ✓ REPLAY SUBSYSTEM (Frontend only, fixture-based)                        │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ replayEngine.js (317 lines)                                         │ │
│  │   13 commands (LOAD_DATASET, PLAY, PAUSE, STEP, SEEK, RESTART...)  │ │
│  │   9 states (IDLE → POSITION_SELECTED → REPLAY_LOADING → ...)       │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ replayConstants.js                                                  │ │
│  │   12 event types (MARKET_SNAPSHOT, DETECTOR_SIGNAL, ..., POSITION_C)│ │
│  │   8 sources, 5 data qualities, 9 marker types                       │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ replayValidation.js                                                 │ │
│  │   validateReplayEvent(), validateReplayDataset(),                   │ │
│  │   validateReplayMarker()                                            │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ 7 View Models:                                                      │ │
│  │   TimelineModel, InspectorModel, MarkerOverlayModel,                │ │
│  │   MarketViewModel, PositionTimelineModel,                           │ │
│  │   ControllerModel, DecisionRailwayModel                             │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ 8 UI Components:                                                    │ │
│  │   ReplayController, ReplayTimeline, ReplayInspector,                │ │
│  │   ReplayMarketView, ReplayMarkerOverlay, DecisionRailway,           │ │
│  │   PositionTimeline, MarketReplayPanel                               │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  DATA SOURCE:                                                             │
│    ✓ replayFixtures.js     (XRP_USDT paper-trade, 10 events, static)     │
│    ✗ ReplayLoader          (fetch from Recorder API → NOT EXISTS)        │
│    ✗ Archive event fetcher (download raw events → NOT EXISTS)            │
│    ✗ Dataset transformer   (raw events → ReplayDataset format)           │
│                                                                           │
│  Replay → Recorder connection: NONE (all data from hardcoded fixture)     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implemented Components (Status Matrix)

### 2.1 Frontend Recorder UI

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Contracts | `recorderContracts.js` | 18 | ✓ COMPLETE |
| Data State | `recorderDataState.js` | 98 | ✓ COMPLETE |
| Error Objects | `recorderError.js` | 45 | ✓ COMPLETE |
| API Client | `services/recorderClient.js` | 258 | ✓ COMPLETE |
| API DTOs | `services/recorderApiDtos.js` | 280 | ✓ COMPLETE |
| Query Builder | `services/recorderQueryBuilder.js` | 118 | ✓ COMPLETE |
| Contract Fixtures | `services/recorderContractFixtures.js` | 147 | ✓ COMPLETE |
| Adapters | `adapters/recorderAdapters.js` | 146 | ✓ COMPLETE |
| Formatters | `formatters/recorderFormatters.js` | 75 | ✓ COMPLETE |
| Mock Data | `mock/mockRecorderData.js` | 111 | ✓ COMPLETE |
| Status Hook | `hooks/useRecorderStatus.js` | 131 | ✓ COMPLETE |
| Storage Hook | `hooks/useRecorderStorage.js` | 121 | ✓ COMPLETE |
| Archives Hook | `hooks/useRecorderArchives.js` | 128 | ✓ COMPLETE |
| Page | `pages/MarketRecorderPage.jsx` | 280 | ✓ COMPLETE |
| Styles | `styles/market-recorder.css` | - | ✓ COMPLETE |
| Index | `index.js` | 37 | ✓ COMPLETE |
| App Route | `App.jsx:53-54` | - | ✓ COMPLETE |
| Navigation | `AppNavigation.jsx:7,14,26` | - | ✓ COMPLETE |

**Client API methods:**
- `getHealth(options)` → `GET /api/market-recorder/health`
- `getStatus(options)` → `GET /api/market-recorder/status`
- `getStorage(options)` → `GET /api/market-recorder/storage`
- `getArchives(query, options)` → `GET /api/market-recorder/archives?page=...`
- `start()` → throws `RECORDER_NOT_IMPLEMENTED`
- `stop()` → throws `RECORDER_NOT_IMPLEMENTED`
- `download(id)` → throws `RECORDER_NOT_IMPLEMENTED`
- `delete(id)` → throws `RECORDER_NOT_IMPLEMENTED`

### 2.2 Backend Recorder Proxy

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Config Contract | `backend/config/recorder_proxy.py` | 128 | ✓ COMPLETE |
| DTO Validation | `backend/models/recorder_proxy.py` | 178 | ✓ COMPLETE |
| URL Builder | `backend/services/http/recorder_url_builder.py` | 46 | ✓ COMPLETE |
| HTTP Client | `backend/services/http/recorder_http_client.py` | 158 | ✓ COMPLETE |
| Service Layer | `backend/services/recorder_proxy/service.py` | 240 | ✓ COMPLETE |
| Error Mapping | `backend/services/recorder_proxy/errors.py` | 75 | ✓ COMPLETE |
| Route Handler | `backend/api/recorder_proxy.py` | 123 | ✓ COMPLETE |
| App Registration | `backend/main.py:1365-1367` | 3 | ✓ COMPLETE |

**Endpoint contracts:**

| Public Path | Upstream Path | Query Args |
|---|---|---|
| `GET /api/market-recorder/health` | `/api/recorder/health` | None (rejected) |
| `GET /api/market-recorder/status` | `/api/recorder/status` | None (rejected) |
| `GET /api/market-recorder/storage` | `/api/recorder/storage` | None (rejected) |
| `GET /api/market-recorder/archives` | `/api/recorder/archives` | page, page_size, stream, symbol, from, to, verification_status, downloadable, sort, order |

**Error codes:**
- `market_recorder_proxy_disabled` (503, non-retryable)
- `market_recorder_proxy_configuration_error` (503, non-retryable)
- `market_recorder_query_invalid` (400, non-retryable)
- `market_recorder_upstream_unavailable` (503, retryable)
- `market_recorder_upstream_timeout` (504, retryable)
- `market_recorder_upstream_invalid_response` (502, non-retryable)
- `market_recorder_upstream_rejected` (502, non-retryable)
- `market_recorder_upstream_protocol_error` (502, non-retryable)
- `market_recorder_internal_error` (500, non-retryable)

### 2.3 Replay Subsystem

| Category | Files | Status |
|----------|-------|--------|
| Replay Engine | `replayEngine.js` (317 lines) | ✓ COMPLETE |
| State Machine | `replayStateMachine.js` | ✓ COMPLETE |
| Constants | `replayConstants.js` | ✓ COMPLETE |
| Validation | `replayValidation.js` | ✓ COMPLETE |
| Projection | `replayProjection.js` | ✓ COMPLETE |
| Utilities | `replayUtils.js` | ✓ COMPLETE |
| Fixtures | `replayFixtures.js` (10 events) | ✓ COMPLETE |
| View Models (7) | `*Model.js` | ✓ COMPLETE |
| UI Components (8) | `*.jsx` | ✓ COMPLETE |
| Market Adapters | `replay/live *Adapter.js` | ✓ COMPLETE |
| Market Context | `marketContextSelection.js` | ✓ COMPLETE |

### 2.4 Test Coverage

| Test Suite | Count | Status |
|-----------|-------|--------|
| Backend Proxy Tests | 92+ tests (6 files) | ✓ ALL PASSING |
| Frontend Recorder Tests | 142+ tests (8+ files) | ✓ ALL PASSING |
| Replay Tests | 100+ tests (14+ files) | ✓ ALL PASSING |
| Total | 334+ tests | ✓ ALL PASSING |

---

## 3. Missing Connections (Integration Gaps)

### Gap 1: Frontend → Backend (Source Switching)
| Field | Detail |
|-------|--------|
| **Current State** | `recorderDataSource` defaults to `MOCK`. All hooks use mock data. `VITE_RECORDER_API_BASE_URL` is not set in `.env.production`. |
| **Expected** | `setRecorderDataSource(RECORDER_DATA_SOURCE.API)` called at app init, reading from `VITE_RECORDER_API_BASE_URL`. |
| **Blocking Reason** | `VITE_RECORDER_API_BASE_URL` not configured. No code in `MarketRecorderPage.jsx` or `App.jsx` to switch source. |
| **Priority** | **P1** — Low effort, high UX impact. Just needs env var + source switch call. |
| **Files Involved** | `hooks/useRecorderStatus.js:9` (source var), `recorderClient.js:16-31` (base URL validation), `.env.production` (missing env var) |

### Gap 2: Backend Proxy → Recorder Server (Live Connection)
| Field | Detail |
|-------|--------|
| **Current State** | `RECORDER_API_ENABLED=false` (default). `RECORDER_API_BASE_URL` not set. All routes return 503. |
| **Expected** | `RECORDER_API_ENABLED=true`. Valid `RECORDER_API_BASE_URL` pointing to Contabo recorder. Proxy forwards GET requests to upstream. |
| **Blocking Reason** | Contabo IP/Host/Port unknown. Network route (firewall, VPC) not configured. `RECORDER_API_BASE_URL` value not approved. |
| **Priority** | **P1** — Structural blocker. All live data flow depends on this. |
| **Files Involved** | `backend/config/recorder_proxy.py:96-127` (config loader), `backend/services/recorder_proxy/service.py:66-68` (_ensure_ready), `.env` (missing env vars) |

### Gap 3: Recorder Server → Upstream API Implementation
| Field | Detail |
|-------|--------|
| **Current State** | No recorder server exists. `runtime_chain_recorder.py` is 0 bytes. No health/status/storage/archives endpoints exist upstream. |
| **Expected** | A FastAPI (or similar) app on Contabo with `GET /api/recorder/health`, `/status`, `/storage`, `/archives` endpoints matching the proxy's upstream contract. |
| **Blocking Reason** | Recorder core is completely unimplemented. No server framework, no endpoints, no storage, no event recording. |
| **Priority** | **P0** — Foundational blocker. Every downstream integration depends on this. |
| **Files Involved** | `backend/runtime/runtime_chain_recorder.py` (empty), new files needed: recorder server app, API routes, storage layer |

### Gap 4: Recorder Core → Event Recording Hooks
| Field | Detail |
|-------|--------|
| **Current State** | No event recording hooks exist in any pipeline stage. Strategy, AI, Governance, Execution, Position tracker, WebSocket feeds — none emit recorder events. |
| **Expected** | Each runtime component calls `recorder.append_event(event)` at the appropriate lifecycle points. Event types match the 11 types in `replayConstants.js`. |
| **Blocking Reason** | `MarketRecorder` class not implemented. No event schema normalization. No correlation ID generation. |
| **Priority** | **P0** — Without hooks, there is nothing to record. Required before storage can be tested. |
| **Files Involved** | Strategy runtime, AI/LLM runtime, Governance runtime, ExecutionRuntime, position tracker, WebSocket callbacks — all need hook injection points |

### Gap 5: Recorder → Storage (JSONL + Compression + Manifest)
| Field | Detail |
|-------|--------|
| **Current State** | `data/market_recorder/` directory does not exist. No active writer, no compression, no manifest generator. |
| **Expected** | Active writer appends JSONL to `active/*.jsonl.part` with fsync. Hourly rotation compresses to `archive/*.jsonl.zst` and generates `.manifest.json`. Manifest index tracks all archives. |
| **Blocking Reason** | Storage code completely unimplemented. Requires JSONL writer, zstd compressor, manifest schema, rotation scheduler, snapshot/recovery logic. |
| **Priority** | **P0** — Required before any data can be persisted or served. |
| **Files Needed** | New: `market_recorder/storage_writer.py`, `market_recorder/rotation.py`, `market_recorder/manifest.py`, `market_recorder/compressor.py` |

### Gap 6: Recorder → Data Access API
| Field | Detail |
|-------|--------|
| **Current State** | No data access endpoints exist. Proxy routes to `/api/recorder/*` but no server responds there. The 4 proxy endpoints (health/status/storage/archives) need upstream implementations. Additional endpoints (datasets, manifests, stream) are specified but not implemented anywhere. |
| **Expected** | Upstream server serves `GET /api/recorder/health`, `/status`, `/storage`, `/archives`. Archive listing reflects actual stored data. Download endpoints serve `*.jsonl.zst` files. Dataset endpoints serve raw events for replay. |
| **Blocking Reason** | Recorder server not implemented. Storage not implemented. API contract for datasets/manifests/stream is only specified, not coded. |
| **Priority** | **P0** — Required for proxy to function and for replay loading. |
| **Files Needed** | New: `market_recorder/recorder_api.py` with FastAPI routes matching upstream contracts |

### Gap 7: Recorder → Control API (Start/Stop)
| Field | Detail |
|-------|--------|
| **Current State** | No start/stop endpoints exist anywhere. Frontend buttons permanently disabled. `recorderClient.start()` and `.stop()` throw `RECORDER_NOT_IMPLEMENTED`. |
| **Expected** | `POST /api/recorder/start` starts WebSocket connections and recording. `POST /api/recorder/stop` gracefully shuts down. Backend proxy routes these through to Contabo. |
| **Blocking Reason** | Recorder server not implemented. Safety restrictions: no POST routes in proxy (GET-only design). Would require adding POST to proxy allowlist with appropriate safety controls. |
| **Priority** | **P2** — Lower priority than recording pipeline. Read-only access is more important first. |
| **Files Involved** | `recorderClient.js:210-237` (start/stop stubs), `backend/api/recorder_proxy.py` (no POST routes), new: recorder control endpoints |

### Gap 8: Storage → Replay (ReplayLoader)
| Field | Detail |
|-------|--------|
| **Current State** | Replay engine loads only from `replayFixtures.js` (hardcoded 10-event fixture). No ReplayLoader exists to fetch recorded data. No archive-to-dataset transformer exists. |
| **Expected** | `ReplayLoader` component calls `GET /api/market-recorder/datasets/{id}` (or fetches archive events), transforms raw events into `ReplayDataset` format, dispatches `LOAD_DATASET` command. |
| **Blocking Reason** | No data access API. No recorded events. No dataset transformation. No archive event format defined. Recorder event schema vs ReplayDataset schema differ — need mapping. |
| **Priority** | **P2** — Depends on Gap 6. Replay integration is the end-to-end validation point. |
| **Files Needed** | New: `replay/replayLoader.js` (client-side data fetcher), `replay/eventTransformer.js` (recorder events → replay dataset format) |

### Gap 9: Market Data → Recorder (Normalizer)
| Field | Detail |
|-------|--------|
| **Current State** | WebSocket feeds exist (KuCoin OrderBookWS, Binance OrderBookWS) but no exchange-agnostic normalizer. Symbol formats differ between exchanges (e.g., XRPUSDTM vs XRP-USDT). |
| **Expected** | Normalizer converts all incoming WebSocket data into a canonical format with normalized symbol, timestamp, price precision, and quantity units. Feeds into `MarketRecorder.append_event()`. |
| **Blocking Reason** | No normalizer code exists. Normalization rules defined in `normalizedMarketModel.js` (frontend only). Backend normalization is partial and exchange-specific. |
| **Priority** | **P1** — Required before MARKET_SNAPSHOT events can be recorded. |
| **Files Needed** | New: `backend/market/market_normalizer.py` |

### Gap 10: Detectors → Recorder
| Field | Detail |
|-------|--------|
| **Current State** | No detectors are implemented (absorption, spoofing, iceberg, fake_pressure, market_context all NOT STARTED). |
| **Expected** | Each detector emits `DETECTOR_SIGNAL` events with signal type and confidence, flowing through normalizer into recorder. |
| **Blocking Reason** | Detectors not implemented. Can record MARKET_SNAPSHOT events without detectors first. |
| **Priority** | **P3** — Detectors are a separate project. Recorder can function with market data only initially. |
| **Files Needed** | New: `backend/detectors/*.py` |

### Gap 11: Correlation IDs
| Field | Detail |
|-------|--------|
| **Current State** | No correlation ID rules defined. decisionId, positionId, markerId, stationId generation and inheritance undefined. |
| **Expected** | `decisionId` assigned at DETECTOR_SIGNAL, carried through entire decision pipeline. `positionId` assigned at POSITION_OPENED, used through position lifecycle. |
| **Blocking Reason** | Rule specification not defined. No ID generator implemented. Replay inspector model expects these IDs to trace event chains. |
| **Priority** | **P1** — Required before decision pipeline events can be recorded meaningfully. Market-only replay works without correlation IDs. |
| **Files Needed** | New: `backend/runtime/correlation.py` |

---

## 4. Data Flow (End to End)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: DATA ACQUISITION                                                    │
│                                                                              │
│  KuCoin WS ──→ Backend OrderBookWS ──→ packet handler                       │
│  Binance WS ──→ Backend OrderBookWS ──→ packet handler                      │
│                                                                              │
│  Status: WebSocket connections EXIST but not connected to recorder.         │
│  Gap: No normalizer (Gap 9). No hook to recorder (Gap 4).                   │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼  (NOT CONNECTED)
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: NORMALIZATION + EVENT CREATION                                      │
│                                                                              │
│  Raw packet ──→ MarketNormalizer ──→ ReplayEvent format                     │
│                                                                              │
│  Target format: { id, timestamp, sequence, eventType, source, positionId,   │
│                   decisionId, markerId, stationId, payload, dataQuality }    │
│                                                                              │
│  Status: Nothing exists. Specified but not implemented.                      │
│  Gap: Normalizer (Gap 9). Event schema (Gap 4).                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼  (NOT CONNECTED)
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: RECORDER CORE                                                       │
│                                                                              │
│  event ──→ MarketRecorder.append_event(event)                               │
│              ├─ assign sequence counter                                     │
│              ├─ generate event ID (mr-{seq}-{uuid})                          │
│              ├─ append to active JSONL writer                               │
│              └─ emit to SSE (if streaming enabled)                          │
│                                                                              │
│  Status: runtime_chain_recorder.py is EMPTY (0 bytes).                      │
│  Gap: Entire recorder core (Gap 4).                                          │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼  (NOT CONNECTED)
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 4: STORAGE TIER                                                        │
│                                                                              │
│  JSONL lines ──→ active/{SYMBOL}_{YYYYMMDDHH}.jsonl.part                    │
│                                                                              │
│  Hourly:                                                                     │
│    .jsonl.part ──→ rotation ──→ archive/{SYMBOL}_{YYYYMMDDHH}.jsonl.zst     │
│                              ├──→ {file}.manifest.json                      │
│                              └──→ manifest_index.json (append)              │
│                                                                              │
│  Status: No storage directory exists. No writer. No compressor.              │
│  Gap: Storage (Gap 5).                                                       │
│  Reference: backend/money_management/timeline.py (JSONL write pattern)       │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼  (NOT CONNECTED)
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 5: DATA ACCESS API (Recorder Server)                                   │
│                                                                              │
│  GET /api/recorder/health     → { status, contract_version, uptime_seconds } │
│  GET /api/recorder/status     → { status, active_files, messages_received...│
│  GET /api/recorder/storage    → { total_bytes, used_bytes, archive_bytes... │
│  GET /api/recorder/archives   → { entries[], page, page_size, total_count } │
│  GET /api/recorder/manifests  → manifest index entries                      │
│  GET /api/recorder/datasets   → available datasets for replay               │
│  GET /api/recorder/datasets/{id} → raw events for a specific archive        │
│                                                                              │
│  Status: NOT IMPLEMENTED at all.                                             │
│  Gap: Data Access API (Gap 6).                                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼  (NOT CONNECTED)
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 6: BACKEND PROXY                                                       │
│                                                                              │
│  Browser → /api/market-recorder/health  → RecorderProxyService              │
│               /api/market-recorder/status  → → → httpx GET                  │
│               /api/market-recorder/storage  → RECORDER_API_BASE_URL         │
│               /api/market-recorder/archives     + /api/recorder/*            │
│                                                                              │
│  Status: COMPLETE but DISABLED (RECORDER_API_ENABLED=false).                │
│  When enabled: proxies all 4 endpoints to upstream.                         │
│  Fail-closed: returns 503 when disabled or misconfigured.                   │
│  Gap: Upstream unavailable (Gap 2). Config not set (Gap 2).                 │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼  (STRUCTURALLY CONNECTED / FAIL-CLOSED)
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 7: FRONTEND RECORDER UI                                                │
│                                                                              │
│  useRecorderStatus()  ──→ recorderClient.getStatus()  ──→ fetch("/api/...") │
│  useRecorderStorage() ──→ recorderClient.getStorage() ──→ fetch("/api/...") │
│  useRecorderArchives()──→ recorderClient.getArchives() ──→ fetch("/api/...")│
│                                                                              │
│  Status: COMPLETE but source= MOCK by default.                              │
│  When source=API: calls Same-Origin proxy (no Contabo URL exposure).        │
│  Control buttons (START/STOP/DOWNLOAD/DELETE) permanently disabled.         │
│  Gap: Source switching not triggered (Gap 1).                               │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼  (NOT CONNECTED)
┌──────────────────────────────────────────────────────────────────────────────┐
│  STEP 8: REPLAY                                                              │
│                                                                              │
│  User selects archive ──→ ReplayLoader fetches events                       │
│                         ├─ transforms to ReplayDataset                      │
│                         └─ dispatches LOAD_DATASET command                  │
│                                                                              │
│  replayEngine.js applies LOAD_DATASET                                       │
│    ├─ validateReplayDataset()                                               │
│    ├─ compute bounds                                                        │
│    ├─ projectReplayState() (derives full projection)                        │
│    └─ state machine: IDLE → REPLAY_LOADING → REPLAY_READY                  │
│                                                                              │
│  Status: Engine COMPLETE. Fixture-based only. No ReplayLoader exists.       │
│  Gap: ReplayLoader (Gap 8). Data Access API (Gap 6).                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Integration Order (Recommended Implementation Sequence)

### Stage 1: Storage Foundation (P0 — Everything depends on this)

| Step | Task | Files to Create/Modify | Depends On |
|------|------|----------------------|------------|
| 1.1 | Implement JSONL Active Writer | `backend/runtime/market_recorder/writer.py` | None |
| 1.2 | Implement MarketRecorder class with append_event() | `backend/runtime/runtime_chain_recorder.py` | Step 1.1 |
| 1.3 | Implement MarketNormalizer (exchange → canonical) | `backend/market/market_normalizer.py` | None |
| 1.4 | Add MARKET_SNAPSHOT event recording hooks to WebSocket feeds | `backend/market/exchanges/*.py` | Steps 1.2, 1.3 |
| 1.5 | Implement manifest schema and generator | `backend/runtime/market_recorder/manifest.py` | Step 1.1 |
| 1.6 | Implement hourly rotation + zstd compression | `backend/runtime/market_recorder/rotation.py` | Steps 1.1, 1.5 |
| 1.7 | Implement snapshot/gap recovery | `backend/runtime/market_recorder/snapshot.py` | Step 1.1 |
| 1.8 | Create data/market_recorder/ directory structure | (mkdir) | Steps 1.1-1.7 |

### Stage 2: Read API (P0 — Proxy integration target)

| Step | Task | Files to Create/Modify | Depends On |
|------|------|----------------------|------------|
| 2.1 | Implement Recorder Server (FastAPI app) | `backend/market_recorder/server.py` | Stage 1 |
| 2.2 | Implement GET /api/recorder/health | `backend/market_recorder/server.py` | Step 2.1 |
| 2.3 | Implement GET /api/recorder/status | `backend/market_recorder/server.py` | Step 2.1 |
| 2.4 | Implement GET /api/recorder/storage | `backend/market_recorder/server.py` | Step 2.1 |
| 2.5 | Implement GET /api/recorder/archives (paginated) | `backend/market_recorder/server.py` | Steps 1.5, 1.6 |
| 2.6 | Implement GET /api/recorder/datasets | `backend/market_recorder/server.py` | Step 2.5 |
| 2.7 | Implement GET /api/recorder/datasets/{id} (raw events) | `backend/market_recorder/server.py` | Step 2.6 |

### Stage 3: Live Connection (P0 — End-to-end smoke test)

| Step | Task | Files to Modify | Depends On |
|------|------|----------------------|------------|
| 3.1 | Set RECORDER_API_ENABLED=true | `.env` | Stage 2 |
| 3.2 | Set RECORDER_API_BASE_URL | `.env` | Stage 2 |
| 3.3 | Smoke test: curl /api/market-recorder/health | manual | Steps 3.1, 3.2 |
| 3.4 | Smoke test: curl /api/market-recorder/status | manual | Steps 3.1, 3.2 |
| 3.5 | Smoke test: curl /api/market-recorder/storage | manual | Steps 3.1, 3.2 |
| 3.6 | Smoke test: curl /api/market-recorder/archives | manual | Steps 3.1, 3.2 |

### Stage 4: Frontend Live Integration (P1 — UI activation)

| Step | Task | Files to Modify | Depends On |
|------|------|----------------------|------------|
| 4.1 | Set VITE_RECORDER_API_BASE_URL | `frontend/.env.production` | Stage 3 |
| 4.2 | Add source switching logic to App.jsx or MarketRecorderPage | `App.jsx` or `MarketRecorderPage.jsx` | Step 4.1 |
| 4.3 | Verify UI status/storage/archives cards display live data | manual | Steps 4.1, 4.2 |
| 4.4 | Add archive pagination UI (useRecorderArchives already supports query params) | `MarketRecorderPage.jsx` | Step 4.3 |

### Stage 5: Decision Events (P1 — Full pipeline recording)

| Step | Task | Files to Modify | Depends On |
|------|------|----------------------|------------|
| 5.1 | Define correlation ID generation rules | `backend/runtime/correlation.py` | None |
| 5.2 | Add recorder hook to Strategy Runtime (STRATEGY_DECISION) | Strategy runtime files | Steps 1.2, 5.1 |
| 5.3 | Add recorder hook to AI/LLM Runtime (AI_DECISION) | AI runtime files | Steps 1.2, 5.1 |
| 5.4 | Add recorder hook to Governance Runtime (GOVERNANCE_DECISION) | Governance runtime files | Steps 1.2, 5.1 |
| 5.5 | Add recorder hook to Execution Runtime (ORDER_SUBMITTED/ACKNOWLEDGED/REJECTED) | ExecutionRuntime.py | Steps 1.2, 5.1 |
| 5.6 | Add recorder hook to Position Tracker (POSITION_OPENED/UPDATED/CLOSED) | Position tracker files | Steps 1.2, 5.1 |

### Stage 6: Replay Integration (P2 — End-to-end validation)

| Step | Task | Files to Create/Modify | Depends On |
|------|------|----------------------|------------|
| 6.1 | Implement ReplayLoader (fetch dataset from API) | `frontend/src/features/market-intelligence/replay/replayLoader.js` | Stages 2, 4 |
| 6.2 | Implement event transformer (recorder events → ReplayDataset) | `frontend/src/features/market-intelligence/replay/eventTransformer.js` | Step 6.1 |
| 6.3 | Implement ArchiveSelector UI (list archives + load selected) | New component | Steps 4.4, 6.1 |
| 6.4 | Wire LOAD_DATASET command to ReplayLoader result | `replayEngine.js` integration | Step 6.1 |
| 6.5 | End-to-end integration test: Start Recorder → Record → Archive → Fetch → Replay | test script | All above |

### Stage 7: Operations (P2 — Production readiness)

| Step | Task | Depends On |
|------|------|------------|
| 7.1 | Create systemd service unit for recorder | Stage 2 |
| 7.2 | Create OpenAPI specification | Stage 2 |
| 7.3 | Implement START/STOP control endpoints | Stage 2 |
| 7.4 | Add POST routes to proxy (safety-controlled) | Step 7.3 |
| 7.5 | Enable START/STOP buttons in UI | Step 7.4 |
| 7.6 | Production deployment + monitoring | All above |

---

## 6. Risk Analysis

### Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| JSONL writer bugs cause data corruption | Medium | CRITICAL | Use reference implementation from MM timeline.py; comprehensive unit tests; fsync verification |
| Upstream recorder becomes unreachable mid-recording | High | HIGH | Implement snapshot/gap recovery (Stage 1.7); fail-closed proxy already handles missing upstream gracefully |
| Correlation ID mis-assignment traces wrong event chains | Medium | MEDIUM | Define rules before implementation; validate with fixtures representing all 11 event types |
| Compression too slow for hourly rotation | Low | MEDIUM | Zstd level 3 is fast enough; can adjust level or defer compression to background thread |
| Recorder process crash during active write | Medium | HIGH | .jsonl.part append ensures in-flight data is persisted; snapshot enables recovery from last known state |
| Network latency between Google Cloud and Contabo | Medium | MEDIUM | Proxy has configurable timeout (default 5s); archives are infrequently accessed; caching possible |
| Proxy exposed to SSRF via malformed upstream responses | Low | CRITICAL | SSRF-safe URL builder prevents arbitrary host:port access; 5 MiB cap prevents memory exhaustion; no redirects, no credentials |
| Frontend exposes Contabo URL to browser | Low | CRITICAL | Same-origin proxy ensures browser NEVER sees Contabo URL; proxy URL builder uses server-side config only |
| Multiple recorder instances write to same storage | Medium | HIGH | Active writer uses O_APPEND; per-symbol file naming prevents cross-symbol corruption; lock mechanism needed for multi-process scenario |

### Single Points of Failure

| Component | Failure Mode | Recovery |
|-----------|-------------|----------|
| Recorder Server Process | Crash | systemd restart (Stage 7.1), snapshot recovery (Stage 1.7) |
| Active Writer | Disk full | Storage monitoring endpoint alerts; rotation frees up space |
| Manifest Index | Corruption | Rebuild from individual manifest files |
| Archive File | Corruption | Checksums in manifest detect corruption; snapshots provide recovery point |
| Proxy Config | Misconfiguration | Fail-closed (503), safe error messages |

---

## 7. Estimated Completion Stages

| Stage | Components | Estimated Effort | Cumulative % |
|-------|-----------|-----------------|--------------|
| Stage 1: Storage Foundation | JSONL writer, MarketRecorder class, normalizer, MARKET_SNAPSHOT hooks, manifest, rotation, compression, snapshot | ~40 hours | 0% → 30% |
| Stage 2: Read API | Recorder server, health/status/storage/archives/datasets endpoints | ~25 hours | 30% → 45% |
| Stage 3: Live Connection | Config setup, proxy smoke tests | ~4 hours | 45% → 48% |
| Stage 4: Frontend Live Integration | Env var, source switching, pagination UI | ~8 hours | 48% → 55% |
| Stage 5: Decision Events | Correlation IDs, 5 pipeline hooks (Strategy, AI, Governance, Execution, Position) | ~30 hours | 55% → 70% |
| Stage 6: Replay Integration | ReplayLoader, event transformer, archive selector, end-to-end test | ~20 hours | 70% → 82% |
| Stage 7: Operations | systemd, OpenAPI spec, START/STOP controls, production deployment | ~15 hours | 82% → 100% |

**Total estimated effort: ~142 hours**

---

## 8. File-to-Integration Mapping

### Files That Need Changes (Integration Touch Points)

| File | Current State | Change Required | Stage |
|------|--------------|----------------|-------|
| `backend/runtime/runtime_chain_recorder.py` | 0 bytes, empty | Implement MarketRecorder class, append_event, sequence counter, JSONL writer | Stage 1 |
| `backend/market/market_normalizer.py` | Does not exist | Create: exchange-agnostic normalizer | Stage 1 |
| `backend/market_recorder/server.py` | Does not exist | Create: FastAPI app with health/status/storage/archives/datasets endpoints | Stage 2 |
| `backend/runtime/market_recorder/writer.py` | Does not exist | Create: JSONL active writer with fsync | Stage 1 |
| `backend/runtime/market_recorder/rotation.py` | Does not exist | Create: hourly rotation, zstd compression | Stage 1 |
| `backend/runtime/market_recorder/manifest.py` | Does not exist | Create: manifest generation, manifest index | Stage 1 |
| `backend/runtime/market_recorder/snapshot.py` | Does not exist | Create: snapshot writer, gap recovery | Stage 1 |
| `backend/runtime/correlation.py` | Does not exist | Create: ID generation rules | Stage 5 |
| `backend/market/exchanges/kucoin_market_ws.py` | 917 lines, no recorder hooks | Add MARKET_SNAPSHOT recording hook | Stage 1 |
| `backend/market/exchanges/binance_market_ws.py` | 643 lines, no recorder hooks | Add MARKET_SNAPSHOT recording hook | Stage 1 |
| `backend/main.py:1365-1367` | Proxy router registered | No changes needed (already registered) | - |
| `backend/config/recorder_proxy.py` | COMPLETE | No changes needed | - |
| `backend/api/recorder_proxy.py` | COMPLETE (GET only) | If control endpoints needed: add POST routes | Stage 7 |
| `backend/services/recorder_proxy/service.py` | COMPLETE | If control endpoints needed: add service methods | Stage 7 |
| `.env` / `.env.production` | No RECORDER_API_* vars | Add RECORDER_API_ENABLED, RECORDER_API_BASE_URL, etc. | Stage 3 |
| `frontend/.env.production` | No VITE_RECORDER_API_BASE_URL | Add VITE_RECORDER_API_BASE_URL | Stage 4 |
| `frontend/src/App.jsx` | Route registered | Add source switching: `setRecorderDataSource(API)` when env var set | Stage 4 |
| `frontend/src/pages/MarketRecorderPage.jsx` | Mock-only rendering | Enable API source, add archive pagination | Stage 4 |
| `frontend/src/features/market-intelligence/replay/replayLoader.js` | Does not exist | Create: fetch dataset from API, transform, dispatch LOAD_DATASET | Stage 6 |
| `frontend/src/features/market-intelligence/replay/eventTransformer.js` | Does not exist | Create: recorder events → replay dataset format | Stage 6 |
| Strategy/AI/Governance/Execution runtime files | No recorder hooks | Add `recorder.append_event()` at lifecycle points | Stage 5 |

### Files That Do NOT Need Changes

| File | Reason |
|------|--------|
| `backend/models/recorder_proxy.py` | DTO validation covers all 4 current endpoints |
| `backend/services/recorder_proxy/errors.py` | Error codes sufficient |
| `backend/services/http/recorder_http_client.py` | HTTP client complete, SSRF-safe |
| `backend/services/http/recorder_url_builder.py` | URL builder complete, fixed allowlist |
| `frontend/src/features/market-recorder/services/recorderClient.js` | Client complete (except start/stop/download/delete stubs) |
| `frontend/src/features/market-recorder/services/recorderApiDtos.js` | DTO validation complete |
| `frontend/src/features/market-recorder/contracts/*` | Contracts stable |
| `frontend/src/features/market-recorder/adapters/recorderAdapters.js` | ViewModel mapping complete |
| `frontend/src/features/market-recorder/hooks/*` | Hooks support both mock and API sources |
| `frontend/src/features/market-intelligence/replay/replayEngine.js` | Engine complete, accepts any ReplayDataset |
| `frontend/src/features/market-intelligence/replay/replayStateMachine.js` | State machine complete |
| `frontend/src/features/market-intelligence/replay/replayValidation.js` | Validation complete |
| `frontend/src/features/market-intelligence/replay/replayConstants.js` | Constants match event spec |

---

## 9. Summary of Integration Points

| # | Integration Point | From → To | Status | Priority | Stage |
|---|------------------|-----------|--------|----------|-------|
| 1 | UI → Backend Proxy (source switch) | Frontend → Backend | ○ Partially complete | P1 | 4 |
| 2 | Backend Proxy → Recorder Server (live connection) | Backend → Recorder | ✗ Not connected | P1 | 3 |
| 3 | Recorder Server → Upstream API | Recorder → HTTP | ✗ Not implemented | P0 | 2 |
| 4 | Event Sources → Recorder Core (hooks) | Runtimes → Recorder | ✗ Not implemented | P0 | 1, 5 |
| 5 | Recorder Core → Storage | Recorder → Disk | ✗ Not implemented | P0 | 1 |
| 6 | Storage → Data Access API | Disk → HTTP | ✗ Not implemented | P0 | 2 |
| 7 | Recorder → Control API | HTTP → Recorder | ✗ Not implemented | P2 | 7 |
| 8 | Data Access → Replay Loader | HTTP → Replay | ✗ Not implemented | P2 | 6 |
| 9 | Market Feeds → Normalizer | WebSocket → Recorder | ✗ Not implemented | P1 | 1 |
| 10 | Detectors → Event Hooks | Detectors → Recorder | ✗ Not implemented | P3 | Future |
| 11 | Correlation IDs → All Events | Generator → Events | ✗ Not defined | P1 | 5 |

**Status legend:** ✓ Complete | ○ Partial | ✗ Not implemented
**Priority legend:** P0 = Blocks everything | P1 = Blocks subsystem | P2 = Enhancement | P3 = Future

---

*End of Audit Report*
