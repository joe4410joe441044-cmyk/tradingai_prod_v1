# 05_DATA_MODEL_SPEC
## Table of Contents
1. Data Model Philosophy
2. Core Entities
3. Feature Snapshot
4. Decision Models
5. Replay Models
6. Timeline Models
7. Inspector Models
8. Serialization
9. Validation Rules

---


---

# 05_DATA_MODEL_SPEC

## Chapter 1 — Data Model Philosophy

### 1.1 Purpose

本章は、TradingAI の独立画面 **MARKET INTELLIGENCE** で使用するデータモデル全体の設計思想を定義する。

MARKET INTELLIGENCE は、単なる現在値表示画面ではない。

以下の一連の判断過程を、リアルタイム表示・履歴参照・Replay・監査のすべてで一貫して扱うための、統合された観測モデルである。

```text
Market Data
    ↓
Python Detectors
    ↓
Feature Builder
    ↓
Python Strategy
    ↓
LSTM
    ↓
LLM
    ↓
Consensus
    ↓
Governance
    ↓
Execution
```

本仕様におけるデータモデルは、次の要件を同時に満たさなければならない。

- Backend が判断過程を欠落なく生成できること
- Frontend が追加推測なしで表示できること
- 現在状態と履歴状態を同じ構造で扱えること
- Replay が実稼働時と同一の意味を再現できること
- Position、Timeline、Railway、Marker が相互参照できること
- AI判断をブラックボックス化せず、入力・判断・抑止理由を追跡できること
- Governance が最終安全権限であることをデータ構造上も維持すること
- 将来の取引所追加、Detector追加、AIモデル変更に耐えられること
- 過去データとの互換性を管理できること

本章は、個別フィールド定義の前提となる最上位原則を定める。

---

### 1.2 Authoritative Data Principle

MARKET INTELLIGENCE に表示される情報は、Frontend が独自に推測・再計算してはならない。

Backend が生成した正式な値を authoritative data とする。

Frontend の責務は以下に限定する。

- Backendデータの表示
- 指定された形式への整形
- UI状態の管理
- ユーザー選択状態の管理
- Replay操作要求の送信
- 表示範囲・展開状態・選択状態の保持

Frontend は以下を行ってはならない。

- BUY / SELL / HOLD の再判定
- Strategy confidence の再計算
- Consensus の再計算
- Governance許可状態の推測
- Position lifecycle の推測
- Detector結果の再評価
- Timeline event の分類変更
- Marker種別の独自決定
- 欠損値を正常値として補完
- 古いSnapshotを最新状態として扱うこと

Backend と Frontend の責務境界は、次のように定義する。

```text
Backend
- Detect
- Calculate
- Decide
- Validate
- Classify
- Persist
- Serialize

Frontend
- Request
- Receive
- Select
- Render
- Navigate
- Replay
- Inspect
```

---

### 1.3 Deterministic Core and AI Interpretation

TradingAI のデータモデルは、決定論的処理とAI解釈処理を明確に分離する。

#### Deterministic Layer

Python が担当する。

- Order Book解析
- Recent Trades解析
- Buy / Sell Pressure
- Liquidity
- Momentum
- Spread
- Volatility
- Absorption
- Fake Pressure
- Spoofing
- Iceberg
- Feature正規化
- Strategy候補生成
- executionAllowed の初期判定
- suppressionReason の生成

Deterministic Layer の出力は、再現可能でなければならない。

同じ入力データと同じ設定値を使用した場合、同じ出力が得られることを原則とする。

#### AI Interpretation Layer

LSTM、LLM、Consensus が担当する。

AIは市場現象を直接検出する主体ではない。

Pythonが生成したFeature SnapshotおよびStrategy候補を入力として受け取り、複数の証拠を統合して最終判断を行う。

AI Layer のデータモデルは、少なくとも以下を保持する。

- 入力Feature参照
- 入力Strategy参照
- 使用モデル
- モデルバージョン
- 出力方向
- 信頼度
- 判断理由
- 反対証拠
- 抑止理由
- 処理時間
- エラー状態

安全設計上、Python Strategy が HOLD を出した場合、AI が独自に BUY または SELL へ昇格させないことを基本原則とする。

この原則は単なる実装ルールではなく、Decision Model 内に明示的な検証可能情報として保持する。

例:

```json
{
  "strategyDirection": "HOLD",
  "aiDirection": "HOLD",
  "upgradeAttempted": false,
  "upgradeAllowed": false
}
```

---

### 1.4 Governance Supremacy

Governance は、Strategy、LSTM、LLM、Consensus よりも上位の最終安全権限を持つ。

データモデル上、以下を明確に分離する。

- 市場判断
- 売買候補
- AI最終判断
- 実行許可
- 実際の注文結果

BUY判断が存在しても、Governanceが拒否した場合は注文を実行してはならない。

```text
Decision = BUY
Governance = BLOCKED
Execution = NOT_SENT
```

この状態は矛盾ではなく、正常な安全停止状態である。

したがって、最終結果を単一の `status` や `decision` フィールドのみで表現してはならない。

最低でも以下を別々に保持する。

- `strategyDecision`
- `lstmDecision`
- `llmDecision`
- `consensusDecision`
- `governanceDecision`
- `executionResult`

画面上の最終表示も、これらを混同してはならない。

---

### 1.5 Immutable Historical Record

Timeline、Position lifecycle、Decision、Execution result は、確定後に意味を書き換えてはならない。

過去イベントは原則として immutable とする。

修正が必要な場合は、既存イベントを上書きするのではなく、訂正イベントまたは補足イベントを追加する。

禁止例:

```text
過去の BUY 判定を HOLD に直接書き換える
```

許可例:

```text
EVENT 1: CONSENSUS_DECISION = BUY
EVENT 2: GOVERNANCE_BLOCKED = MAX_DRAWDOWN
EVENT 3: EXECUTION_NOT_SENT
```

データ訂正が必要な場合:

```text
EVENT 4: DATA_CORRECTION
targetEventId = EVENT 1
reason = SOURCE_TIMESTAMP_CORRECTED
```

この原則により、Replayと監査結果の整合性を維持する。

---

### 1.6 Event-Sourced Observation Model

MARKET INTELLIGENCE は、現在状態だけでなく、状態がどのように変化したかを重要視する。

そのため、全体設計は event-sourced observation model を基本とする。

ただし、取引システム本体を完全なEvent Sourcing方式へ変更することを要求するものではない。

MARKET INTELLIGENCE向けには、少なくとも以下をイベントとして観測可能にする。

