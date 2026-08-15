# RP-MR-01 Market Recorder Architecture Review

**Version:** 1.0
**Status:** Complete
**Task ID:** RP-MR-01
**Prerequisite:** RP-INT-01

---

# 判定

**PASS（設計確定可能）** — Market Recorder の Pipeline 構造、Replay との責務境界、Event 生成ポイントは特定完了。未解決の設計項目 10 件を列挙し、実装ロードマップを提示する。

---

# 1. Market Recorder 仕様書確認

### 1.1 既存仕様書

| 文書 | パス | 状態 |
|------|------|------|
| Master Specification | `docs/market_recorder/01_Market_Recorder_Master_Specification.md` | **存在（設計のみ）** |
| Storage Contract (02) | 未作成 | **不在** |
| Data Access Contract (03) | 未作成 | **不在** |
| Snapshot / Gap Recovery (04) | 未作成 | **不在** |
| Storage Contract v2 (05) | 未作成 | **不在** |
| Certification Plan (06) | 未作成 | **不在** |

### 1.2 Master Specification 抜粋

- **6 Design Principles:** Data Integrity First / Deterministic Storage / Immutable Archive / Fault Tolerance / Recoverability / Replay Safety
- **Storage Lifecycle:** `.jsonl.part`（active）→ rotation → `.jsonl.zst`（archive）→ manifest
- **Architecture Layers:** WebSocket → Normalization → Active Writer → Hourly Rotation → Zstd Compression → Manifest → Snapshot/Recovery → Data Access

### 1.3 実装ファイル

| ファイル | 状態 |
|----------|------|
| `backend/runtime/runtime_chain_recorder.py` | **空ファイル（0行）** |

Market Recorder に該当する実装コードは一切存在しない。

---

# 2. Recorder Pipeline

