# 05_DATA_MODEL_SPEC

## Chapter 2 — Core Entities

### 2.1 Purpose

本章は、MARKET INTELLIGENCE全体で使用する中核Entityを定義する。

対象は以下である。

- Replay
- Position
- Timeline
- Railway
- Marker
- 共通Entity Envelope
- Entity Reference
- Entity間Relationship
- Lifecycle State
- Read Model
- Frontend表示用参照構造

本章の目的は、BackendとFrontendが同じEntity定義を共有し、実装時に独自解釈や重複モデルを作らない状態を確立することである。

本章では、次章以降で詳細化するFeature Snapshot、Decision、Governance、Executionを参照Entityとして扱う。

---

## 2.2 Core Entity Map

MARKET INTELLIGENCEの主要Entity関係は以下とする。

```text
ReplaySession
    └─ ReplayCursor
         └─ ReplayFrame
              ├─ FeatureSnapshot
              ├─ DecisionChain
              ├─ ActivePosition[]
              ├─ TimelineEvent[]
              ├─ RailwayCycle[]
              └─ Marker[]

Position
    ├─ EntryDecisionChain
    ├─ EntryOrder[]
    ├─ ManagementEvent[]
    ├─ ExitDecisionChain
    ├─ ExitOrder[]
    ├─ TimelineEvent[]
    ├─ RailwayCycle[]
    └─ Marker[]

TimelineGroup
    └─ TimelineEvent[]

RailwayCycle
    ├─ FeatureSnapshotReference
    ├─ DecisionReference[]
    ├─ GovernanceReference
    ├─ ExecutionReference
    ├─ PositionReference
    └─ TimelineEventReference[]

Marker
    ├─ PositionReference
    ├─ OrderReference
    ├─ ExecutionReference
    ├─ TimelineEventReference
    └─ ReplayReference
```

---

## 2.3 Common Entity Envelope

すべての主要Entityは、共通Envelopeを基礎として構成する。

### 2.3.1 Standard Envelope

```json
{
  "id": "entity_id",
  "entityType": "POSITION",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T05:42:31.482Z",
  "updatedAt": "2026-07-19T05:42:31.482Z",
  "sourceTimestamp": "2026-07-19T05:42:31.410Z",
  "source": "POSITION_MANAGER",
  "runtimeInstanceId": "runtime_01K0...",
  "deploymentVersion": "fc76c4fb4dad2d318ce7b23375ca11d35d8a849c",
  "correlationId": "corr_01K0...",
  "sequence": 18442,
  "context": {
    "mode": "LIVE",
    "replaySessionId": null,
    "readOnly": true
  },
  "metadata": {},
  "extensions": {}
}
```

### 2.3.2 Required Envelope Fields

| Field | Type | Required | Nullable | Meaning |
|---|---:|---:|---:|---|
| `id` | string | Yes | No | Entityの一意ID |
| `entityType` | enum | Yes | No | Entity種別 |
| `schemaVersion` | string | Yes | No | Serialization schema version |
| `createdAt` | datetime | Yes | No | Entity生成時刻 |
| `source` | string | Yes | No | Primary ownerまたは生成元 |
| `sequence` | integer | Yes | No | 対象stream内の順序 |
| `context` | object | Yes | No | LIVE / REPLAY context |

### 2.3.3 Optional Envelope Fields

| Field | Type | Required | Nullable | Meaning |
|---|---:|---:|---:|---|
| `updatedAt` | datetime | No | Yes | 最終更新時刻 |
| `sourceTimestamp` | datetime | No | Yes | 元データ発生時刻 |
| `runtimeInstanceId` | string | No | Yes | Runtime識別子 |
| `deploymentVersion` | string | No | Yes | 実装Version |
| `correlationId` | string | No | Yes | 1判断pipelineの追跡ID |
| `metadata` | object | No | No | 非主要補足情報 |
| `extensions` | object | No | No | 将来拡張領域 |

`metadata`および`extensions`のdefaultは空objectとする。

---

## 2.4 Entity Type Enum

```text
REPLAY_SESSION
REPLAY_CURSOR
REPLAY_FRAME
POSITION
POSITION_EVENT
TIMELINE_EVENT
TIMELINE_GROUP
RAILWAY_CYCLE
RAILWAY_STAGE
MARKER
FEATURE_SNAPSHOT
STRATEGY_DECISION
LSTM_DECISION
LLM_DECISION
CONSENSUS_DECISION
GOVERNANCE_DECISION
EXECUTION_ATTEMPT
ORDER
ERROR_RECORD
```

Frontendは未知の`entityType`を受信した場合、破棄せずUnsupported Entityとして扱う。

---

## 2.5 Entity Reference

Entity間参照は、単純なID文字列だけでなく、標準Reference Modelを利用できる。

### 2.5.1 EntityReference Model

```json
{
  "entityType": "POSITION",
  "entityId": "pos_01K0...",
  "label": "XRPUSDT LONG",
  "state": "OPEN",
  "timestamp": "2026-07-19T05:42:31.482Z"
}
```

### 2.5.2 EntityReference Fields

| Field | Type | Required | Nullable | Meaning |
|---|---:|---:|---:|---|
| `entityType` | enum | Yes | No | 参照先Entity種別 |
| `entityId` | string | Yes | No | 参照先ID |
| `label` | string | No | Yes | UI表示用短縮label |
| `state` | string | No | Yes | 参照時点のstate snapshot |
| `timestamp` | datetime | No | Yes | 参照関係が成立した時刻 |

`label`と`state`は表示最適化用であり、参照先のauthoritative valueを置換しない。

---

# 2.6 Replay Core Entities

## 2.6.1 ReplaySession

ReplaySessionは、特定期間の過去データを読み込み、MARKET INTELLIGENCE上で再生・停止・移動するためのセッションを表す。

### Model

