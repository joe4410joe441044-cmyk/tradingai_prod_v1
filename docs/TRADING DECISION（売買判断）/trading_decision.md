# TL-UI-ALIGN-1
# Trading Decision / Trading Lifecycle Monitor 実経路整合・UI拡張指示書

## 1. 背景

TradingAIには既存の

TRADING DECISION（売買判断）

画面が存在する。

現在この画面には主として、

MARKET
↓
PYTHON STRATEGY
↓
MONEY MANAGEMENT
↓
GOVERNANCE
↓
EXECUTION
↓
POSITION

というDecision Pipelineが表示されている。

また、

FINAL DECISION
CURRENT STATE
BLOCKING STAGE
BLOCKING REASON
CURRENT BLOCK CONTEXT
ENTRY READINESS

等が存在し、

「現在どこまで判断が進み、
どこで、なぜ止まっているか」

を表示する原型はすでに存在している。


しかしこれは現状、

Trading Lifecycle全体ではなく、
主としてEntryまでのDecision Pipelineを
可視化したものである。


TL-E2E-AUDIT-1-R1によって、
Production PAPER Runtimeで実際に通る
Trading Lifecycleを監査した。


今回のUI修正では、

設計上こうあるべき

ではなく、

TL-E2E-AUDIT-1-R1で
実際に観測・証明されたRuntime経路

をauthorityとして使用する。


--------------------------------------------------

## 2. この画面の最終的な役割

この画面を単なる設定画面や
フロー図にはしない。


最終的な役割は、

TRADING LIFECYCLE MONITOR

とする。


ユーザーがこの画面を見ることで、
最低でも次の3点が分かること。


1.
TradingAIは今どこにいるのか


2.
なぜその状態なのか


3.
直前のTrading Cycleで何が起きたのか


--------------------------------------------------

## 3. 基本原則

UI表示と実Runtimeを一致させる。


禁止:

存在しないRuntime Nodeを
想像で追加すること。

設計書だけを根拠に
CONNECTEDと表示すること。

未観測経路を
正常動作しているように表示すること。

UNKNOWNをREADYへ変換すること。

NOT REACHEDをPASSとして扱うこと。

UI独自ロジックで
Trading Decisionを生成すること。


Runtime authorityに存在しない情報は、

UNKNOWN

NOT AVAILABLE

NOT EXPOSED

NOT OBSERVED

等として明示する。


--------------------------------------------------

## 4. TL-E2E-AUDIT-1-R1をAuthorityとして読む

最初に監査Reportから以下を抽出する。


A. Runtime Nodes

実際に存在するNode


B. Runtime Edges

実際に接続されているNode間経路


C. Entry Path

注文候補からPosition OPENまで


D. No-Trade Path

取引しなかった場合のNext Loopまで


E. Exit Path

Position OPENからFLATまで


F. State Update Path

PnL
Risk
Exposure
Position
その他実在する更新


G. Next Loop

次Cycleへ戻る実経路


H. Trading AI

実際のRuntime pathに存在するか


I. Supervisor

Lifecycle上のauthorityか、
observerか


J. AI Advisor

Lifecycle上のauthorityか、
advisory onlyか


K. Market Recorder

Lifecycle上の位置


これを表にしてからUI変更を開始する。


--------------------------------------------------

## 5. CURRENT IMPLEMENTED LIFECYCLEを確定

TL-E2E-AUDIT-1-R1の実測結果から、

CURRENT IMPLEMENTED TRADING LIFECYCLE

を一本の経路として作成する。


例:

BOT START
↓
LOOP
↓
MARKET DATA
↓
ACTIVE SYMBOL
↓
MARKET INTELLIGENCE
↓
STRATEGY
↓
...

以降は監査結果を使用。


この例をそのまま実装してはいけない。

必ず実測結果へ置換する。


--------------------------------------------------

## 6. 現在のDecision Pipelineとの比較

既存UI:

MARKET
↓
PYTHON STRATEGY
↓
MONEY MANAGEMENT
↓
GOVERNANCE
↓
EXECUTION
↓
POSITION


について各Nodeを、

MATCH

PARTIAL

MISSING

EXTRA

WRONG ORDER

NOT CONNECTED

UNKNOWN

で分類する。


既存UIをすぐ変更せず、
最初に差分表を作る。


--------------------------------------------------

## 7. 画面構造

基本的に現在の
TRADING DECISION画面を再利用する。

全面作り直しを避ける。


既存の視認性、

FINAL DECISION

CURRENT STATE

BLOCKING STAGE

BLOCKING REASON

CURRENT BLOCK CONTEXT

ENTRY READINESS

は可能な限り維持する。


その上でLifecycle表示を拡張する。