- Market Snapshot生成
- Detector更新
- Feature Snapshot生成
- Strategy Decision生成
- LSTM Decision生成
- LLM Decision生成
- Consensus生成
- Governance評価
- Order送信
- Order受付
- Order約定
- Order拒否
- Position Open
- Position Increase
- Position Reduce
- Position Close
- Stop Loss
- Take Profit
- Trailing Stop
- Emergency Flatten
- Replay開始
- Replay停止
- Replay Cursor移動
- Data Gap検出
- Processing Error

現在状態はイベント列から導出可能であることが望ましいが、表示性能のためにSnapshot形式も併用する。

```text
Historical Truth = Event Records
Fast Current View = Materialized Snapshot
```

---

### 1.7 Snapshot and Event Separation

Snapshot と Event は目的が異なるため、同一構造として扱ってはならない。

#### Snapshot

特定時点の状態全体を表す。

例:

- Order Book Snapshot
- Feature Snapshot
- Position Snapshot
- Decision Snapshot
- Railway Snapshot
- Replay Snapshot

特性:

- 特定時刻の全体状態
- UIの初期描画に適する
- 最新状態取得に適する
- 一部が更新される可能性がある
- バージョン管理が必要

#### Event

状態変化または判断発生を表す。

例:

- STRATEGY_DECISION_CREATED
- GOVERNANCE_BLOCKED
- POSITION_OPENED
- ORDER_FILLED
- REPLAY_CURSOR_MOVED

特性:

- 発生順序を持つ
- 一意なEvent IDを持つ
- 原則immutable
- Replayと監査の基礎になる
- 同一時刻でも順序情報が必要

FrontendはSnapshotとEventを混同せず、用途別に使用する。

---

### 1.8 Stable Identity

すべての主要Entityは、一意で安定したIDを持たなければならない。

最低限、以下にIDを持たせる。

- Replay Session
- Position
- Order
- Timeline Event
- Timeline Group
- Railway Cycle
- Marker
- Feature Snapshot
- Strategy Decision
- LSTM Decision
- LLM Decision
- Consensus Decision
- Governance Decision
- Execution Attempt

IDは表示名、時刻、配列indexから生成してはならない。

不適切な例:

```text
positionId = "XRPUSDT-2026-07-19-1"
eventId = array index 42
```

推奨:

```text
pos_01K0...
evt_01K0...
dec_01K0...
rpl_01K0...
```

ID要件:

- システム全体で衝突しない
- 再起動後も変化しない
- Frontend再取得後も同一Entityを識別できる
- Replay時にも元Entityとの関係を追跡できる
- URLまたはAPI queryで安全に使用できる
- 並び順をIDの文字列比較だけに依存しない

ID形式はUUID、ULID、または同等の衝突耐性を持つ形式を採用できる。

時系列ソート可能性を重視する場合はULID系を推奨するが、正式な順序はtimestampおよびsequenceで決定する。

---

### 1.9 Time Model

MARKET INTELLIGENCEでは、複数種類の時刻を区別する。

最低限、以下を必要に応じて保持する。

- `sourceTimestamp`
- `receivedAt`
- `processedAt`
- `createdAt`
- `updatedAt`
- `persistedAt`
- `replayTimestamp`

#### sourceTimestamp

取引所またはデータソース上の発生時刻。

#### receivedAt

TradingAIがデータを受信した時刻。

#### processedAt

Detector、Strategy、AI等が処理を完了した時刻。

#### createdAt

EntityまたはEventが生成された時刻。

#### persistedAt

永続化が完了した時刻。

#### replayTimestamp

Replay上で現在指している市場時刻。

すべての永続化・API時刻は、ISO 8601 UTC形式を標準とする。

```text
2026-07-19T05:42:31.482Z
```

Frontendはユーザー表示時のみローカルタイムへ変換する。

内部データをAsia/Tokyo固定で保存してはならない。

処理遅延分析のため、以下を計算可能にする。

```text
ingestionLatencyMs = receivedAt - sourceTimestamp
processingLatencyMs = processedAt - receivedAt
persistenceLatencyMs = persistedAt - processedAt
endToEndLatencyMs = persistedAt - sourceTimestamp
```

---

### 1.10 Sequence and Ordering

同一ミリ秒内に複数イベントが発生する可能性があるため、timestampだけで順序を決定してはならない。

イベントは以下を持つ。

- `sequence`
- `sourceSequence` または取引所sequence
- `streamSequence`
- `positionSequence`
- `decisionSequence`

すべてを必須とする必要はないが、対象Entity内で確定的な順序が再現できなければならない。

Timelineの標準ソート優先順位:

```text
1. eventTimestamp
2. sequence
3. createdAt
4. eventId
```

Replayでは、実稼働時と同じ順序を再現する。

同一timestampのイベント順序をFrontendが独自に並べ替えてはならない。

---

### 1.11 Explicit State over Inference

状態は可能な限り明示的に保持する。

Frontendに状態推測を要求してはならない。

不適切な例:

```text
closedAt があるから Position は CLOSED だろう
orderId がないから注文未送信だろう
confidence が低いから HOLD だろう
```

適切な例:

```json
{
  "positionState": "CLOSED",
  "executionState": "NOT_SENT",
  "decision": "HOLD"
}
```

状態を表すフィールドはEnumを使用する。

Booleanの多用による矛盾状態を避ける。

不適切:

```json
{
  "isOpen": true,
  "isClosed": true,
  "isPending": false
}
```

適切:

```json
{
  "state": "OPEN"
}
```

複数の独立軸が必要な場合のみ、別Enumとして分離する。

例:

```json
{
  "lifecycleState": "OPEN",
  "executionState": "FILLED",
  "riskState": "NORMAL"
}
```

---

### 1.12 Null, Missing, Unknown, and Not Applicable

以下は別の意味として扱う。

- フィールド欠損
- `null`
- `UNKNOWN`
- `NOT_AVAILABLE`
- `NOT_APPLICABLE`
- `NOT_CALCULATED`
- `ERROR`

#### Missing

スキーマ違反、旧Version、または不正データの可能性がある。

#### null

フィールドは存在するが、値がまだ確定していない、または意図的に空である。

#### UNKNOWN

本来値が存在するが、現時点で安全に判断できない。

#### NOT_AVAILABLE

外部ソースまたは現在の環境では取得できない。

#### NOT_APPLICABLE

当該Entity・状態には適用されない。

#### NOT_CALCULATED

処理がまだ実行されていない。

#### ERROR

処理を試行したが失敗した。

例:

```json
{
  "spoofingScore": null,
  "spoofingState": "NOT_CALCULATED"
}
```

```json
{
  "executionOrderId": null,
  "executionState": "NOT_APPLICABLE"
}
```

```json
{
  "liquidityScore": null,
  "liquidityState": "ERROR",
  "errorCode": "ORDER_BOOK_GAP"
}
```

`null`をゼロとして扱ってはならない。