```json
{
  "id": "rpl_01K0...",
  "entityType": "REPLAY_SESSION",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T06:00:00.000Z",
  "source": "REPLAY_ENGINE",
  "sequence": 1,
  "context": {
    "mode": "REPLAY",
    "replaySessionId": "rpl_01K0...",
    "readOnly": true
  },
  "symbol": "XRPUSDT",
  "exchange": "KUCOIN_FUTURES",
  "marketType": "FUTURES",
  "range": {
    "startAt": "2026-07-18T00:00:00.000Z",
    "endAt": "2026-07-18T01:00:00.000Z"
  },
  "state": "READY",
  "playback": {
    "speed": 1.0,
    "direction": "FORWARD",
    "loop": false
  },
  "cursorId": "rpc_01K0...",
  "dataStatus": {
    "state": "COMPLETE",
    "coveragePct": 100.0,
    "gapCount": 0
  },
  "sessionVersion": 1,
  "metadata": {},
  "extensions": {}
}
```

### ReplaySession State Enum

```text
CREATING
LOADING
READY
PLAYING
PAUSED
SEEKING
COMPLETED
FAILED
EXPIRED
CLOSED
```

### Rules

- `PLAYING`時は有効な`cursorId`が必須。
- `FAILED`時は`error`が必須。
- `COMPLETED`はcursorが`range.endAt`へ到達した状態。
- `EXPIRED`はReplay用データまたはセッション保持期限を超過した状態。
- ReplaySessionはLive executionを発生させない。
- `context.readOnly`は常に`true`。
- ReplaySessionから生成される注文・Position表示は過去記録の再現であり、新規実行ではない。

---

## 2.6.2 ReplayCursor

ReplayCursorは、Replay Session内の現在位置を表す。

### Model

```json
{
  "id": "rpc_01K0...",
  "entityType": "REPLAY_CURSOR",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T06:00:00.100Z",
  "updatedAt": "2026-07-19T06:02:18.200Z",
  "source": "REPLAY_ENGINE",
  "sequence": 1420,
  "context": {
    "mode": "REPLAY",
    "replaySessionId": "rpl_01K0...",
    "readOnly": true
  },
  "sessionId": "rpl_01K0...",
  "state": "STABLE",
  "timestamp": "2026-07-18T00:17:42.510Z",
  "eventSequence": 98142,
  "progressPct": 29.51,
  "frameId": "rpf_01K0...",
  "previousFrameId": "rpf_01JZ...",
  "nextFrameAvailable": true,
  "lastMove": {
    "type": "PLAYBACK_TICK",
    "requestedAt": "2026-07-19T06:02:18.100Z",
    "completedAt": "2026-07-19T06:02:18.200Z"
  }
}
```

### Cursor State Enum

```text
INITIALIZING
STABLE
MOVING
SEEKING
AT_START
AT_END
ERROR
```

### Move Type Enum

```text
PLAYBACK_TICK
STEP_FORWARD
STEP_BACKWARD
SEEK_TIMESTAMP
SEEK_EVENT
SEEK_POSITION
SEEK_MARKER
JUMP_START
JUMP_END
```

### Rules

- `timestamp`はReplay Session range内でなければならない。
- `progressPct`は0.0〜100.0。
- cursor移動中のFrontend表示は、旧frameを維持しつつloading状態を示してよい。
- 新frameが確定するまで旧frameと新cursorを混在させてはならない。
- Cursor変更はTimeline Eventとして記録可能だが、Domain Timelineへの保存は必須ではない。

---

## 2.6.3 ReplayFrame

ReplayFrameは、Replay Cursorが指す特定時点の表示用統合Snapshotである。

### Model

```json
{
  "id": "rpf_01K0...",
  "entityType": "REPLAY_FRAME",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T06:02:18.200Z",
  "sourceTimestamp": "2026-07-18T00:17:42.510Z",
  "source": "REPLAY_ENGINE",
  "sequence": 98142,
  "context": {
    "mode": "REPLAY",
    "replaySessionId": "rpl_01K0...",
    "readOnly": true
  },
  "sessionId": "rpl_01K0...",
  "cursorId": "rpc_01K0...",
  "frameTimestamp": "2026-07-18T00:17:42.510Z",
  "featureSnapshotId": "fs_01K0...",
  "activePositionIds": ["pos_01K0..."],
  "visibleTimelineEventIds": ["evt_01K0..."],
  "railwayCycleIds": ["rwy_01K0..."],
  "markerIds": ["mrk_01K0..."],
  "dataCompleteness": {
    "state": "COMPLETE",
    "missingDomains": []
  }
}
```

### Data Completeness Enum

```text
COMPLETE
PARTIAL
GAPPED
UNKNOWN
ERROR
```

### Rules

- ReplayFrameはView aggregationであり、判断結果を再計算しない。
- Frameが`PARTIAL`または`GAPPED`の場合、Frontendは欠損domainを明示する。
- `featureSnapshotId`が存在しない場合、`dataCompleteness.state`は`COMPLETE`にできない。
- ReplayFrameは任意のUI設定を保存しない。

---

# 2.7 Position Core Entity

## 2.7.1 Position Purpose

Position Entityは、1つの市場Exposureのライフサイクル全体を表す。

Positionは単なる現在数量ではない。

以下を統合する。

- Entry判断
- Entry注文
- 約定
- Position Open
- Position Increase
- Position Reduce
- Risk管理
- Exit判断
- Exit注文
- Close
- Emergency Flatten
- PnL
- 関連Timeline
- Marker
- Railway Cycle

---

## 2.7.2 Position Model