```
┌──────────────────────────────────────────────────────────────────────┐
│                        MARKET RECORDER PIPELINE                       │
│                                                                       │
│  Layer 1: Data Acquisition                                            │
│  ┌──────────────────────┐                                             │
│  │  Exchange WebSocket   │  KuCoin Futures / Binance Futures          │
│  │  (OrderBookWS)        │  Order Book (Level2, 20 depth)             │
│  │  kucoin_market_ws.py  │  Recent Trades                             │
│  │  binance_market_ws.py │                                             │
│  └────────┬─────────────┘                                             │
│           ↓                                                            │
│  Layer 2: Normalization                                                │
│  ┌──────────────────────┐                                             │
│  │  Market Normalizer    │  Symbol canonicalization                   │
│  │                       │  Price / Quantity normalization            │
│  │  [新設]               │  Timestamp normalization (UTC, ms)         │
│  │                       │  Exchange-agnostic format                  │
│  └────────┬─────────────┘                                             │
│           ↓                                                            │
│  Layer 3: Feature Generation                                           │
│  ┌──────────────────────┐                                             │
│  │  FeatureEngine        │  directional_bias, momentum_score,         │
│  │  backend/ai/          │  volatility_score, liquidity_score,        │
│  │  feature_engine.py    │  confidence_score, position_pressure,      │
│  │                       │  orderflow_delta, spread_score,            │
│  │  + Detectors [新設]   │  imbalance_score, custom_features          │
│  │                       │                                             │
│  │  Output: FeatureSnap  │  + absorption, spoofing, iceberg,          │
│  │  shot (Data Model     │  fake_pressure, market_context             │
│  │  05 Chapter 3)        │                                             │
│  └────────┬─────────────┘                                             │
│           ↓                                                            │
│  Layer 4: Decision Pipeline                                            │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │  Feature Snapshot                                              │     │
│  │      ↓                                                         │     │
│  │  Strategy (Python + LSTM)                                      │     │
│  │      ↓                                                         │     │
│  │  AI Review (LLMEngine / Rule Engine)                           │     │
│  │      ↓                                                         │     │
│  │  Governance (governance_runtime.py)                            │     │
│  │      ↓                                                         │     │
│  │  Execution (ExecutionRuntime.py)                               │     │
│  │      ↓                                                         │     │
│  │  Position (Paper/Live)                                         │     │
│  └──────────────────────────────────────────────────────────────┘     │
│           ↓ (各段階で Event を発生)                                     │
│  Layer 5: Event Recording                                              │
│  ┌──────────────────────┐                                             │
│  │  Market Recorder Core │  EventType → ReplayEvent 変換              │
│  │  [新設]               │  positionId / decisionId / markerId        │
│  │                       │  / stationId の相関追跡                    │
│  │  runtime_chain_       │  sequence 自動採番                        │
│  │  recorder.py          │  dataQuality 判定                          │
│  │                       │  重複排除（signature 方式）                 │
│  └────────┬─────────────┘                                             │
│           ↓                                                            │
│  Layer 6: Storage                                                      │
│  ┌──────────────────────┐                                             │
│  │  Active Writer         │  active/{symbol}_{hour}.jsonl.part        │
│  │  [新設]               │  O_APPEND + O_NOFOLLOW, fsync              │
│  │                       │  UTF-8, ASCII-safe, sort_keys, no NaN      │
│  └────────┬─────────────┘                                             │
│           ↓ (毎時 rotation)                                            │
│  ┌──────────────────────┐                                             │
│  │  Archive Compressor    │  archive/{symbol}_{hour}.jsonl.zst        │
│  │  [新設]               │  Zstandard level 3                         │
│  │                       │  Streaming decompression 対応              │
│  └────────┬─────────────┘                                             │
│           ↓                                                            │
│  ┌──────────────────────┐                                             │
│  │  Manifest Generator    │  {symbol}_{hour}.jsonl.zst.manifest.json  │
│  │  [新設]               │  event count, time range, checksums,       │
│  │                       │  sequence range, file size, status         │
│  └────────┬─────────────┘                                             │
│           ↓                                                            │
│  Layer 7: Data Access                                                  │
│  ┌──────────────────────┐                                             │
│  │  Replay Dataset        │  API endpoint or file reader              │
│  │  Generator [新設]     │  → ReplayDataset 組み立て                 │
│  │                       │  time range query / symbol filter          │
│  │                       │  pagination / streaming support            │
│  └────────┬─────────────┘                                             │
│           ↓                                                            │
│  =========================================================            │
│           ↓                                                            │
│  Layer 8: Replay Engine (既存 Frontend)                                │
│  ┌──────────────────────┐                                             │
│  │  ReplayEngine          │  LOAD_DATASET → validate → project        │
│  │  + ReplayProjection    │  → UI (Timeline, Marker, Inspector,       │
│  │  + View Models         │  Railway, Market View)                    │
│  │  frontend/.../replay/  │                                            │
│  └──────────────────────┘                                             │
└──────────────────────────────────────────────────────────────────────┘
```

---

# 3. Event 設計

### 3.1 Event Type 一覧（Replay が要求する 11 種）