`UNKNOWN`を安全確認済みとして扱ってはならない。

---

### 1.13 Fail-Closed Data Interpretation

安全に関係するデータが欠損、不正、古い、矛盾、またはUNKNOWNの場合、実行許可側へ倒してはならない。

例:

```text
Governance data missing
→ executionAllowed = false

Feature Snapshot stale
→ decision executable = false

Position state unknown
→ new order blocked

Model result malformed
→ AI decision invalid
```

Fail-closed対象:

- Governance
- executionAllowed
- realOrderAllowed
- Position state
- Pending Order state
- Emergency state
- Feature freshness
- Strategy validity
- AI response validity
- Consensus validity
- Exchange mode
- Paper / Live mode
- Symbol consistency

表示上も、UNKNOWNを正常なグレー表示だけで済ませず、監査可能なreasonを保持する。

---

### 1.14 Data Freshness

すべてのリアルタイムSnapshotは、鮮度判定可能でなければならない。

最低限、以下を持つ。

- `sourceTimestamp`
- `createdAt`
- `freshnessState`
- `ageMs`
- `maxAgeMs`
- `staleReason`

推奨Enum:

```text
FRESH
AGING
STALE
EXPIRED
UNKNOWN
```

鮮度基準はEntity種別ごとに異なる。

例:

- Order Book: 非常に短い
- Recent Trades: 短い
- Feature Snapshot: 短い
- AI Decision: 判断対象Snapshotとの対応関係で評価
- Position: 取引所同期状況を含めて評価
- Historical Timeline: 鮮度ではなく完全性を評価

Frontendが現在時刻との差だけで独自にSTALE判定する場合でも、Backendの正式な`freshnessState`を上書きしてはならない。

Frontend側の表示用経過時間と、Backend側の安全判定は分離する。

---

### 1.15 Cross-Entity Traceability

判断から注文結果までを、一意に追跡できなければならない。

最低限、以下の参照関係を保持する。

```text
Feature Snapshot
    ↓
Strategy Decision
    ↓
LSTM Decision
    ↓
LLM Decision
    ↓
Consensus Decision
    ↓
Governance Decision
    ↓
Execution Attempt
    ↓
Order
    ↓
Position
```

主要参照例:

- `featureSnapshotId`
- `strategyDecisionId`
- `lstmDecisionId`
- `llmDecisionId`
- `consensusDecisionId`
- `governanceDecisionId`
- `executionAttemptId`
- `orderId`
- `positionId`
- `timelineEventIds`
- `markerIds`
- `railwayCycleId`
- `replaySessionId`

すべての段階が必ず成功するとは限らない。

途中で抑止された場合も、どこまで進んだかを追跡できる構造にする。

例:

```text
Feature Snapshot exists
Strategy HOLD
LSTM not invoked
LLM not invoked
Consensus NOT_APPLICABLE
Governance NOT_EVALUATED
Execution NOT_SENT
```

---

### 1.16 Model Versioning and Reproducibility

AI判断およびDetector判断を再現するため、使用したロジックのVersionを保持する。

最低限:

- `schemaVersion`
- `detectorVersion`
- `featureBuilderVersion`
- `strategyVersion`
- `lstmModelVersion`
- `llmModelVersion`
- `consensusVersion`
- `governancePolicyVersion`
- `executionVersion`
- `configurationVersion`

必要に応じて以下も保持する。

- model name
- model provider
- prompt version
- threshold profile
- feature set version
- source code commit
- deployment version
- runtime instance ID

LLMについては、完全な決定論的再現が保証できない場合がある。

その場合でも、少なくとも以下を保存する。

- 入力データ
- システム指示またはprompt version
- model identifier
- temperature等の主要parameter
- raw response
- parsed response
- validation result
- latency
- token usage
- retry count

---

### 1.17 Raw Data and Derived Data

データは、raw data と derived data を区別する。

#### Raw Data

外部ソースまたは実行系から受け取った原始データ。

例:

- Exchange Order Book update
- Trade execution feed
- Order response
- Position response
- LLM raw response

#### Derived Data

TradingAIが計算・分類した値。

例:

- Buy Pressure
- Liquidity Score
- Momentum
- Spoofing suspicion
- Strategy confidence
- Consensus score
- Event severity

Derived Dataは、可能な範囲で元データ参照を持つ。

```json
{
  "featureSnapshotId": "fs_...",
  "sourceEventIds": ["evt_...", "evt_..."],
  "calculationVersion": "feature-builder-2.1.0"
}
```

表示用に丸めた値と、内部計算値も分離する。

```json
{
  "rawValue": 0.6738421,
  "displayValue": 0.67
}
```

APIで両方を返す必要がない場合でも、Backend内部または永続化層では精度を失わない。

---

### 1.18 Normalized Values and Units

数値は単位を明示する。

フィールド名、metadata、またはschemaで単位を確定する。

例:

- `price`
- `quantity`
- `notionalUsdt`
- `latencyMs`
- `spreadBps`
- `volatilityPct`
- `confidence`
- `pressureScore`
- `timestamp`

0〜1正規化値と百分率を混同してはならない。

例:

```text
confidence = 0.82
confidencePct = 82.0
```

標準方針:

- 内部confidence: 0.0〜1.0
- UI表示: 0〜100%
- Basis Points: `spreadBps`
- Percent: `volatilityPct`
- Milliseconds: `latencyMs`
- Currency: suffixまたはcurrency fieldを持つ
- Quantity: asset単位を明示
- Price: quote currencyを明示

異常値は暗黙にclampせず、validation errorとして扱う。

---

### 1.19 Extensibility

将来、以下が追加されることを前提とする。

- 新しい取引所
- 新しい銘柄
- Spot / Futures / Options
- 新しいDetector
- 新しいFeature
- 複数Strategy
- 複数LSTM
- 複数LLM
- 複数Consensus方式
- 新しいGovernance Policy
- 複数Execution venue
- Portfolio単位のPosition
- 複数Position同時管理

拡張性のため、固定フィールドと拡張フィールドを分離する。

例:

```json
{
  "detectorType": "SPOOFING",
  "state": "SUSPECTED",
  "score": 0.71,
  "evidence": {},
  "extensions": {}
}
```

ただし、`extensions`へ主要フィールドを逃がしてはならない。

UI・安全判定・検索・監査で使用する値は正式スキーマとして定義する。

---

### 1.20 Exchange Neutrality

Core Entityは、特定取引所のレスポンス構造に直接依存してはならない。

取引所固有データはadapter層で正規化する。

Coreモデル例:

```json
{
  "exchange": "KUCOIN_FUTURES",
  "symbol": "XRPUSDTM",
  "normalizedSymbol": "XRPUSDT",
  "marketType": "FUTURES"
}
```

取引所固有情報が必要な場合:

```json
{
  "exchangeMetadata": {
    "contractCode": "XRPUSDTM",
    "nativeOrderId": "..."
  }
}
```

FrontendはKuCoin固有レスポンスを直接解釈してはならない。

---

### 1.21 Live and Replay Parity

Replayは、Liveとは別の簡易データ構造を使用してはならない。

Live表示とReplay表示は、原則として同じCore Entityを使用する。

差分はcontextで表現する。

```json
{
  "context": {
    "mode": "REPLAY",
    "replaySessionId": "rpl_...",
    "readOnly": true
  }
}
```

Live:

```json
{
  "context": {
    "mode": "LIVE",
    "replaySessionId": null,
    "readOnly": true
  }
}
```

Replay専用情報はReplay Session、Replay Cursor等に分離する。

これにより、Frontend ComponentをLive用とReplay用に重複実装することを避ける。

---

### 1.22 Position-Centric and Time-Centric Views

MARKET INTELLIGENCEは、2種類の主要な参照軸を持つ。

#### Position-Centric

特定Positionを中心に、関連する判断・注文・Marker・Timelineを参照する。

```text
Position
├─ Entry Decisions
├─ Entry Orders
├─ Entry Markers
├─ Management Events
├─ Exit Decisions
├─ Exit Orders
└─ Close Result
```

#### Time-Centric

特定時刻またはReplay Cursorを中心に、その時点の市場・判断状態を参照する。

```text
Timestamp
├─ Order Book
├─ Recent Trades
├─ Feature Snapshot
├─ Decisions
├─ Governance
├─ Execution
└─ Active Positions
```

データモデルは両方の検索を可能にする。

各Entityは必要に応じて以下を持つ。

- `positionId`
- `eventTimestamp`
- `featureSnapshotId`
- `replaySessionId`
- `railwayCycleId`

---

### 1.23 UI Model and Domain Model Separation

Domain Model と UI State Model を分離する。

#### Domain Model

Backendが管理する事実。

例:

- Position
- Feature Snapshot
- Decision
- Governance Result
- Timeline Event
- Marker
- Replay Session

#### UI State Model

Frontendだけが管理する表示状態。

例:

- selectedPositionId
- selectedTimelineEventId
- expandedGroupIds
- inspectorTab
- replaySpeed
- visibleTimeRange
- hoveredMarkerId
- railwayZoom
- panelWidth

UI StateをBackendのDomain Entityへ保存してはならない。

ただし、ユーザーセッションを跨ぐ表示設定を保存する場合は、Domain APIとは別のPreference Modelとして管理する。

---

### 1.24 Read Model Optimization

MARKET INTELLIGENCEは、詳細な監査可能性と高頻度表示を両立する必要がある。

そのため、Backendは用途別のRead Modelを提供できる。

例:

- Current Intelligence Snapshot
- Position Detail View
- Timeline Page
- Railway View
- Marker View
- Replay Frame
- Inspector Detail

Read ModelはCore Entityを基に構築する。

Read Model内で新しい意味を作ってはならない。

例:

```text
Core:
GovernanceDecision.state = BLOCKED

Read Model:
finalStatusLabel = "BLOCKED BY GOVERNANCE"
```

`finalStatusLabel`は表示用であり、Coreの`state`を置換しない。

---

### 1.25 Pagination and Bounded Data

Timeline、Recent Trades、Order Book history、Replay frame等は無制限配列として返してはならない。

APIは以下のいずれかを採用する。

- Cursor Pagination
- Time Range Query
- Sequence Range Query
- Limit + continuation token

推奨:

```text
cursor-based pagination
```

理由:

- 高頻度イベントでoffsetが不安定
- Live追加中でも重複・欠落を防ぎやすい
- Replayと相性が良い

レスポンス例:

```json
{
  "items": [],
  "nextCursor": "cur_...",
  "hasMore": true
}
```

Frontendは全履歴を一度に要求してはならない。

---

### 1.26 Data Integrity

Entity間の整合性を検証する。

例:

- DecisionのsymbolとFeature Snapshotのsymbolが一致
- Governance DecisionのconsensusDecisionIdが存在
- Execution AttemptのgovernanceDecisionIdが存在
- PositionのentryOrderIdが同一symbol
- MarkerのpositionIdが存在
- Timeline EventのentityReferenceが存在
- Replay CursorがSession範囲内
- Event sequenceがSession内で一意
- Live modeでReplay専用状態が混入しない

不整合時は、暗黙補正せずvalidation errorを生成する。

必要に応じてTimelineへ以下を記録する。

```text
DATA_INTEGRITY_ERROR
REFERENCE_NOT_FOUND
SYMBOL_MISMATCH
SEQUENCE_CONFLICT
SCHEMA_VERSION_UNSUPPORTED
```

---

### 1.27 Error Modeling

エラーは文字列だけで表現してはならない。

標準Error Modelを使用する。

最低限:

```json
{
  "code": "ORDER_BOOK_GAP",
  "message": "Order book sequence gap detected.",
  "severity": "HIGH",
  "retryable": true,
  "source": "ORDER_BOOK_PROCESSOR",
  "occurredAt": "2026-07-19T05:42:31.482Z",
  "metadata": {}
}
```

Errorは対象Entityに関連付ける。

- `error`
- `errors`
- `validationErrors`
- `processingErrors`

ユーザー表示用messageと、機械判定用codeを分離する。

Frontendはmessage文字列を解析して処理分岐してはならない。

---

### 1.28 Security and Sensitive Data

MARKET INTELLIGENCE用モデルには、以下を含めてはならない。

- API Secret
- API Passphrase
- Private Key
- Authorization Header
- Session Token
- Full credential
- 不要な個人情報

LLM raw request / responseを保存する場合も、秘密情報が含まれないようにsanitizeする。

Order IDやPosition情報は運用上必要だが、外部共有ログではmask可能な構造にする。

---

### 1.29 Performance Principles

高頻度データを扱うため、以下を原則とする。

- Full Snapshotの過剰送信を避ける
- Incremental Updateを使用可能にする
- 大容量evidenceを必要時取得に分離する
- Timeline詳細をlazy load可能にする
- Inspector詳細を選択時取得可能にする
- Order Bookは表示深度を制限する
- Replay frameはprefetch可能にする
- 同一Entityの重複payloadを避ける

ただし、性能最適化によって意味や監査情報を失ってはならない。

軽量一覧モデルと完全詳細モデルを分離する。

---

### 1.30 Schema Ownership

各モデルにはBackend側のownerを明確にする。