```json
{
  "id": "pos_01K0...",
  "entityType": "POSITION",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T05:42:31.482Z",
  "updatedAt": "2026-07-19T05:48:02.104Z",
  "sourceTimestamp": "2026-07-19T05:48:02.012Z",
  "source": "POSITION_MANAGER",
  "runtimeInstanceId": "runtime_01K0...",
  "deploymentVersion": "fc76c4...",
  "correlationId": "corr_entry_01K0...",
  "sequence": 24,
  "context": {
    "mode": "LIVE",
    "replaySessionId": null,
    "readOnly": true
  },
  "exchange": "KUCOIN_FUTURES",
  "marketType": "FUTURES",
  "symbol": "XRPUSDTM",
  "normalizedSymbol": "XRPUSDT",
  "side": "LONG",
  "lifecycleState": "OPEN",
  "executionState": "FILLED",
  "riskState": "NORMAL",
  "syncState": "SYNCED",
  "quantity": {
    "current": 120.0,
    "opened": 120.0,
    "closed": 0.0,
    "unit": "XRP"
  },
  "price": {
    "entryAverage": 0.61240,
    "current": 0.61510,
    "exitAverage": null,
    "quoteCurrency": "USDT"
  },
  "notional": {
    "entry": 73.488,
    "current": 73.812,
    "currency": "USDT"
  },
  "leverage": 3.0,
  "marginMode": "ISOLATED",
  "openedAt": "2026-07-19T05:42:31.482Z",
  "closedAt": null,
  "entry": {
    "decisionChainId": "dc_01K0...",
    "executionAttemptId": "exa_01K0...",
    "orderIds": ["ord_01K0..."],
    "markerIds": ["mrk_01K0..."]
  },
  "management": {
    "stopLossPrice": 0.60100,
    "takeProfitPrice": 0.62900,
    "trailingStop": {
      "enabled": false,
      "activationPrice": null,
      "distancePct": null
    }
  },
  "exit": {
    "reason": null,
    "decisionChainId": null,
    "executionAttemptId": null,
    "orderIds": [],
    "markerIds": []
  },
  "pnl": {
    "unrealized": 0.324,
    "realized": 0.0,
    "fees": 0.041,
    "funding": 0.0,
    "net": 0.283,
    "currency": "USDT",
    "returnPct": 0.385
  },
  "references": {
    "timelineEventIds": ["evt_01K0..."],
    "railwayCycleIds": ["rwy_01K0..."]
  },
  "freshness": {
    "state": "FRESH",
    "ageMs": 92,
    "maxAgeMs": 3000,
    "staleReason": null
  },
  "metadata": {},
  "extensions": {}
}
```

---

## 2.7.3 Position Side Enum

```text
LONG
SHORT
FLAT
UNKNOWN
```

`FLAT`はPosition履歴またはSnapshot用途では使用可能だが、active Positionのsideとしては使用しない。

---

## 2.7.4 Position Lifecycle State Enum

```text
PENDING_ENTRY
OPENING
OPEN
INCREASING
REDUCING
PENDING_EXIT
CLOSING
CLOSED
CANCELLED
FAILED
STATE_UNKNOWN
```

### State Meaning

| State | Meaning |
|---|---|
| `PENDING_ENTRY` | Entry判断確定、注文送信前または待機 |
| `OPENING` | Entry注文送信済み、約定未確定 |
| `OPEN` | Position保有中 |
| `INCREASING` | 数量追加中 |
| `REDUCING` | 一部縮小中 |
| `PENDING_EXIT` | Exit判断確定、注文送信前 |
| `CLOSING` | Close注文送信済み |
| `CLOSED` | Position終了 |
| `CANCELLED` | Entry前に取消 |
| `FAILED` | Position確立または終了処理が失敗 |
| `STATE_UNKNOWN` | Authoritative stateを確認不能 |

---

## 2.7.5 Position State Transition

```text
PENDING_ENTRY
    ├─ OPENING
    │    ├─ OPEN
    │    ├─ FAILED
    │    └─ STATE_UNKNOWN
    └─ CANCELLED

OPEN
    ├─ INCREASING → OPEN
    ├─ REDUCING → OPEN
    ├─ PENDING_EXIT
    ├─ CLOSING
    └─ STATE_UNKNOWN

PENDING_EXIT
    ├─ CLOSING
    ├─ OPEN
    └─ STATE_UNKNOWN

CLOSING
    ├─ CLOSED
    ├─ OPEN
    ├─ FAILED
    └─ STATE_UNKNOWN
```

禁止遷移例:

```text
CLOSED → OPEN
CANCELLED → OPEN
FAILED → CLOSED
```

訂正が必要な場合は、状態上書きではなくCorrection Eventまたはreconciliation処理を記録する。

---

## 2.7.6 Execution State Enum

```text
NOT_SENT
SUBMITTING
ACKNOWLEDGED
PARTIALLY_FILLED
FILLED
REJECTED
CANCELLED
EXPIRED
FAILED
UNKNOWN
```

Position lifecycleとExecution stateは別軸とする。

例:

```text
Position lifecycleState = OPEN
Execution state = FILLED
```

---

## 2.7.7 Risk State Enum

```text
NORMAL
WARNING
LIMIT_APPROACHING
STOP_LOSS_ARMED
TAKE_PROFIT_ARMED
TRAILING_ACTIVE
EXIT_REQUIRED
EMERGENCY_EXIT
BLOCKED
UNKNOWN
```

---

## 2.7.8 Sync State Enum

```text
SYNCED
SYNCING
STALE
MISMATCH
SOURCE_UNAVAILABLE
UNKNOWN
```

`MISMATCH`または`UNKNOWN`時は、新規注文許可の判断に直接利用してはならず、Governanceへfail-closed情報として伝達する。

---

## 2.7.9 Position Quantity Rules

- `current >= 0`
- `opened >= 0`
- `closed >= 0`
- `current + closed`は原則`opened`と一致する。
- 手数料や取引所丸めによる差がある場合は`tolerance`を別途定義する。
- `CLOSED`では`current = 0`。
- `OPEN`では`current > 0`。
- `LONG / SHORT`方向は負数量では表さない。
- sideとquantityの符号表現を混用しない。