--------------------------------------------------

## 8. Current Lifecycle

画面の最重要領域として、

CURRENT LIFECYCLE

を表示する。


目的:

今TradingAIがどこにいるのかを
一目で確認できること。


各Nodeには最低限、

Node Name
State
Reason
Timestamp

を表示可能にする。


必要なら、

Cycle ID

も使用する。


--------------------------------------------------

## 9. Node State

状態表示はRuntime authorityに基づく。


候補例:

WAITING

ACTIVE

READY

PASSED

BLOCKED

NOT REACHED

OPEN

FILLED

FLAT

COMPLETE

UNKNOWN

STALE


ただし実際に使用するenum/状態は
既存contractを優先する。


UI専用の意味の違う状態を
勝手に増やさない。


--------------------------------------------------

## 10. Blocking表示

現在の

BLOCKING STAGE
BLOCKING REASON
CURRENT BLOCK CONTEXT

は重要なので維持する。


取引しなかった場合、

どのNodeで止まったか

なぜ止まったか

後続NodeがなぜNOT REACHEDなのか

を説明できること。


例:

STRATEGY → HOLD

MM → RISK_LIMIT

GOVERNANCE → BLOCK

MARKET → STALE

など。


ただし実Runtimeで存在するReasonのみ使用。


--------------------------------------------------

## 11. Entry Lifecycle

監査でEntry経路が証明された場合、

Entryについて、

Candidate
↓
Risk / Size
↓
Governance
↓
Order
↓
Fill
↓
Position OPEN

の実際の経路を表示する。


名称と順序は監査結果に合わせる。


--------------------------------------------------

## 12. Position Lifecycle

現在UIはPOSITIONで終わっている。


これをTrading Lifecycle Monitorへ
発展させる場合、

Position OPEN後の実経路を追加する。


監査で確認されたものだけを使用。


候補:

POSITION OPEN

POSITION MONITOR

EXIT DECISION

EXIT EXECUTION

POSITION FLAT


ただし未実装なら表示上も
IMPLEMENTEDとして扱わない。


--------------------------------------------------

## 13. Exit Lifecycle

ExitはEntryと同等に重要。


確認する:

Exit authority

Exit trigger

Exit decision

Exit order

Exit fill

Position FLAT


1–3秒Exit等の短時間処理でも、
後から確認できる構造にする。


--------------------------------------------------

## 14. Cycle Completion

1 Cycleが完了したことを
明示できるようにする。


可能なら、

CYCLE ID

START TIME

ENTRY TIME

EXIT TIME

DURATION

RESULT

FINAL POSITION STATE

をRuntime authorityから表示。


存在しないfieldは追加しない。


--------------------------------------------------

## 15. Next Loop

Trading Lifecycleとして最重要。


取引成立後:

Position FLAT
↓
State Update
↓
Next Cycle


No Trade時:

Block / Hold
↓
Cycle Complete
↓
Next Cycle


の両方について、

実際にLoopへ戻ったことを
確認できる表示を検討する。


単にLOOP ONだから
循環したと判断しない。


--------------------------------------------------

## 16. Last Completed Cycle

高速取引では現在状態だけでは
人間が確認できない。


そのため、

LAST COMPLETED CYCLE

を設けることを検討する。


直前Cycleについて、

Decision

Blocking/Entry

MM

Governance

Execution

Position

Exit

Result

Duration

をcompactに表示。


詳細は折りたたみ可能とする。


--------------------------------------------------

## 17. CurrentとHistoryを分離

画面をログの羅列にしない。


上部:

CURRENT LIFECYCLE


中部:

CURRENT DECISION / BLOCK REASON


下部:

LAST COMPLETED CYCLE


さらに古いCycle:

HISTORY

へ格納。


現在のSupervisor Conversation Historyと同様に、
過去情報が画面を無限に伸ばさない構造にする。


--------------------------------------------------

## 18. Trading AI表示

現在:

TRADING AI: OFF
AI IMPLEMENTATION: NOT_INSTALLED

と表示されている。


TL-E2E-AUDIT-1-R1で
Trading AIの実装・接続状態を確認する。


監査結果が、

AI_NOT_IN_PATH

ならその事実を表示。


CONNECTEDなら、
どのNode間に存在するかを表示。


未証明ならUNKNOWN。


AI AdvisorをTrading AIとして
誤表示してはいけない。


SupervisorもTrading AIとして
扱ってはいけない。


--------------------------------------------------

## 19. Supervisorの位置

SupervisorがSHADOW / read-onlyであり、
Operational Effect NONEなら、

Lifecycle decision nodeとして
Pipelineへ挿入しない。


Observer / Oversightとして
別表示する。


監査で別の結果が証明された場合のみ変更。


