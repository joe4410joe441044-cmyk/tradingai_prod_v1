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