---

## 2.7.10 Position Summary Read Model

一覧表示には軽量Read Modelを使用できる。

```json
{
  "positionId": "pos_01K0...",
  "symbol": "XRPUSDT",
  "side": "LONG",
  "state": "OPEN",
  "quantity": 120.0,
  "entryPrice": 0.61240,
  "currentPrice": 0.61510,
  "unrealizedPnl": 0.324,
  "returnPct": 0.385,
  "openedAt": "2026-07-19T05:42:31.482Z",
  "riskState": "NORMAL"
}
```

Read ModelはPosition Core Entityの意味を変更してはならない。

---

# 2.8 Timeline Core Entities

## 2.8.1 TimelineEvent

TimelineEventは、MARKET INTELLIGENCE上で観測・監査・Replayされる1つの出来事を表す。

### Model

```json
{
  "id": "evt_01K0...",
  "entityType": "TIMELINE_EVENT",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T05:42:31.700Z",
  "sourceTimestamp": "2026-07-19T05:42:31.482Z",
  "source": "TIMELINE_AGGREGATOR",
  "runtimeInstanceId": "runtime_01K0...",
  "deploymentVersion": "fc76c4...",
  "correlationId": "corr_01K0...",
  "sequence": 18451,
  "context": {
    "mode": "LIVE",
    "replaySessionId": null,
    "readOnly": true
  },
  "eventType": "POSITION_OPENED",
  "category": "POSITION",
  "severity": "INFO",
  "status": "CONFIRMED",
  "title": "LONG position opened",
  "summary": "120 XRP opened at 0.61240 USDT.",
  "eventTimestamp": "2026-07-19T05:42:31.482Z",
  "references": [
    {
      "entityType": "POSITION",
      "entityId": "pos_01K0...",
      "label": "XRPUSDT LONG",
      "state": "OPEN",
      "timestamp": "2026-07-19T05:42:31.482Z"
    },
    {
      "entityType": "ORDER",
      "entityId": "ord_01K0...",
      "label": "Entry order",
      "state": "FILLED",
      "timestamp": "2026-07-19T05:42:31.482Z"
    }
  ],
  "groupId": "grp_01K0...",
  "positionId": "pos_01K0...",
  "railwayCycleId": "rwy_01K0...",
  "markerIds": ["mrk_01K0..."],
  "detail": {
    "price": 0.61240,
    "quantity": 120.0,
    "side": "LONG"
  },
  "error": null,
  "metadata": {},
  "extensions": {}
}
```

---

## 2.8.2 Timeline Event Status Enum

```text
OBSERVED
PENDING
CONFIRMED
CORRECTED
SUPERSEDED
FAILED
UNKNOWN
```

---

## 2.8.3 Timeline Category Enum

```text
MARKET_DATA
DETECTOR
FEATURE
STRATEGY
LSTM
LLM
CONSENSUS
GOVERNANCE
EXECUTION
ORDER
POSITION
RISK
EMERGENCY
REPLAY
SYSTEM
DATA_QUALITY
ERROR
```

---

## 2.8.4 Timeline Severity Enum

```text
DEBUG
INFO
NOTICE
WARNING
HIGH
CRITICAL
```

`severity`はUI色付けのみではなく、フィルタ・通知・監査優先度にも使用する。

---

## 2.8.5 Timeline Event Type Naming

Event Typeは`UPPER_SNAKE_CASE`とする。

例:

```text
FEATURE_SNAPSHOT_CREATED
STRATEGY_DECISION_CREATED
LSTM_DECISION_CREATED
LLM_DECISION_CREATED
CONSENSUS_DECISION_CREATED
GOVERNANCE_ALLOWED
GOVERNANCE_BLOCKED
EXECUTION_SUBMITTED
EXECUTION_REJECTED
ORDER_ACKNOWLEDGED
ORDER_PARTIALLY_FILLED
ORDER_FILLED
POSITION_OPENED
POSITION_INCREASED
POSITION_REDUCED
POSITION_CLOSED
STOP_LOSS_TRIGGERED
TAKE_PROFIT_TRIGGERED
TRAILING_STOP_TRIGGERED
EMERGENCY_FLATTEN_STARTED
EMERGENCY_FLATTEN_COMPLETED
DATA_GAP_DETECTED
STATE_UNKNOWN_DETECTED
```

---

## 2.8.6 TimelineGroup

TimelineGroupは、同一判断cycleまたはPosition lifecycle内の複数Eventをまとめる。

### Model

```json
{
  "id": "grp_01K0...",
  "entityType": "TIMELINE_GROUP",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T05:42:30.900Z",
  "updatedAt": "2026-07-19T05:42:31.700Z",
  "source": "TIMELINE_AGGREGATOR",
  "sequence": 18440,
  "context": {
    "mode": "LIVE",
    "replaySessionId": null,
    "readOnly": true
  },
  "groupType": "DECISION_TO_EXECUTION",
  "state": "COMPLETED",
  "title": "BUY decision cycle",
  "startAt": "2026-07-19T05:42:30.900Z",
  "endAt": "2026-07-19T05:42:31.700Z",
  "correlationId": "corr_01K0...",
  "positionId": "pos_01K0...",
  "railwayCycleId": "rwy_01K0...",
  "eventIds": [
    "evt_feature",
    "evt_strategy",
    "evt_llm",
    "evt_consensus",
    "evt_governance",
    "evt_execution",
    "evt_position"
  ],
  "summary": {
    "finalDecision": "BUY",
    "governanceState": "ALLOWED",
    "executionState": "FILLED",
    "positionState": "OPEN"
  }
}
```

### Group Type Enum