| Model | Primary Owner |
|---|---|
| Order Book | Market Data / Exchange Adapter |
| Recent Trades | Market Data / Exchange Adapter |
| Feature Snapshot | Feature Builder |
| Strategy Decision | Python Strategy |
| LSTM Decision | LSTM Engine |
| LLM Decision | LLM Engine |
| Consensus Decision | Consensus Engine |
| Governance Decision | Governance |
| Execution Attempt | Execution |
| Order | Execution / Exchange Adapter |
| Position | Execution / Position Manager |
| Timeline Event | Timeline Aggregator |
| Railway Cycle | Intelligence Orchestrator |
| Marker | Marker Builder / Execution Observer |
| Replay Session | Replay Engine |
| Inspector State | Frontend |
| Serialization Schema | Shared Contract |

複数モジュールが同一フィールドを別々に生成してはならない。

---

### 1.31 Compatibility Philosophy

スキーマ変更は、以下に分類する。

#### Backward-Compatible

- Optional field追加
- 新Enum値追加。ただしConsumerがUNKNOWN fallbackを持つ場合
- Metadata追加
- 新しいEvent Category追加
- 新しいDetector追加

#### Potentially Breaking

- Required field追加
- Field rename
- Field type変更
- Enum意味変更
- Nullability変更
- Timestamp semantics変更
- ID semantics変更
- 単位変更
- 0〜1から0〜100への変更

Breaking Changeは`schemaVersion`を更新し、移行方針を定義する。

Frontendは未対応Versionを無理に表示せず、安全なUnsupported Stateを表示する。

---

### 1.32 Naming Convention

JSONフィールドは `camelCase` を標準とする。

Python内部では `snake_case` を使用できるが、API serialization時に統一する。

推奨:

```text
featureSnapshotId
createdAt
executionAllowed
suppressionReason
```

Enum値は `UPPER_SNAKE_CASE` とする。

```text
BUY
SELL
HOLD
NOT_SENT
GOVERNANCE_BLOCKED
```

Entity ID prefix例:

```text
fs_   Feature Snapshot
sd_   Strategy Decision
ld_   LSTM Decision
llm_  LLM Decision
cd_   Consensus Decision
gd_   Governance Decision
exa_  Execution Attempt
ord_  Order
pos_  Position
evt_  Timeline Event
grp_  Timeline Group
rwy_  Railway Cycle
mrk_  Marker
rpl_  Replay Session
```

prefixは必須ではないが、採用する場合は全システムで統一する。

---

### 1.33 Minimum Audit Envelope

主要Entityは、共通監査情報を持つ。

推奨共通構造:

```json
{
  "id": "entity_id",
  "schemaVersion": "1.0.0",
  "createdAt": "2026-07-19T05:42:31.482Z",
  "updatedAt": "2026-07-19T05:42:31.482Z",
  "source": "MODULE_NAME",
  "runtimeInstanceId": "runtime_...",
  "deploymentVersion": "git_commit_or_release",
  "correlationId": "corr_..."
}
```

すべての高頻度Market Eventへ完全な監査Envelopeを付ける必要はない。

ただし、判断・Governance・Execution・Position・Replay等の重要Entityでは追跡可能性を確保する。

---

### 1.34 Correlation Model

一連の処理を横断追跡するため、`correlationId`を使用する。

例:

```text
Market Event
  correlationId = corr_123
Feature Snapshot
  correlationId = corr_123
Strategy Decision
  correlationId = corr_123
LLM Decision
  correlationId = corr_123
Governance Decision
  correlationId = corr_123
Execution Attempt
  correlationId = corr_123
```

Positionのライフサイクル全体は別の`positionId`で追跡する。

つまり:

- `correlationId`: 1回の判断・実行パイプライン
- `positionId`: Position全体
- `railwayCycleId`: Railway上の1判断サイクル
- `replaySessionId`: Replay操作セッション

これらを混同しない。

---

### 1.35 Data Model Non-Goals

本仕様は以下を目的としない。

- 取引戦略アルゴリズムそのものの定義
- Detectorの数式詳細
- LSTM学習仕様
- LLM prompt全文
- Governance policyの全ルール
- Exchange API client実装
- Database製品の固定
- Frontend ComponentのCSS定義
- Network protocolの最終決定
- 完全なEvent Sourcing基盤の強制
- Live取引許可条件の緩和

これらは別仕様書で管理する。

本仕様は、それらの結果を一貫して表現・保存・伝達・表示するためのデータ契約を定義する。

---

### 1.36 Chapter 1 Definition of Done

Chapter 1は、以下をすべて満たした場合に完成とする。

- Backend authoritative原則が定義されている
- Frontendの非責務が定義されている
- Python、LSTM、LLM、Consensus、Governance、Executionの責務境界が明確である
- Governance最上位原則が定義されている
- SnapshotとEventの違いが定義されている
- Historical Recordのimmutable原則が定義されている
- Stable IDとEntity参照原則が定義されている
- UTC時刻、sequence、orderingが定義されている
- null、missing、unknown等の意味が分離されている
- fail-closed原則が定義されている
- freshness判定が定義されている
- Cross-Entity Traceabilityが定義されている
- Model Versioningと再現性が定義されている
- Raw DataとDerived Dataが分離されている
- 単位と正規化値の原則が定義されている
- Exchange Neutralityが定義されている
- LiveとReplayの共通モデル方針が定義されている
- Domain ModelとUI Stateが分離されている
- Error ModelとData Integrity方針が定義されている
- CompatibilityとNaming Conventionが定義されている
- Correlation Modelが定義されている
- 本仕様のNon-Goalsが明確である

---

## Chapter 1 Status

```text
STATUS: COMPLETE
DOCUMENT: 05_DATA_MODEL_SPEC
CHAPTER: 1
TITLE: Data Model Philosophy
```


---

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


---


# 05_DATA_MODEL_SPEC

# Chapter 3 — Feature Snapshot

## 3.1 Purpose

Feature Snapshot は、Python Detector 群が市場から抽出した特徴量を、
AI・Strategy・Replay・Timeline・Inspector が共通利用するための
唯一の authoritative 市場特徴モデルである。

Feature Snapshot は以下を満たす。

- Detector の生データを統合する
- Strategy の唯一の入力となる
- LSTM / LLM の共通入力となる
- Replay で完全再現できる
- Timeline / Railway から参照できる
- Frontend は再計算しない

---

## 3.2 Snapshot Domains

Feature Snapshot は最低限以下の Domain を持つ。

- Order Book
- Recent Trades
- Liquidity
- Buy / Sell Pressure
- Momentum
- Volatility
- Spread
- Absorption
- Fake Pressure
- Iceberg
- Spoofing
- Market Context
- Detector Health
- Feature Freshness

---

## 3.3 Core Model