| # | EventType | Source | 生成元 | 生成タイミング | Payload Key Fields |
|---|-----------|--------|--------|---------------|-------------------|
| 1 | `MARKET_SNAPSHOT` | `MARKET` | OrderBookWS + FeatureEngine | WebSocket メッセージ受信毎（throttle 推奨: 100ms-500ms） | `symbol`, `exchange`, `markPrice`, `bestBid`, `bestAsk`, `spread`, `volatility`, `buyPressure`, `sellPressure`, `liquidity`, `momentum`, `orderBook` (asks/bids), `trades` (recent) |
| 2 | `DETECTOR_SIGNAL` | `DETECTOR` | Detectors（absorption, spoofing, iceberg, fake_pressure 等） | 各 Detector がシグナル検出時 | `signal` (string), `confidence` (0-1) |
| 3 | `STRATEGY_DECISION` | `STRATEGY` | Python Strategy / LSTM | Strategy 判断完了時 | `direction` (LONG/SHORT/HOLD), `result` (PROPOSED/SUPPRESSED) |
| 4 | `AI_DECISION` | `AI` | LLMEngine / Rule Engine | AI 最終判断完了時 | `direction`, `confidence`, `bias`, `momentum`, `imbalance`, `reason` |
| 5 | `GOVERNANCE_DECISION` | `GOVERNANCE` | Governance Runtime | Governance 判定時 | `outcome` (APPROVED/BLOCKED), `blockReason`, `safetyMode`, `execution_enabled` |
| 6 | `ORDER_SUBMITTED` | `EXECUTION` | ExecutionRuntime | Order 送信時 | `clientOrderId`, `side` |
| 7 | `ORDER_ACKNOWLEDGED` | `EXECUTION` | ExecutionRuntime | Exchange 応答受信時 | `clientOrderId`, `status` |
| 8 | `POSITION_OPENED` | `POSITION` | ExecutionRuntime / Position Tracker | 新規 Position 成立時 | `markerType` (ENTRY), `side`, `price`, `entryPrice`, `quantity` |
| 9 | `POSITION_UPDATED` | `POSITION` | Position Tracker | Mark Price 変動 or 追加注文時 | `markPrice`, `unrealizedPnl` |
| 10 | `POSITION_CLOSED` | `POSITION` | Position Tracker | Position 決済時 | `markerType` (EXIT), `side`, `price`, `exitPrice`, `realizedPnl`, `reason` |
| 11 | `EXECUTION_REJECTED` | `EXECUTION` | ExecutionRuntime | Order 拒否時 | `clientOrderId`, `reason`, `errorCode` |

### 3.2 共通フィールド

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique ID（format: `mr-{sequence}-{uuid_hex}`） |
| `timestamp` | ISO 8601 / epoch ms | Yes | Event 発生時刻 |
| `sequence` | int (>=0) | Yes | Recorder 内連番（global monotonic） |
| `eventType` | string | Yes | 上記 11 種のいずれか |
| `source` | string | Yes | 上記 Source のいずれか |
| `positionId` | string\|null | Yes | Position 参照（POSITION_* イベントのみ non-null） |
| `decisionId` | string\|null | Yes | Decision Chain 参照（DETECTOR→EXECUTION で共有） |
| `markerId` | string\|null | Yes | Marker 参照 |
| `stationId` | string\|null | Yes | Railway Station 識別子（例: detector, python-strategy, ai-final-decision, governance, execution） |
| `payload` | object | Yes | Event type 固有データ |
| `dataQuality` | string | Yes | `VALID` / `UNKNOWN` / `PARTIAL` / `STALE` / `INVALID` |

### 3.3 Reference 追跡ルール

- **decisionId:** `DETECTOR_SIGNAL` 時に採番 → `STRATEGY_DECISION` → `AI_DECISION` → `GOVERNANCE_DECISION` → `ORDER_SUBMITTED` → `ORDER_ACKNOWLEDGED` → `POSITION_OPENED` まで同一の decisionId を引き継ぐ
- **positionId:** `POSITION_OPENED` 時に採番 → `POSITION_UPDATED` → `POSITION_CLOSED` で同一 positionId
- **markerId:** 任意のイベントに紐付く視覚マーカー（`MARKET_SNAPSHOT` の BUY/SELL 判定、`POSITION_OPENED` のエントリー、`POSITION_CLOSED` のイグジット、`GOVERNANCE_DECISION` のブロック）
- **stationId:** Railway 上のステーション識別子（`detector`, `python-strategy`, `ai-final-decision`, `governance`, `execution` など）

### 3.4 Sequence 設計