```text
MARKET_ANALYSIS
DECISION_CYCLE
DECISION_TO_EXECUTION
POSITION_ENTRY
POSITION_MANAGEMENT
POSITION_EXIT
EMERGENCY_SEQUENCE
REPLAY_SEQUENCE
DATA_QUALITY_INCIDENT
SYSTEM_INCIDENT
```

### Group State Enum

```text
OPEN
IN_PROGRESS
COMPLETED
PARTIAL
FAILED
CANCELLED
UNKNOWN
```

---

## 2.8.7 Timeline Ordering Rules

Timeline標準並び順:

```text
eventTimestamp ASC
sequence ASC
createdAt ASC
eventId ASC
```

降順表示時も、同時刻イベントの内部順序を反転させてはならない。

FrontendはBackendが返す`sequence`を尊重する。

---

# 2.9 Railway Core Entities

## 2.9.1 Railway Purpose

Railwayは、1回の市場判断が各処理段階を通過する様子を可視化する。

標準stage:

```text
MARKET
DETECTORS
FEATURES
STRATEGY
LSTM
LLM
CONSENSUS
GOVERNANCE
EXECUTION
POSITION
```

Railwayは処理結果を生成しない。

既存Entityを視覚的に接続するRead / Trace Modelである。

---

## 2.9.2 RailwayCycle

### Model

```json
{
  "id": "rwy_01K0...",
  "entityType": "RAILWAY_CYCLE",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T05:42:30.900Z",
  "updatedAt": "2026-07-19T05:42:31.700Z",
  "sourceTimestamp": "2026-07-19T05:42:30.850Z",
  "source": "INTELLIGENCE_ORCHESTRATOR",
  "runtimeInstanceId": "runtime_01K0...",
  "deploymentVersion": "fc76c4...",
  "correlationId": "corr_01K0...",
  "sequence": 918,
  "context": {
    "mode": "LIVE",
    "replaySessionId": null,
    "readOnly": true
  },
  "symbol": "XRPUSDT",
  "cycleState": "COMPLETED",
  "startedAt": "2026-07-19T05:42:30.900Z",
  "completedAt": "2026-07-19T05:42:31.700Z",
  "durationMs": 800,
  "finalDirection": "BUY",
  "finalOutcome": "POSITION_OPENED",
  "positionId": "pos_01K0...",
  "timelineGroupId": "grp_01K0...",
  "stages": [
    {
      "stage": "MARKET",
      "state": "COMPLETED",
      "startedAt": "2026-07-19T05:42:30.900Z",
      "completedAt": "2026-07-19T05:42:30.950Z",
      "durationMs": 50,
      "entityReference": {
        "entityType": "FEATURE_SNAPSHOT",
        "entityId": "fs_01K0..."
      },
      "reasonCode": null,
      "error": null
    },
    {
      "stage": "STRATEGY",
      "state": "COMPLETED",
      "startedAt": "2026-07-19T05:42:31.000Z",
      "completedAt": "2026-07-19T05:42:31.050Z",
      "durationMs": 50,
      "entityReference": {
        "entityType": "STRATEGY_DECISION",
        "entityId": "sd_01K0..."
      },
      "reasonCode": null,
      "error": null
    },
    {
      "stage": "GOVERNANCE",
      "state": "COMPLETED",
      "startedAt": "2026-07-19T05:42:31.500Z",
      "completedAt": "2026-07-19T05:42:31.520Z",
      "durationMs": 20,
      "entityReference": {
        "entityType": "GOVERNANCE_DECISION",
        "entityId": "gd_01K0..."
      },
      "reasonCode": null,
      "error": null
    }
  ],
  "metadata": {},
  "extensions": {}
}
```

---

## 2.9.3 Railway Cycle State Enum

```text
CREATED
RUNNING
COMPLETED
SUPPRESSED
BLOCKED
PARTIAL
FAILED
CANCELLED
UNKNOWN
```

### Meaning

- `SUPPRESSED`: StrategyまたはAI判断により実行候補にならなかった。
- `BLOCKED`: Governanceで拒否された。
- `PARTIAL`: 一部stageが欠損または処理未完了。
- `FAILED`: 処理エラーにより正常な最終結果を生成できなかった。

---

## 2.9.4 RailwayStage

### Stage Enum

```text
MARKET
DETECTORS
FEATURES
STRATEGY
LSTM
LLM
CONSENSUS
GOVERNANCE
EXECUTION
POSITION
```

### Stage State Enum

```text
NOT_STARTED
QUEUED
RUNNING
COMPLETED
SKIPPED
SUPPRESSED
BLOCKED
FAILED
NOT_APPLICABLE
UNKNOWN
```

### Rules

- `state = COMPLETED`では`completedAt`必須。
- `state = FAILED`では`error`必須。
- `state = SKIPPED`では`reasonCode`必須。
- `state = BLOCKED`は主としてGovernanceまたはExecution前後で使用する。
- StrategyがHOLDの場合、LSTM/LLMを呼ばない設計なら、それらは`NOT_APPLICABLE`または`SKIPPED`。
- `SKIPPED`と`NOT_APPLICABLE`を混同しない。
- Stage順序は固定配列indexではなく`stage` enumで識別する。

---

## 2.9.5 Railway Final Outcome Enum

```text
HOLD
SUPPRESSED
GOVERNANCE_BLOCKED
EXECUTION_NOT_SENT
ORDER_SUBMITTED
ORDER_REJECTED
ORDER_PARTIALLY_FILLED
ORDER_FILLED
POSITION_OPENED
POSITION_UPDATED
POSITION_CLOSED
FAILED
UNKNOWN
```

---

# 2.10 Marker Core Entity

## 2.10.1 Marker Purpose

Markerは、Order Book / DOM、Price Ladder、Timeline、Replay上に表示する重要イベントの視覚的目印である。

Markerは以下を表す。

- BUY execution
- SELL execution
- Position entry
- Position add
- Position reduce
- Position close
- Stop Loss
- Take Profit
- Trailing Stop
- Emergency Flatten
- Governance Block
- Execution Reject
- Replay bookmark
- User selection anchor