--------------------------------------------------

## 20. AI Advisorの位置

AI Advisorがadvisory-onlyなら、

Execution Pipelineへ挿入しない。


Trading authorityと
advisory functionを混同しない。


--------------------------------------------------

## 21. Market Recorder

Market Recorderが
Lifecycle eventを記録している場合、

Decision authorityではなく、

RECORDING / OBSERVATION

として表現する。


実監査結果に従う。


--------------------------------------------------

## 22. 操作機能

この画面は基本的に、

OBSERVATION / EXPLANATION

画面とする。


Bot Start

Loop ON/OFF

Auto Trade ON/OFF

Emergency操作

注文操作

等を主目的にしない。


操作authorityは既存Operation側に残す。


この画面からTrading mutationを
新規追加しない。


--------------------------------------------------

## 23. UI目的

ユーザーが3秒程度見れば、

現在どこか

取引するのか/しないのか

止まった場所

止まった理由

Position状態

直前Cycle結果

Next Loopしたか

が把握できることを目標とする。


--------------------------------------------------

## 24. 詳細情報

Raw runtime fieldsやdiagnosticsを
常時大量表示しない。


通常表示:

人間向け要約


Details:

Raw state
timestamps
source
authority
reason code
cycle metadata


と分離する。


--------------------------------------------------

## 25. Stale / Unknown

現在存在する

STALE DECISION DATA

の思想は維持する。


STALEの場合、

古い判断をLIVE判断として
表示しない。


UNKNOWNの場合、

推測して埋めない。


--------------------------------------------------

## 26. History

Lifecycle Historyが既存で存在するか調査。


既存authorityがあれば再利用。


新しいDB/storeを作る前に、

Market Recorder

runtime history

audit/history

existing event store

を確認する。


同じ情報を複数DBへ
重複保存しない。


--------------------------------------------------

## 27. Performance

Microstructure Edge Runtimeを
UI監視のために遅くしてはいけない。


UIはobserver。


Lifecycle telemetryによって、

Strategy

Execution

Exit

Loop

のcritical pathへ
不要な同期I/Oを追加しない。


--------------------------------------------------

## 28. Safety

今回のUI変更によって、

Strategy decision

Money Management decision

Governance decision

Execution authority

Order routing

Exit logic

Bot control

Loop control

を変更しない。


Real Order禁止。


PAPER / Dry Runを維持。


--------------------------------------------------

## 29. 実装前Report

コード変更前に必ず以下を出す。


CURRENT IMPLEMENTED LIFECYCLE

UI CURRENT PIPELINE

DIFFERENCE TABLE

PROPOSED UI LIFECYCLE

DATA SOURCE MAP


各UI表示項目について、

Source

Authority

Freshness

Update timing

を明示。


ここで矛盾があればSTOP。


--------------------------------------------------

## 30. 実装

差分確定後に最小変更。


既存Trading Decision画面を
可能な限り再利用。


全面rewriteは禁止。


--------------------------------------------------

## 31. Tests

最低限:

Node ordering

Current state

Blocking stage

Blocking reason

NOT REACHED

UNKNOWN

STALE

Entry path

No-trade path

Position OPEN

Position FLAT

Exit path

Next cycle

Last completed cycle

History separation

Trading AI state

Supervisor observer-only

AI Advisor advisory-only


実装されていないケースは
無理にfixtureで正常化せず、
実contractに合わせる。


--------------------------------------------------

## 32. Production Verification

PAPERのみ。


Real Order禁止。


実際のRuntimeで、

UI Node

Runtime Node

State

Reason

Cycle ID

Timestamp

が一致するか確認。


可能ならTL-E2E-AUDIT-1-R1で使用した
同一観測データと照合する。


--------------------------------------------------

## 33. Final Report

# TL-UI-ALIGN-1 Final Report

### Verdict

### Audit Authority

### Current Implemented Lifecycle

### Previous UI Pipeline

### Difference Table

### Final UI Lifecycle

### Runtime Data Sources

### Current Lifecycle Verification

### Entry Verification

### No-Trade Verification

### Exit Verification

### Position Verification

### Next Loop Verification

### Last Completed Cycle

### History

### Trading AI Position

### Supervisor Position

### AI Advisor Position

### Market Recorder Position

### Automated Tests

### Production Verification

### Performance Impact

### PRE Trading Safety

### POST Trading Safety

### Git State

### Findings

### Final Conclusion


--------------------------------------------------

## 34. STOP

UIと実Runtimeの一致を確認して停止。


commit / pushは別途指示がない限り行わない。


Real Order禁止。


Execution Authority変更禁止。


Strategy変更禁止。


Money Management logic変更禁止。


Governance logic変更禁止。