- Recorder 起動時に sequence counter = 0
- 全 Event に単調増加する global sequence を割り当て
- Market Recorder が停止→再開する場合は last sequence + 1 から継続（Manifest から復元）
- 異なる symbol 間でも同一の global sequence space を使用（Manifest で symbol 別に分離）

---

# 4. Replay との責務境界

```
┌─────────────────────────────────────────────────────────────────┐
│                     MARKET RECORDER (Backend)                     │
│                                                                   │
│  - WebSocket 接続・再接続                                          │
│  - 市場データ正規化                                                │
│  - Detector 実行・Feature 生成                                     │
│  - Strategy / AI / Governance パイプラインの実行                   │
│  - 全 Event の収集・sequence 付与                                  │
│  - Event の JSONL 追記（active）                                   │
│  - 時間ローテーション・Zstd 圧縮（archive）                         │
│  - Manifest 生成                                                   │
│  - Snapshot / Gap 検出 / Recovery                                  │
│  - Data Access API（HTTP エンドポイント）                           │
│      GET /api/market-recorder/manifests?symbol=&from=&to=         │
│      GET /api/market-recorder/datasets?symbol=&from=&to=          │
│      GET /api/market-recorder/datasets/{datasetId}                │
│      GET /api/market-recorder/stream?symbol=&from= (SSE)          │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│                      REPLAY LOADER (Frontend)                     │
│                                                                   │
│  - API 呼び出し（fetch manifests / datasets）                      │
│  - Manifest から dataset 選択                                      │
│  - ReplayDataset の組み立て                                       │
│  - 検証（validateReplayDataset）                                   │
│  - ReplayEngine に LOAD_DATASET コマンド発行                       │
│  - エラーハンドリング / リトライ                                    │
│  - Streaming 受信・バッファリング                                   │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│                      REPLAY ENGINE (Frontend)                     │
│                                                                   │
│  - Dataset 検証                                                    │
│  - State Machine 駆動                                             │
│  - Projection 計算                                                │
│  - View Model 派生（Timeline, Marker, Railway, Inspector）         │
│  - UI 表示（Controller, MarketView, Timeline, Inspector,          │
│    MarkerOverlay, PositionTimeline）                              │
└─────────────────────────────────────────────────────────────────┘
```

### 境界ルール

| 項目 | Recorder 側 | Replay Loader 側 |
|------|-----------|----------------|
| JSONL 解析 | Recorder 自身の読み取り（Recovery） | ReplayDataset 組み立て時の読み取り |
| dataQuality 付与 | Recorder が各 Event に付与 | 追加判定なし（Recorder 値を使用） |
| Event 並び替え | Recorder が sequence 順を保証 | Replay Loader は sequence 順を信頼 |
| 検証 | Recorder が Valid な Event のみ書く | Replay Loader も validate（二重防御） |
| 欠損検出 | Recorder が Manifest で管理 | Replay Loader は欠損時エラー表示 |
| Live Streaming | Recorder が SSE push | Replay Loader が受信・append |

---

# 5. Storage 設計

### 5.1 ディレクトリ構造

```
data/market_recorder/
├── active/
│   ├── {symbol}_{YYYYMMDDHH}.jsonl.part        # 稼働中ファイル
│   └── .{symbol}_{YYYYMMDDHH}.jsonl.part.tmp   # 追記作業用一時ファイル
├── archive/
│   ├── {symbol}_{YYYYMMDDHH}.jsonl.zst          # 圧縮済みアーカイブ
│   └── {symbol}_{YYYYMMDDHH}.jsonl.zst.manifest.json
├── snapshots/
│   └── {symbol}_{YYYYMMDDHHmmss}.json.gz        # 復旧用スナップショット
└── index/
    └── manifest_index.json                       # 全 Manifest の統合インデックス
```

### 5.2 JSONL 形式