```json
{
  "id":"fs_01...",
  "symbol":"XRPUSDT",
  "exchange":"KUCOIN_FUTURES",
  "snapshotTimestamp":"2026-07-19T05:42:31.482Z",
  "orderBook":{},
  "recentTrades":{},
  "liquidity":{},
  "pressure":{},
  "momentum":{},
  "volatility":{},
  "spread":{},
  "absorption":{},
  "spoofing":{},
  "iceberg":{},
  "marketContext":{},
  "freshness":{
      "state":"FRESH",
      "ageMs":18
  }
}
```

---

## 3.4 Order Book Domain

保持対象例

- Top N Bid
- Top N Ask
- Mid Price
- Spread
- Best Bid
- Best Ask
- Total Bid Volume
- Total Ask Volume
- Imbalance
- Book Update Sequence

---

## 3.5 Recent Trades Domain

保持対象例

- Last Trade
- Trade Count
- Buy Market Volume
- Sell Market Volume
- Average Size
- VWAP
- Delta

---

## 3.6 Liquidity Domain

保持対象例

- Liquidity Score
- Bid Depth
- Ask Depth
- Large Wall Count
- Thin Book Detection

Score は 0.0〜1.0 を標準とする。

---

## 3.7 Pressure Domain

保持対象例

- Buy Pressure
- Sell Pressure
- Net Pressure
- Pressure Bias
- Pressure Confidence

---

## 3.8 Momentum Domain

保持対象例

- Momentum Score
- Persistence
- Acceleration
- Direction

---

## 3.9 Volatility Domain

保持対象例

- Current Volatility
- Short Window
- Long Window
- Volatility State

---

## 3.10 Spread Domain

保持対象例

- Current Spread
- Average Spread
- Spread Bps
- Spread State

---

## 3.11 Detector Domains

Detectorごとに以下を保持する。

- detectorName
- detectorVersion
- state
- score
- confidence
- evidence
- processingTimeMs

対象

- Absorption
- Fake Pressure
- Spoofing
- Iceberg

---

## 3.12 Market Context

例

- Session
- Trend
- Range
- Regime
- Risk Level

---

## 3.13 Freshness

```text
FRESH
AGING
STALE
EXPIRED
UNKNOWN
```

---

## 3.14 Feature Health

Detectorごとに

- READY
- DEGRADED
- FAILED
- DISABLED

を保持する。

---

## 3.15 Relationships

Feature Snapshot は以下へ参照される。

- Strategy Decision
- LSTM
- LLM
- Consensus
- Railway
- Timeline
- Replay

---

## 3.16 Validation

必須

- symbol
- timestamp
- freshness
- detectorVersion

異常

- symbol mismatch
- stale snapshot
- detector failure
- sequence gap

---

## 3.17 Review Checklist

- Feature Snapshot は唯一の市場特徴モデル
- Frontend は再計算しない
- Detector Domain が分離されている
- Freshness を保持する
- Replay 再現可能
- Strategy 入力と一致する
- Version 管理される

---

## Chapter 3 Status

STATUS: COMPLETE
TITLE: Feature Snapshot


---


# 05_DATA_MODEL_SPEC

# Chapter 4 — Decision Models

## 4.1 Purpose

Decision Models は MARKET INTELLIGENCE の判断チェーンを定義する。

```
Feature Snapshot
    ↓
Python Strategy
    ↓
LSTM
    ↓
LLM
    ↓
Consensus
    ↓
Governance
    ↓
Execution
```

各段階は独立した Entity を持ち、前段の結果を上書きしない。

---

## 4.2 Decision Principles

- Python が市場特徴を解析する。
- Strategy は最初の売買候補を生成する。
- LSTM は時系列補助評価を行う。
- LLM は総合判断を行う。
- Consensus は複数判断を統合する。
- Governance は最終安全判定を行う。
- Execution は注文実行のみ担当する。

---

## 4.3 Shared Decision Model

共通フィールド

- id
- featureSnapshotId
- inputReferences
- direction
- confidence
- reasoning
- suppressionReason
- processingTimeMs
- modelVersion
- createdAt

---

## 4.4 Python Strategy

責務

- BUY / SELL / HOLD 候補生成
- executionAllowed 初期判定
- suppressionReason
- deterministic 処理

出力

```
BUY
SELL
HOLD
```

---

## 4.5 LSTM Model

責務

- 時系列補助評価
- 継続性
- モメンタム維持
- ノイズ低減

出力

- direction
- confidence
- persistenceScore

---

## 4.6 LLM Model

責務

- Feature と Strategy を統合
- 相反証拠を評価
- 最終 AI 判断

保持

- promptVersion
- modelIdentifier
- rawResponse
- parsedResponse
- validationResult
- tokenUsage
- latencyMs

---

## 4.7 Consensus

入力

- Strategy
- LSTM
- LLM

保持

- finalDirection
- confidence
- agreementScore
- disagreementReason

Consensus は各モデルを書き換えない。

---

## 4.8 Governance

責務

- 安全判定
- 実行可否

状態

```
ALLOWED
BLOCKED
UNKNOWN
```

保持

- blockReason
- policyVersion

---

## 4.9 Execution Decision

Execution は判断を作らない。

保持

- submitted
- acknowledged
- filled
- rejected
- executionResult

---

## 4.10 Decision Chain

```
Feature Snapshot
→ Strategy
→ LSTM
→ LLM
→ Consensus
→ Governance
→ Execution
```

全段階は trace 可能である。

---

## 4.11 Direction Enum

```
BUY
SELL
HOLD
UNKNOWN
```

---

## 4.12 Confidence

内部表現

0.0〜1.0

UI

0〜100%

---

## 4.13 Suppression

例

- LOW_LIQUIDITY
- HIGH_SPREAD
- LOW_CONFIDENCE
- GOVERNANCE_BLOCK

---

## 4.14 Validation

- Feature Snapshot 必須
- direction 必須
- version 必須
- malformed response 拒否

---

## 4.15 Review Checklist

- Decision Chain が分離されている
- Governance が最上位
- Execution は判断しない
- 全 Decision が trace 可能
- HOLD を勝手に BUY に昇格しない
- Version 管理される

---

## Chapter 4 Status

STATUS: COMPLETE
TITLE: Decision Models


---


# 05_DATA_MODEL_SPEC

# Chapter 5 — Replay Models

## 5.1 Purpose

Replay Models は、MARKET INTELLIGENCE の判断・市場状態・Position・Timeline を
後から完全に再現するためのデータモデルを定義する。

Replay は分析・デバッグ・AI評価・検証を目的とし、
Live Trading を実行してはならない。

---

## 5.2 Replay Architecture

```
Replay Session
    ↓
Replay Cursor
    ↓
Replay Frame
    ├─ Feature Snapshot
    ├─ Decision Chain
    ├─ Timeline
    ├─ Railway
    ├─ Position
    └─ Marker
```

---