MarkerはUIだけの一時装飾ではなく、Domain Entityへの参照を持つ監査可能な表示Entityとする。

---

## 2.10.2 Marker Model

```json
{
  "id": "mrk_01K0...",
  "entityType": "MARKER",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T05:42:31.700Z",
  "sourceTimestamp": "2026-07-19T05:42:31.482Z",
  "source": "MARKER_BUILDER",
  "correlationId": "corr_01K0...",
  "sequence": 774,
  "context": {
    "mode": "LIVE",
    "replaySessionId": null,
    "readOnly": true
  },
  "markerType": "POSITION_ENTRY",
  "direction": "BUY",
  "state": "ACTIVE",
  "symbol": "XRPUSDT",
  "price": 0.61240,
  "quantity": 120.0,
  "notional": 73.488,
  "currency": "USDT",
  "timestamp": "2026-07-19T05:42:31.482Z",
  "positionId": "pos_01K0...",
  "orderId": "ord_01K0...",
  "executionAttemptId": "exa_01K0...",
  "timelineEventId": "evt_01K0...",
  "railwayCycleId": "rwy_01K0...",
  "display": {
    "label": "BUY 120 XRP",
    "shortLabel": "B",
    "priority": 80,
    "persistent": true,
    "clusterable": true
  },
  "attributes": {
    "reduceOnly": false,
    "emergency": false,
    "paper": true,
    "live": false
  },
  "metadata": {},
  "extensions": {}
}
```

---

## 2.10.3 Marker Type Enum

```text
BUY_EXECUTION
SELL_EXECUTION
POSITION_ENTRY
POSITION_INCREASE
POSITION_REDUCE
POSITION_EXIT
STOP_LOSS
TAKE_PROFIT
TRAILING_STOP
EMERGENCY_FLATTEN
GOVERNANCE_BLOCK
EXECUTION_REJECT
ORDER_CANCEL
LIQUIDATION_WARNING
REPLAY_BOOKMARK
DATA_GAP
SYSTEM_ERROR
```

---

## 2.10.4 Marker Direction Enum

```text
BUY
SELL
NEUTRAL
UNKNOWN
```

---

## 2.10.5 Marker State Enum

```text
PENDING
ACTIVE
HISTORICAL
SUPERSEDED
INVALIDATED
ERROR
```

### Rules

- Execution確定前は`PENDING`。
- 約定またはイベント確定後は`ACTIVE`。
- Replay表示または過去範囲では`HISTORICAL`として返せる。
- 元Eventが訂正された場合は`SUPERSEDED`。
- 誤生成と確認された場合は`INVALIDATED`。
- Markerは元Entityを削除しても直接消去せず、参照不能状態を監査可能にする。

---

## 2.10.6 Marker Persistence

Markerの保持方針:

- Position Entry Marker: Position close後も履歴として保持
- Position Exit Marker: 永続保持
- Governance Block Marker: Timeline期間中保持
- System Error Marker: severityに応じて保持
- Replay Bookmark: Replay SessionまたはユーザーPreferenceに紐付け
- Hover Marker: Domain Markerとして保存しない
- Temporary selection marker: Frontend UI Stateで管理

---

## 2.10.7 Marker Clustering

表示範囲に多数のMarkerが存在する場合、Frontendはcluster表示してよい。

ただしclusterはUI Read Modelであり、元Markerを置換しない。

例:

```json
{
  "clusterId": "cluster_local_42",
  "count": 12,
  "priceRange": {
    "min": 0.6120,
    "max": 0.6131
  },
  "markerIds": ["mrk_1", "mrk_2"]
}
```

`clusterId`はFrontend local IDでよい。

---

# 2.11 Position Event Entity

Positionの各変化はPositionEventとして表現できる。

### Model

```json
{
  "id": "pevt_01K0...",
  "entityType": "POSITION_EVENT",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T05:45:00.000Z",
  "sourceTimestamp": "2026-07-19T05:44:59.920Z",
  "source": "POSITION_MANAGER",
  "correlationId": "corr_01K0...",
  "sequence": 25,
  "context": {
    "mode": "LIVE",
    "replaySessionId": null,
    "readOnly": true
  },
  "positionId": "pos_01K0...",
  "eventType": "POSITION_REDUCED",
  "previousState": "OPEN",
  "newState": "OPEN",
  "quantityBefore": 120.0,
  "quantityAfter": 80.0,
  "price": 0.61700,
  "reasonCode": "TAKE_PROFIT_PARTIAL",
  "orderId": "ord_01K1...",
  "executionAttemptId": "exa_01K1...",
  "timelineEventId": "evt_01K1..."
}
```

### Position Event Type Enum

```text
POSITION_CREATED
ENTRY_REQUESTED
ENTRY_SUBMITTED
ENTRY_PARTIALLY_FILLED
POSITION_OPENED
POSITION_INCREASE_REQUESTED
POSITION_INCREASED
POSITION_REDUCE_REQUESTED
POSITION_REDUCED
EXIT_REQUESTED
EXIT_SUBMITTED
POSITION_CLOSED
POSITION_CANCELLED
POSITION_FAILED
POSITION_STATE_UNKNOWN
POSITION_RECONCILED
POSITION_CORRECTED
```

---

# 2.12 Core Relationship Rules

## 2.12.1 Position Relationships

- 1 Positionは0..n Orderを持つ。
- 1 Positionは0..n Markerを持つ。
- 1 Positionは1..n Timeline Eventを持つ。
- 1 Positionは1..n Position Eventを持つ。
- 1 Positionは1..n Railway Cycleと関連できる。
- Entry前にcancelされた場合、Position Entityを作るかEntry Candidate Entityで扱うかは実装で選択できる。ただし選択方針を統一する。
- CLOSED Positionは新規Order追加不可。ただしCorrection / Reconciliation Eventは追加可能。