- 1行 = 1 Event Object（`ReplayEvent` 互換）
- UTF-8, ASCII-safe, `sort_keys`, `allow_nan=False`, `separators=(",", ":")`
- 末尾は必ず `\n`
- 追記は `O_APPEND | O_WRONLY | O_NOFOLLOW`, `fsync` 後

### 5.3 Manifest 形式

```json
{
  "manifestId": "manifest-xrpusdtm-2026073112",
  "symbol": "XRPUSDTM",
  "exchange": "KUCOIN",
  "marketType": "FUTURES",
  "hour": "2026-07-31T12:00:00Z",
  "archiveFile": "XRPUSDTM_2026073112.jsonl.zst",
  "archiveSizeBytes": 1048576,
  "compressionAlgorithm": "zstd",
  "compressionLevel": 3,
  "uncompressedSizeBytes": 4194304,
  "eventCount": 36000,
  "firstSequence": 48001,
  "lastSequence": 84000,
  "timeRange": {
    "startedAt": "2026-07-31T12:00:00.000Z",
    "endedAt": "2026-07-31T12:59:59.950Z"
  },
  "checksums": {
    "sha256_uncompressed": "e3b0c44298fc...",
    "sha256_compressed": "6e340b9cffb3..."
  },
  "status": "COMPLETE",
  "createdAt": "2026-07-31T13:00:05.000Z",
  "recorderVersion": "1.0.0"
}
```

### 5.4 Index 形式

```json
{
  "version": 1,
  "updatedAt": "2026-07-31T13:00:05.000Z",
  "entries": [
    {
      "symbol": "XRPUSDTM",
      "exchange": "KUCOIN",
      "hour": "2026-07-31T12:00:00Z",
      "manifestFile": "XRPUSDTM_2026073112.jsonl.zst.manifest.json",
      "eventCount": 36000,
      "status": "COMPLETE"
    }
  ]
}
```

### 5.5 Compression

- Zstandard level 3（アーカイブ用）
- ストリーミング伸長対応（`zstd.ZstdDecompressor.stream_reader`）
- アクティブファイル（`.part`）は非圧縮
- ローテーション時にのみ圧縮

### 5.6 Replay 読み込み方式

| 方式 | 用途 | 実装優先度 |
|------|------|-----------|
| API 全件取得（`GET /datasets/{id}`） | 単一時間枠の Replay | **Phase 1** |
| API 範囲取得（`GET /datasets?from=&to=`） | 複数時間枠の結合 | Phase 2 |
| Streaming 取得（SSE） | Live Replay / 長時間 Replay | Phase 3 |
| File 直接読み取り | ローカル開発 / Debug | Phase 1 |

### 5.7 Streaming / Live Replay 対応

- Recorder が「稼働中の `.part` ファイル」を Streaming ソースとして提供
- SSE（Server-Sent Events）で逐次 push
- クライアント（Replay Loader）は受信した Event を既存 Dataset に append
- Live Replay は `endedAt = null` の特殊モードとして扱う

### 5.8 スナップショット / リカバリ

- 定期的（例: 10分毎）に全 Recorder 内部状態を `snapshots/` へ保存
- 保持内容: last sequence, symbol state map, active file offset
- 再起動時にスナップショットから復元し、active file 末尾を検証
- Gap 検出: Manifest の `firstSequence` / `lastSequence` の連続性チェック

---

# 6. Architecture Gap（未解決の設計項目）