## 5.3 Replay Session

保持対象

- sessionId
- symbol
- exchange
- startTime
- endTime
- state
- playbackSpeed
- currentCursor
- createdAt

状態

```
READY
PLAYING
PAUSED
SEEKING
COMPLETED
FAILED
```

---

## 5.4 Replay Cursor

保持対象

- currentTimestamp
- eventSequence
- frameId
- progressPct

移動方法

- Play
- Pause
- Step Forward
- Step Backward
- Seek Timestamp
- Seek Position
- Seek Marker

---

## 5.5 Replay Frame

1フレームはある時刻の完全スナップショット。

含まれるもの

- Feature Snapshot
- Decision Chain
- Timeline Events
- Railway Cycle
- Active Positions
- Visible Markers

Frontend は Replay Frame を再計算しない。

---

## 5.6 Playback States

```
STOPPED
PLAYING
PAUSED
BUFFERING
SEEKING
ERROR
```

---

## 5.7 Playback Controls

対応操作

- Play
- Pause
- Resume
- Restart
- Jump Start
- Jump End
- Next Event
- Previous Event
- Speed Change

---

## 5.8 Playback Speed

標準

```
0.25x
0.5x
1x
2x
4x
8x
16x
```

高速再生でも Event の順序を変更しない。

---

## 5.9 Replay Integrity

Replay は以下を変更しない。

- Position
- Timeline
- Decision
- Marker

Replay は読み取り専用である。

---

## 5.10 Replay Validation

検証項目

- Frame 欠損
- Sequence Gap
- Timestamp Order
- Missing Decision
- Missing Feature Snapshot
- Broken Reference

---

## 5.11 Replay API Read Model

```
Replay Session
Replay Cursor
Replay Frame
Frame Entities
```

---

## 5.12 Review Checklist

- Replay は Read Only
- Live 注文しない
- Frame を再計算しない
- Event 順序を維持
- Position を変更しない
- Decision Chain を保持
- Railway を保持
- Timeline を保持
- Marker を保持

---

## Chapter 5 Status

STATUS: COMPLETE
TITLE: Replay Models


---


# 05_DATA_MODEL_SPEC

# Chapter 6 — Timeline Models

## 6.1 Purpose

Timeline Models は、MARKET INTELLIGENCE における市場・AI・Execution・Position の
出来事を時系列で記録・表示・Replayするための標準モデルを定義する。

Timeline は監査・デバッグ・分析・Replay の基盤であり、
過去イベントを上書きしない immutable event log を前提とする。

---

## 6.2 Timeline Philosophy

- Event は追加のみ
- 過去を書き換えない
- 全イベントは時系列で追跡可能
- Replay と同一イベントを利用する
- Position・Decision・Railway・Marker を相互参照する

---

## 6.3 Timeline Structure

```text
Timeline
 ├─ Timeline Group
 │    ├─ Timeline Event
 │    ├─ Timeline Event
 │    └─ Timeline Event
 └─ Timeline Event
```

---

## 6.4 Timeline Event

保持項目

- eventId
- eventType
- category
- severity
- timestamp
- sequence
- title
- summary
- references
- correlationId

---

## 6.5 Timeline Group

同一判断サイクルをまとめる。

保持項目

- groupId
- groupType
- state
- startTime
- endTime
- eventIds

---

## 6.6 Event Categories

- MARKET
- DETECTOR
- FEATURE
- STRATEGY
- LSTM
- LLM
- CONSENSUS
- GOVERNANCE
- EXECUTION
- ORDER
- POSITION
- RISK
- EMERGENCY
- REPLAY
- SYSTEM
- ERROR

---

## 6.7 Severity

- DEBUG
- INFO
- NOTICE
- WARNING
- HIGH
- CRITICAL

---

## 6.8 Ordering Rules

表示順序

1. eventTimestamp
2. sequence
3. createdAt
4. eventId

高速 Replay 中も順序を変更しない。

---

## 6.9 Event Relationships

Timeline Event は参照できる。

- Feature Snapshot
- Decision Chain
- Position
- Railway
- Marker
- Replay Frame

---

## 6.10 Immutable Rules

禁止事項

- Event 更新
- Event 削除
- Event 並び替え
- Event 内容書き換え

訂正は Correction Event を追加する。

---

## 6.11 Filtering

対応フィルター

- Time
- Category
- Severity
- Position
- Decision
- Replay
- Symbol

---

## 6.12 Search

検索対象

- eventId
- correlationId
- positionId
- symbol
- reasonCode
- decision

---

## 6.13 Timeline API

返却対象

- Timeline Events
- Timeline Groups
- Pagination Cursor
- Total Count

---

## 6.14 Validation

検証

- duplicate sequence
- timestamp order
- missing reference
- invalid category
- invalid severity

---

## 6.15 Review Checklist

- Event は immutable
- Group が定義される
- Replay と共通利用
- Event 順序維持
- Category 分離
- Severity 分離
- Filtering 対応
- Search 対応

---

## Chapter 6 Status

STATUS: COMPLETE
TITLE: Timeline Models


---


# 05_DATA_MODEL_SPEC

# Chapter 7 — Inspector Models

## 7.1 Purpose

Inspector は、MARKET INTELLIGENCE 内の任意の Entity を詳細に解析・監査するための
読み取り専用モデルである。

Inspector は市場データ・AI判断・Execution・Position・Replay の根拠を
一画面で確認できることを目的とする。

---

## 7.2 Design Principles

- Read Only
- Entity を変更しない
- Authoritative Data を表示する
- Timeline / Railway / Replay と連携する
- 相互参照を提供する

---

## 7.3 Supported Entities

- Feature Snapshot
- Strategy Decision
- LSTM Decision
- LLM Decision
- Consensus
- Governance
- Execution
- Position
- Timeline Event
- Railway Cycle
- Marker

---

## 7.4 Inspector Layout

```text
Header
 ├─ Entity Summary
 ├─ State
 ├─ Timestamp

Body
 ├─ Properties
 ├─ References
 ├─ Timeline
 ├─ Railway
 ├─ Raw Data
 ├─ Validation
 └─ Related Entities
```

---

## 7.5 Entity Summary

保持項目

- entityId
- entityType
- state
- createdAt
- updatedAt
- source
- schemaVersion

---

## 7.6 Properties Panel

表示対象

- Core Fields
- Domain Fields
- Metrics
- Confidence
- Risk
- Status

---

## 7.7 References Panel

表示対象

- Parent Entity
- Child Entities
- Related Timeline
- Related Position
- Related Replay
- Related Marker

---

## 7.8 Validation Panel

表示

- Validation Result
- Missing Fields
- Unknown State
- Freshness
- Schema Version

---

## 7.9 Raw Data

Raw JSON を表示可能。