## 2.12.2 Timeline Relationships

- Timeline Eventは0..1 Timeline Groupに所属。
- Timeline Groupは1..n Timeline Eventを持つ。
- Eventは複数EntityReferenceを持てる。
- Timeline Eventは元Entityの状態を上書きしない。
- 同一Eventを複数Groupへ所属させない。

## 2.12.3 Railway Relationships

- 1 Railway Cycleは1 correlationIdに対応。
- 1 Railway Cycleは0..1 Positionを生成または更新。
- HOLD / BLOCKED CycleではPositionが存在しないことがある。
- 1 Stageは0..1 primary EntityReferenceを持つ。
- 補助参照が必要な場合は`relatedReferences`を追加可能。

## 2.12.4 Marker Relationships

- Domain Markerは最低1つの元Entity参照を持つ。
- Execution MarkerはOrderまたはExecution Attempt参照必須。
- Position MarkerはPosition参照必須。
- Governance Block MarkerはGovernance Decision参照必須。
- Replay BookmarkだけはDomain Entity参照なしでもよいが、timestamp必須。

## 2.12.5 Replay Relationships

- ReplaySessionは1 active ReplayCursorを持つ。
- ReplayCursorは1 active ReplayFrameを持つ。
- ReplayFrameは複数Core EntityのIDを参照。
- Replay表示Entityは元Live Entity IDを維持する。
- Replay専用コピーIDを新規発行する場合、`originEntityId`を必須とする。

---

# 2.13 Core Entity Consistency Rules

## 2.13.1 Symbol Consistency

以下は一致しなければならない。

```text
Position.symbol
Order.symbol
FeatureSnapshot.symbol
Decision.symbol
RailwayCycle.symbol
Marker.symbol
```

`normalizedSymbol`とnative symbolは区別する。

---

## 2.13.2 Context Consistency

同一Response graph内で以下を混在させない。

```text
LIVE Entity
REPLAY Entity
```

ReplayFrame配下のEntityは`context.mode = REPLAY`として返すか、元Entityをそのまま返す場合はResponse Envelope側でReplay contextを明示する。

---

## 2.13.3 Time Consistency

- `createdAt <= updatedAt`
- Position `openedAt <= closedAt`
- Railway `startedAt <= completedAt`
- TimelineGroup `startAt <= endAt`
- Replay range `startAt < endAt`
- Marker timestampは元Event timestampと一致または許容差内
- sourceTimestampが未来時刻の場合、Data Quality Errorを生成

---

## 2.13.4 State Consistency

例:

```text
Position lifecycleState = CLOSED
→ quantity.current = 0
→ closedAt != null
→ exit.reason != null or correctionReason != null
```

```text
Railway cycleState = BLOCKED
→ Governance stage state = BLOCKED
→ Execution stage state = NOT_APPLICABLE or NOT_STARTED
```

```text
Marker type = POSITION_EXIT
→ positionId required
→ direction should oppose Position side
```

---

# 2.14 API Read Models

## 2.14.1 Current Intelligence Core Response

```json
{
  "schemaVersion": "1.0.0",
  "generatedAt": "2026-07-19T05:48:02.200Z",
  "context": {
    "mode": "LIVE",
    "readOnly": true
  },
  "activePositions": [],
  "recentTimelineEvents": [],
  "activeRailwayCycles": [],
  "visibleMarkers": [],
  "pagination": {
    "timelineNextCursor": null,
    "markerNextCursor": null
  }
}
```

---

## 2.14.2 Position Detail Response

```json
{
  "position": {},
  "positionEvents": [],
  "timelineEvents": [],
  "railwayCycles": [],
  "markers": [],
  "relatedDecisionChains": [],
  "relatedOrders": []
}
```

---

## 2.14.3 Replay Frame Response

```json
{
  "session": {},
  "cursor": {},
  "frame": {},
  "positions": [],
  "timelineEvents": [],
  "railwayCycles": [],
  "markers": [],
  "featureSnapshot": {},
  "decisionChains": []
}
```

---

# 2.15 Frontend State References

FrontendはCore Entityを複製してUI Stateへ保存しない。

推奨UI State:

```json
{
  "selectedPositionId": "pos_01K0...",
  "selectedTimelineEventId": "evt_01K0...",
  "selectedRailwayCycleId": "rwy_01K0...",
  "selectedMarkerId": "mrk_01K0...",
  "activeReplaySessionId": null,
  "expandedTimelineGroupIds": ["grp_01K0..."],
  "hoveredEntity": {
    "entityType": "MARKER",
    "entityId": "mrk_01K0..."
  }
}
```

Entity本体はnormalized store、query cache、または同等の一元管理領域に保持する。

---

# 2.16 Backend Ownership

| Entity | Primary Owner | Secondary Producer |
|---|---|---|
| ReplaySession | Replay Engine | API Layer |
| ReplayCursor | Replay Engine | None |
| ReplayFrame | Replay Engine | Read Model Builder |
| Position | Position Manager | Execution Reconciler |
| PositionEvent | Position Manager | Reconciler |
| TimelineEvent | Timeline Aggregator |各Domain Module |
| TimelineGroup | Timeline Aggregator | Intelligence Orchestrator |
| RailwayCycle | Intelligence Orchestrator | Trace Builder |
| RailwayStage | RailwayCycle内部 |各Stage Module |
| Marker | Marker Builder | Execution Observer |
| EntityReference | Shared Contract | Read Model Builder |

同一Entityのauthoritative更新ownerは1つに限定する。

---

# 2.17 Storage Considerations

本仕様はDB製品を固定しないが、以下を満たすこと。