| # | Gap | 深刻度 | 説明 |
|---|-----|--------|------|
| **G1** | Storage Contract 未定義（docs 02-06） | **CRITICAL** | Master Spec が参照する下位仕様書 02〜06 がいずれも未作成。ファイル名・JSONL 形式・checksum アルゴリズム・manifest の完全な schema が確定していない。 |
| **G2** | Recorder 実装ファイルが空 | **CRITICAL** | `backend/runtime/runtime_chain_recorder.py` が 0 行。実装のエントリポイントすら未定義。 |
| **G3** | Event Recording Hook 不在 | **CRITICAL** | Strategy / AI / Governance / Execution の各段階に、Recorder へ Event を送信する Hook が存在しない。現在の各 Runtime は Recorder を認識していない。 |
| **G4** | Normalizer 不在 | **HIGH** | Exchange（KuCoin / Binance）間で統一された内部形式へ変換する Normalizer が未実装。symbol canonicalization や timestamp normalization は一部存在するが、体系化されていない。 |
| **G5** | Detector 群が Recorder 非対応 | **HIGH** | absorption / spoofing / iceberg / fake_pressure 等の Detector が未実装、または Recorder への出力インターフェースを持たない。 |
| **G6** | Replay Loader 不在 | **HIGH** | Frontend 側に API 呼び出し→ReplayDataset 組み立てを行う Loader モジュールが存在しない。現在は hardcoded fixture のみ。 |
| **G7** | Correlation ID 生成ルール未定義 | **HIGH** | decisionId / positionId / markerId の採番規則・引き継ぎルールがコード化されていない。Fixture では手動で設定されている。 |
| **G8** | Data Quality 判定ロジック未定義 | **MEDIUM** | 各 Event に付与する dataQuality（VALID/PARTIAL/STALE/INVALID/UNKNOWN）の判定基準が定義されていない。 |
| **G9** | Recorder の API Contract 未定義 | **HIGH** | Frontend が Recorder データを取得するための HTTP API の path / method / request/response schema が未定義。 |
| **G10** | sequence 永続化と復元の設計不足 | **MEDIUM** | Recorder 再起動時に sequence counter を復元する仕組み（Manifest 読み取り or Snapshot）が未設計。 |

---

# 7. 実装優先順位（ロードマップ）

```
Phase 1: Foundation ─────────────────────────────────────────────
PR1-1  Storage Contract 策定（docs 02）
       → JSONL format, Manifest schema, directory structure,
         filename convention, checksum algorithm の確定
PR1-2  Data Access Contract 策定（docs 03）
       → HTTP API endpoint 定義, request/response schema,
         pagination, error codes
PR1-3  Snapshot / Recovery 設計（docs 04）
       → snapshot format, gap detection algorithm,
         recovery procedure

Phase 2: Core Recorder ─────────────────────────────────────────
PR2-1  runtime_chain_recorder.py の基本実装
       → MarketRecorder クラス, append event, sequence counter,
         JSONL active writer, fsync
PR2-2  Normalizer 実装
       → Symbol canonicalization, timestamp normalize,
         price/quantity Decimal, exchange-agnostic MarketSnapshot
PR2-3  Market Snapshot Event の記録
       → WebSocket on_update → Normalizer →
         MarketRecorder.append(MARKET_SNAPSHOT)

Phase 3: Decision Events ───────────────────────────────────────
PR3-1  Correlation 追跡機構
       → decisionId / positionId の採番・引継ぎ
PR3-2  Detector Signal 記録
       → Detector → Recorder.append(DETECTOR_SIGNAL)
PR3-3  Strategy / AI / Governance Event 記録
       → 各 Runtime に Recorder hook を追加
PR3-4  Execution / Position Event 記録
       → ExecutionRuntime / PositionTracker に Recorder hook

Phase 4: Archive & Access ──────────────────────────────────────
PR4-1  Rotation + Zstd Compression
       → Hourly rotation, .part → .zst + manifest
PR4-2  HTTP Data Access API
       → GET manifests, datasets, stream (SSE)
PR4-3  Snapshot / Gap Recovery
       → Periodic snapshot, restart recovery

Phase 5: Replay Integration ────────────────────────────────────
PR5-1  Replay Loader（Frontend）
       → API fetch → ReplayDataset 組み立て
PR5-2  Streaming / Live Replay
       → SSE → append to running dataset
PR5-3  Multi-hour dataset combining
       → 複数 manifest をまたぐ ReplayDataset 構築

Phase 6: Certification ─────────────────────────────────────────
PR6-1  Storage v2 Certification（docs 06）
PR6-2  統合テスト（Recorder → API → Replay Loader → Replay Engine）
```