- Pretty Print
- Collapse
- Copy

Raw Data は編集不可。

---

## 7.10 Inspector State

```
READY
LOADING
NOT_FOUND
PARTIAL
ERROR
```

---

## 7.11 Navigation

対応

- Position → Timeline
- Timeline → Railway
- Railway → Decision
- Decision → Feature Snapshot
- Marker → Position
- Replay → Frame

---

## 7.12 API Model

返却

- entity
- references
- validation
- relatedEntities
- rawData

---

## 7.13 Validation

確認

- missing entity
- invalid reference
- stale entity
- unsupported schema
- unknown state

---

## 7.14 Review Checklist

- Read Only
- Entity 編集不可
- Raw JSON 表示
- Validation 表示
- 相互参照可能
- Timeline 連携
- Railway 連携
- Replay 連携

---

## Chapter 7 Status

STATUS: COMPLETE
TITLE: Inspector Models


---


# 05_DATA_MODEL_SPEC

# Chapter 8 — Serialization

## 8.1 Purpose

Serialization は、Backend・Frontend・Replay・保存層の間で
Core Entity を一貫した形式で交換するためのルールを定義する。

本章は JSON を標準フォーマットとし、将来的な MessagePack や
Protocol Buffers 等への拡張も妨げない設計を前提とする。

---

## 8.2 Serialization Principles

- Backend が Authoritative
- JSON を標準とする
- UTF-8 エンコード
- UTC タイムスタンプ
- camelCase のキー名
- Enum は文字列で表現
- Null と Missing を区別する
- Frontend は受信データを再計算しない

---

## 8.3 Standard Envelope

すべての API Response は以下を基礎とする。

```json
{
  "schemaVersion":"1.0.0",
  "generatedAt":"2026-07-19T05:42:31.482Z",
  "context":{
    "mode":"LIVE",
    "readOnly":true
  },
  "data":{}
}
```

---

## 8.4 Primitive Rules

- string
- number
- boolean
- object
- array
- null

数値は IEEE-754 を前提とする。

---

## 8.5 Date & Time

- ISO-8601
- UTC
- ミリ秒精度
- タイムゾーン省略禁止

例

```
2026-07-19T05:42:31.482Z
```

---

## 8.6 Enum Rules

Enum は数値ではなく文字列。

例

```
BUY
SELL
HOLD
```

未知の Enum は UNKNOWN として扱う。

---

## 8.7 Identifier Rules

ID は文字列。

例

- pos_xxx
- evt_xxx
- fs_xxx
- rwy_xxx
- mrk_xxx

意味を持たない一意識別子とする。

---

## 8.8 Null Rules

Null は

「値は存在するが未設定」

Missing は

「フィールドが存在しない」

として扱う。

---

## 8.9 Versioning

schemaVersion を必須とする。

Major 変更では互換性を保証しない。

Minor 変更では後方互換を維持する。

---

## 8.10 Forward Compatibility

未知フィールド

- 無視可能

未知 Entity

- Unsupported Entity として保持

未知 Enum

- UNKNOWN

---

## 8.11 Validation

受信時

- schemaVersion
- entityType
- id
- timestamp
- required fields

を検証する。

---

## 8.12 Serialization Errors

例

- INVALID_SCHEMA
- UNSUPPORTED_VERSION
- INVALID_ENUM
- INVALID_TIMESTAMP
- MISSING_REQUIRED_FIELD
- INVALID_REFERENCE

---

## 8.13 API Guidelines

- gzip 圧縮対応
- Pagination 対応
- Cursor 対応
- Partial Response 可
- Immutable Entity

---

## 8.14 Review Checklist

- JSON 標準
- UTF-8
- UTC
- camelCase
- schemaVersion 必須
- Enum は文字列
- Null と Missing を区別
- Forward Compatibility 対応

---

## Chapter 8 Status

STATUS: COMPLETE
TITLE: Serialization


---


# 05_DATA_MODEL_SPEC

# Chapter 9 — Validation Rules

## 9.1 Purpose

Validation Rules は、MARKET INTELLIGENCE の全データモデルに対して
整合性・安全性・再現性を保証するための共通検証規則を定義する。

Validation は Fail Closed を基本方針とする。

---

## 9.2 Validation Layers

1. Schema Validation
2. Field Validation
3. Enum Validation
4. Relationship Validation
5. State Validation
6. Time Validation
7. Business Validation
8. Replay Validation
9. API Validation

---

## 9.3 Required Field Validation

必須項目例

- id
- entityType
- schemaVersion
- createdAt
- context
- source

必須項目欠落時は Validation Error とする。

---

## 9.4 Enum Validation

対象

- Direction
- State
- Severity
- Category
- Marker Type

未知値は UNKNOWN として扱うか、仕様上必須の場合はエラーとする。

---

## 9.5 Relationship Validation

検証対象

- Position → Timeline
- Timeline → Railway
- Railway → Decision
- Decision → Feature Snapshot
- Marker → Position

参照切れは INVALID_REFERENCE とする。

---

## 9.6 Time Validation

検証

- createdAt <= updatedAt
- openedAt <= closedAt
- startedAt <= completedAt
- Timestamp の逆転禁止

---

## 9.7 State Validation

例

- CLOSED Position は quantity = 0
- OPEN Position は quantity > 0
- BLOCKED Governance は Execution 不可
- Replay は readOnly

---

## 9.8 Business Validation

例

- Symbol 一致
- Exchange 一致
- CorrelationId 一致
- Replay Context 一致

---

## 9.9 Replay Validation

Replay では

- Frame 欠損
- Cursor 範囲外
- Event 順序逆転
- Snapshot 欠落

を検出する。

---

## 9.10 Freshness Validation

状態

- FRESH
- AGING
- STALE
- EXPIRED
- UNKNOWN

STALE 以上は警告または Fail Closed の対象。

---

## 9.11 Error Codes

代表例

- INVALID_SCHEMA
- INVALID_STATE
- INVALID_REFERENCE
- INVALID_TIMESTAMP
- INVALID_SEQUENCE
- SYMBOL_MISMATCH
- STALE_DATA
- UNKNOWN_STATE
- REPLAY_OUT_OF_RANGE

---

## 9.12 Validation Result Model

```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "checkedAt": "2026-07-19T05:42:31.482Z"
}
```

---

## 9.13 API Requirements

Validation Result は

- Inspector
- Replay
- Timeline
- Railway

から参照可能とする。

---

## 9.14 Review Checklist

- 必須項目検証
- Enum 検証
- State 検証
- Time 検証
- Relationship 検証
- Replay 検証
- Freshness 検証
- Error Code 定義
- Fail Closed 方針

---

## Chapter 9 Status

STATUS: COMPLETE
TITLE: Validation Rules