- Entity IDで取得可能
- Position IDで関連Event検索可能
- correlationIdで判断cycle検索可能
- timestamp rangeでTimeline検索可能
- Replay Session rangeでFrame検索可能
- Markerをsymbol / time rangeで検索可能
- Railway CycleをPositionまたはcorrelationIdで検索可能
- immutable event保存に対応
- schemaVersionを保持可能
- pagination cursorを安定生成可能

推奨index:

```text
Position:
- id
- symbol + openedAt
- lifecycleState
- correlationId

TimelineEvent:
- eventTimestamp + sequence
- positionId
- correlationId
- category
- severity

RailwayCycle:
- startedAt
- correlationId
- positionId
- cycleState

Marker:
- symbol + timestamp
- positionId
- markerType

ReplaySession:
- id
- createdAt
- state
```

---

# 2.18 Core Error Cases

以下は明示的に検出する。

```text
ENTITY_REFERENCE_NOT_FOUND
DUPLICATE_ENTITY_ID
INVALID_STATE_TRANSITION
SYMBOL_MISMATCH
CONTEXT_MODE_MISMATCH
SEQUENCE_CONFLICT
TIMESTAMP_ORDER_INVALID
POSITION_QUANTITY_MISMATCH
RAILWAY_STAGE_ORDER_INVALID
MARKER_SOURCE_MISSING
REPLAY_CURSOR_OUT_OF_RANGE
REPLAY_FRAME_INCOMPLETE
SCHEMA_VERSION_UNSUPPORTED
```

Errorは黙って補正せず、validation resultまたはTimeline Eventとして記録する。

---

# 2.19 Implementation Requirements

Backend:

- Pydantic、dataclass、TypedDict、または同等のschema定義を作成する。
- API serialization時にcamelCaseへ統一する。
- Enumを文字列定数で散在させない。
- Entity ID生成を共通化する。
- timestampをUTCに統一する。
- state transition validatorを設ける。
- cross-reference validationを設ける。
- ReplayとLiveのcontext validatorを設ける。
- Core EntityとRead Modelを分離する。
- Timeline Eventを文字列logの代替にしない。

Frontend:

- TypeScript型または同等の型定義を作成する。
- Backend Enumを独自に再定義する場合、shared contract生成を優先する。
- `message`文字列を解析して状態判定しない。
- EntityをIDで参照する。
- Timeline順序をsequenceで維持する。
- UNKNOWN / UNSUPPORTEDを明示表示する。
- Marker clusterをDomain Entityとして保存しない。
- Replay EntityからLive操作を発火しない。

---

# 2.20 Review Checklist

## Common Envelope

- [ ] 全主要Entityに一意IDがある
- [ ] `entityType`が明示されている
- [ ] `schemaVersion`がある
- [ ] UTC timestampを使用している
- [ ] `sequence`がある
- [ ] LIVE / REPLAY contextが明示されている
- [ ] correlationIdの用途が統一されている

## Replay

- [ ] ReplaySession / Cursor / Frameが分離されている
- [ ] Cursorはsession range外へ移動できない
- [ ] Frame completenessが明示されている
- [ ] ReplayからLive executionが発生しない
- [ ] 元Entityとの参照関係を維持している

## Position

- [ ] lifecycleStateとexecutionStateが分離されている
- [ ] quantity整合性が検証される
- [ ] CLOSED時の条件が明確
- [ ] Position Eventが履歴として残る
- [ ] Entry / Management / Exit参照が存在する
- [ ] syncStateが明示される
- [ ] STATE_UNKNOWNがfail-closedで扱われる

## Timeline

- [ ] Timeline Eventがimmutable
- [ ] category / severity / eventTypeが分離されている
- [ ] orderingがtimestampだけに依存しない
- [ ] Timeline Groupが定義されている
- [ ] EntityReferenceが使用されている
- [ ] Correctionが上書きではなくEvent追加で行われる

## Railway

- [ ] Railway Cycleが1 correlationIdへ対応する
- [ ] Stage Enumが統一されている
- [ ] SKIPPED / NOT_APPLICABLE / BLOCKEDが分離される
- [ ] StageごとのEntity参照がある
- [ ] finalOutcomeが明示される
- [ ] Railwayが判断結果を再計算しない

## Marker

- [ ] Markerが元Entity参照を持つ
- [ ] type / direction / stateが分離される
- [ ] Position close後も履歴Markerが保持される
- [ ] 一時HoverやSelectionをDomain Markerにしない
- [ ] clusterがUI Read Modelである
- [ ] Replay Bookmarkの例外規則が定義されている

## Relationships

- [ ] symbol consistencyを検証する
- [ ] context consistencyを検証する
- [ ] timestamp consistencyを検証する
- [ ] state consistencyを検証する
- [ ] missing referenceを明示エラーにする
- [ ] Core EntityとUI Stateが分離されている

---

# 2.21 Chapter 2 Definition of Done

Chapter 2は、以下をすべて満たした場合に完成とする。

- 共通Entity Envelopeが定義されている
- Entity Type Enumが定義されている
- EntityReferenceが定義されている
- ReplaySessionが定義されている
- ReplayCursorが定義されている
- ReplayFrameが定義されている
- Position Core Entityが定義されている
- Position lifecycleが定義されている
- Position Eventが定義されている
- TimelineEventが定義されている
- TimelineGroupが定義されている
- Timeline orderingが定義されている
- RailwayCycleが定義されている
- RailwayStageが定義されている
- Markerが定義されている
- Marker persistenceが定義されている
- Entity間Relationshipが定義されている
- consistency ruleが定義されている
- API Read Model例が定義されている
- Frontend UI Stateとの分離が定義されている
- Backend ownershipが定義されている
- Storage要件が定義されている
- Error caseが定義されている
- Backend / Frontend実装要件が定義されている
- Review Checklistが完成している

---

## Chapter 2 Status

```text
STATUS: COMPLETE
DOCUMENT: 05_DATA_MODEL_SPEC
CHAPTER: 2
TITLE: Core Entities
```