---

# 8. 参考ファイル一覧

### Recorder 関連

| ファイル | 説明 |
|----------|------|
| `docs/market_recorder/01_Market_Recorder_Master_Specification.md` | Master Spec（設計のみ） |
| `backend/runtime/runtime_chain_recorder.py` | 空ファイル |
| `backend/money_management/timeline.py` | 既存 MM Timeline Recorder（参考実装） |

### Replay 関連

| ファイル | 説明 |
|----------|------|
| `frontend/src/features/market-intelligence/replay/replayConstants.js` | EventType / Source / DataQuality / MarkerType 定義 |
| `frontend/src/features/market-intelligence/replay/replayValidation.js` | ReplayEvent / ReplayDataset / Marker 検証 |
| `frontend/src/features/market-intelligence/replay/replayEngine.js` | Replay Engine 本体 |
| `frontend/src/features/market-intelligence/replay/replayProjection.js` | Projection 計算 |
| `frontend/src/features/market-intelligence/replay/decisionRailwayModel.js` | Railway Station 定義 |
| `frontend/src/features/market-intelligence/replay/replayFixtures.js` | XRP_FIXTURE（Payload サンプル） |

### 意思決定パイプライン

| ファイル | 説明 |
|----------|------|
| `backend/ai/feature_engine.py` | Feature Engine（directional_bias, momentum 等） |
| `backend/ai/llm_engine.py` | LLM/Rule Engine（AI Decision） |
| `backend/ai/runtime_state.py` | RuntimeState（market context） |
| `backend/runtime/governance_runtime.py` | Governance Runtime |
| `backend/runtime/ExecutionRuntime.py` | Execution Runtime |

### データモデル仕様

| ファイル | 説明 |
|----------|------|
| `docs/data_model/05_DATA_MODEL_SPEC_CHAPTER_03_FEATURE_SNAPSHOT.md` | Feature Snapshot モデル |
| `docs/data_model/05_DATA_MODEL_SPEC_CHAPTER_04_DECISION_MODELS.md` | Decision Chain モデル |
| `docs/data_model/05_DATA_MODEL_SPEC_CHAPTER_05_REPLAY_MODELS.md` | Replay モデル |
| `docs/data_model/05_DATA_MODEL_SPEC_CHAPTER_06_TIMELINE_MODELS.md` | Timeline モデル |

---

# 9. Git 状態

```
 M backend/ai_advisor/runner_process_detection.py
 M backend/utils/log_buffer.py
 M docs/ai_advisor/AI_ADVISOR_EXACT_RELEASE_MANIFEST_CANDIDATE.md
 M docs/ai_advisor/systemd-credential-smoke-runbook.md
 M frontend/dist/index.html
 M tests/test_ai_advisor_runner_process_detection.py
 M tests/test_ai_advisor_systemd_unit_contract.py
 + 未追跡: docs/OpenCode_User_Quick_Guide.md
 + 未追跡: docs/ai_advisor/
 + 未追跡: docs/data_model/
 + 未追跡: docs/market_intelligence/
 + 未追跡: docs/market_recorder/
 + 未追跡: docs/money_management/
 + 未追跡: docs/opencode/
 + 未追跡: docs/visual_guideline/
```

本 Task による変更: `docs/opencode/reports/RP-MR-01_Architecture_Review.md`（新規）

---

# 10. 次工程

- **RP-MR-02**: Storage Contract 策定（G1前半: docs 02 作成, JSONL/Manifest schema 確定）
- **RP-MR-03**: Data Access Contract 策定（G1: docs 03, API endpoint 定義）
- **RP-MR-04**: Snapshot / Recovery 設計（G1: docs 04, recovery procedure 確定）
