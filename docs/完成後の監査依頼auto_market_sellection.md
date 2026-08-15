# TradingAI 完成後 統合監査指示書

## 文書名

`TRADINGAI_POST_IMPLEMENTATION_INTEGRATION_AUDIT.md`

## 0. 目的

本監査は、AUTO MARKET
SELECTION（AMS）を含むTradingAIの主要実装工程が完了した後に実施する、全体統合監査である。

個別機能の単体PASSを再確認するだけではなく、今回までの多数の変更を統合した結果として、

-   Market Data
-   Active Symbol Authority
-   AUTO MARKET SELECTION
-   DOM / Order Book
-   Market Intelligence
-   Strategy
-   AI
-   Money Management
-   Governance
-   Execution
-   Emergency
-   Dashboard / Frontend

が、一つのTradingAIシステムとして正しく接続・同期されていることを確認する。

特に、現在実画面で確認されている「板情報（DOM）が表示されていない」事象を重要監査項目とする。

この監査は原則として機能実装完了後、Actual Live AUTO / Real
Orderの本格有効化前に実施する。

------------------------------------------------------------------------

# 1. 最重要原則

監査開始時点では安全側を維持すること。

原則:

-   realOrderAllowed = false
-   AUTO TRADE = OFF
-   実注文禁止
-   実注文キャンセル禁止
-   leverage変更禁止
-   margin変更禁止
-   transfer禁止
-   Governance authority変更禁止
-   Emergency authority変更禁止

監査のために安全機構を緩和してはならない。

Live環境のread-only情報が必要な場合も、private mutation
APIを使用してはならない。

------------------------------------------------------------------------

# 2. Git安全確認

開始時に必ず以下を記録する。

``` bash
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git status --short
```

既存dirty / untracked / deletedを保持する。

禁止:

``` text
git reset
git restore
git clean
git stash
既存差分を破棄するcheckout
```

監査段階では原則としてcommit / push / deployを行わない。

修正が必要な場合は、まずFindingとして報告し、修正工程を分離する。

------------------------------------------------------------------------

# 3. 監査方法

以下の順序で確認する。

``` text
Static Architecture Audit
        ↓
Backend Runtime Audit
        ↓
Market Feed / WebSocket Audit
        ↓
DOM / Market Intelligence Audit
        ↓
Decision Chain Audit
        ↓
MM / Governance / Execution Audit
        ↓
Frontend / Dashboard Audit
        ↓
Paper Integration Validation
        ↓
Regression Tests
        ↓
Finding Classification
```

単にtestがPASSすることだけを完成条件にしない。

実際のruntime data flowとFrontend表示を確認すること。

------------------------------------------------------------------------

# 4. Active Symbol Authority

BotManagerのauthoritative activeSymbolが唯一のruntime symbol
authorityとして維持されていることを確認する。

確認対象:

``` text
BotManager.activeSymbol
active_runtime_id
ExecutionEngine.symbol
Market Feed symbol
DOM symbol
Strategy symbol
AI symbol
MM/order-intent symbol
Governance symbol
Execution symbol
Frontend activeSymbol
```

第二のactive symbol authorityが作られていないこと。

requestedSymbol、Top Candidate、Replay
SymbolなどがactiveSymbolへ誤昇格していないこと。

------------------------------------------------------------------------

# 5. AUTO MARKET SELECTION

AMSについて以下を確認する。

``` text
Universe
→ Scanner
→ Capital Eligibility
→ Ranking
→ Top Candidate
→ Selection Proposal
→ SafeSwitch
→ Active Symbol
```

確認項目:

-   Universeが正常取得される
-   Scannerが正常評価する
-   MM eligibilityが正しくgateする
-   Ranking scoreが正しく生成される
-   Top CandidateとActive Symbolが別概念として維持される
-   switch不可条件でswitchしない
-   active symbol CASが維持される
-   stale candidateを使用しない
-   old runtime contextを使用しない

AMSがStrategyのBUY/SELLを決定していないことも確認する。

------------------------------------------------------------------------

# 6. DOM / Order Book 最重要監査

現在、実画面で板情報が表示されていない事象が確認されている。

これを最優先Finding候補として扱う。

以下の経路を順番に追跡する。

``` text
activeSymbol
↓
Exchange Symbol Normalization
↓
KuCoin Market WebSocket
↓
Subscription
↓
Order Book Snapshot
↓
Sequence Synchronization
↓
OrderBook Runtime
↓
Market Intelligence State
↓
Frontend State
↓
DOM Component
```

各境界で、

``` text
symbol
runtimeId
timestamp
sequence
bid
ask
snapshot freshness
```

を確認する。

------------------------------------------------------------------------

# 7. DOM非表示の原因分類

板が表示されない場合、推測で修正せず、まず以下のどこで停止しているか特定する。

A. WebSocket未接続

B. subscribe失敗

C. symbol normalization不一致

D. snapshot取得失敗

E. sequence validation失敗

F. runtime ID guardによるreject

G. backend orderbook state未更新

H. API/WS frontend bridge不成立

I. Frontend state更新失敗

J. DOM component rendering問題

K. Bot STOPPED / Loop OFFによる仕様上の非表示

L. AMS変更によるregression

原因を最低でも、

``` text
Backend Feed
Backend Runtime
API/Transport
Frontend State
Frontend Rendering
Expected Runtime State
```

のどこに属するか確定する。

------------------------------------------------------------------------

# 8. DOMデータ品質

板が表示された場合も以下を確認する。

-   bestBid \< bestAsk
-   bids / asksが空でない
-   sequenceが後退しない
-   crossed bookが表示されない
-   stale snapshotを表示しない
-   activeSymbolとDOM symbolが一致
-   old symbolの板が混入しない
-   switch後に新symbolの板へ切り替わる
-   同一symbol時に不要なruntime churnが起きない

------------------------------------------------------------------------

# 9. DOM + Entry Marker

TradingAI UIでは左側DOMは重要な運用監視UIである。

将来的な実取引/ペーパー取引のentry markerとの整合も確認する。

最低限、

``` text
Entry Symbol
Entry Price
DOM Symbol
DOM Price Scale
Runtime ID
```

の整合性を監査する。

markerが旧symbolのDOM上へ残留しないこと。

今回marker機能が未接続の場合は、勝手に実装せずFindingとして報告する。

------------------------------------------------------------------------

# 10. Recent Trades

Recent Tradesのactive runtime feedが存在する場合、

-   activeSymbol一致
-   timestamp正常
-   old symbol混入なし
-   switch後切替
-   stale表示なし

を確認する。

active runtimeがまだ存在しない場合は、

``` text
NOT IMPLEMENTED / NOT APPLICABLE
```

を明確に分類する。

DOM障害と混同しない。

------------------------------------------------------------------------

# 11. Market Intelligence

以下を確認する。

``` text
DOM
↓
Microstructure Detectors
↓
Feature Builder
↓
Strategy
```

Detector例:

-   Iceberg
-   Spoofing
-   Absorption
-   Fake Pressure
-   Buy/Sell Pressure
-   Momentum
-   Liquidity
-   Spread
-   Volatility

各結果がactiveSymbol/runtimeIdと一致すること。

旧runtime detector stateがswitch後に再利用されないこと。

------------------------------------------------------------------------

# 12. Feature Builder

確認:

-   detector outputとsymbol一致
-   runtime ID一致
-   stale input拒否
-   switch時history/current feature state reset
-   nullを0へ捏造しない
-   missing dataを安全側に扱う

------------------------------------------------------------------------

# 13. Strategy

Strategyは、

``` text
BUY
SELL
HOLD
```

候補を生成する第一判断層として維持されていること。

AMSがStrategy方向を注入していないこと。

確認:

``` text
Strategy.symbol == activeSymbol
Strategy.runtimeId == active_runtime_id
```

旧symbol / 旧runtimeのStrategy decisionはExecutionへ到達させない。

------------------------------------------------------------------------

# 14. AI Decision

AIはPython Strategy / Featureをレビューする層として確認する。

AIが独自にmarket selection authorityになっていないこと。

確認:

``` text
AI.symbol
AI.runtimeId
Strategy correlation
evaluatedAt
```

旧AI decisionをswitch後に使用しない。

Strategy
HOLDを不正にBUY/SELLへ昇格する経路がないことも既存設計に従って確認する。

------------------------------------------------------------------------

# 15. Money Management

以下のauthority chainを確認する。

``` text
Account Authority
→ Money Management
→ Capital Eligibility
→ Position Sizing / Risk
→ Order Intent Context
```

確認:

-   equity
-   available capital
-   exposure
-   remaining exposure
-   risk budget
-   position capacity
-   MM mode/regime
-   authorityFresh
-   executionEntryAllowed

AMS側でMM計算を複製していないこと。

Live/Paper authorityを混同しないこと。

------------------------------------------------------------------------

# 16. Governance

Governanceが最終安全authorityとして維持されていること。

確認:

``` text
MM ALLOW + Governance BLOCK
→ BLOCK
```

AMS、Strategy、AIがGovernanceをoverrideできないこと。

symbol/runtime mismatch時はfail closed。

------------------------------------------------------------------------

# 17. Emergency

EmergencyがAMSより上位の安全authorityとして維持されていること。

確認:

``` text
Emergency unsafe
Emergency unknown
Emergency ACTION_REQUIRED
```

では、

-   new selection
-   symbol switch
-   new entry

が許可されないこと。

既存Emergency Stop機能のregressionも確認する。

------------------------------------------------------------------------

# 18. Execution

Execution直前に最低限、

``` text
activeSymbol
runtimeId
Strategy context
AI context
MM/order intent
Governance decision
ExecutionEngine.symbol
```

が一致していること。

不一致時:

``` text
NO ORDER
FAIL CLOSED
```

Paper監査ではreal exchange orderが0件であること。

------------------------------------------------------------------------

# 19. Old Context Invalidation

symbol switchをsimulation/Paperで再現できる場合、

旧symbol / runtimeの以下を検証する。

-   WS callback
-   DOM
-   Detector
-   Feature
-   Strategy
-   AI
-   MM intent
-   Governance result
-   Execution request

新runtimeへ混入しないこと。

旧callback rejection guardが正常に機能すること。

------------------------------------------------------------------------

# 20. Frontend Active Symbol

Frontendでは、

``` text
backend activeSymbol
```

をLIVE runtime authorityとする。

以下は別概念として維持する。

``` text
requestedSymbol
Top Candidate
Replay Symbol
```

UI表示だけを見てauthorityを推測せず、backend responseと比較する。

------------------------------------------------------------------------

# 21. Dashboard AUTO MARKET SELECTION

以下を確認する。

-   Active
-   Top Candidate
-   Cycle
-   Switch
-   Scanner status
-   Ranking status
-   Live AUTO state
-   blockReasons
-   configurationVersion
-   approval state（存在する場合）

ActiveとTop Candidateが同一fieldとして扱われていないこと。

------------------------------------------------------------------------

# 22. WAITING / UNAVAILABLE / BLOCKED

Dashboardに、

``` text
WAITING
UNAVAILABLE
BLOCKED
UNKNOWN
```

が表示される場合、その表示が本当にauthority/runtime状態と一致するか確認する。

単にデータ接続が壊れている状態を「UNAVAILABLEだから正常」と判定しない。

各表示について根拠となるbackend fieldを特定する。

------------------------------------------------------------------------

# 23. Frontend Console

実ブラウザ確認時に、

-   JavaScript error
-   React error
-   unhandled promise rejection
-   WebSocket error
-   API error
-   repeated reconnect
-   render loop

を確認する。

重大errorがある場合はFindingへ記録。

------------------------------------------------------------------------

# 24. Backend Logs

以下を確認する。

-   traceback
-   repeated reconnect
-   WS subscription error
-   sequence mismatch
-   stale snapshot
-   symbol mismatch
-   runtime ID mismatch
-   unhandled exception
-   repeated failed retry
-   resource leak兆候

------------------------------------------------------------------------

# 25. API / Transport

Market IntelligenceおよびDashboardが利用するAPI/WSについて、

-   HTTP status
-   response schema
-   symbol
-   runtime ID
-   timestamp
-   freshness
-   null semantics

を確認する。

Backendが正常でFrontendだけ壊れている場合を明確に区別する。

------------------------------------------------------------------------

# 26. Paper統合確認

Live AUTOへ進む前にPaper状態で可能な限り実runtimeを確認する。

最低限、

``` text
Paper
dryRun = true
realOrderAllowed = false
```

を維持する。

可能なら、

``` text
Bot start
Market Feed
DOM
Market Intelligence
Strategy
AI
MM
Governance
Paper Execution
```

を一連で確認する。

------------------------------------------------------------------------

# 27. Symbol Switch Paper Validation

安全に可能ならPaperで、

``` text
Symbol A
↓
SafeSwitch
↓
Symbol B
```

を再現する。

確認:

-   activeSymbol B
-   runtimeId更新
-   DOM B
-   Detector B
-   Strategy B
-   AI B
-   Execution context B
-   old A callback reject
-   old A DOM非表示
-   old A decision非使用

------------------------------------------------------------------------

# 28. UI Visual Audit

実ブラウザで最低限以下を確認する。

-   DOMが表示される
-   レイアウト崩れなし
-   Active Symbolが正しい
-   Top Candidateが正しい
-   status表示がbackendと一致
-   card重複なし
-   stale data混在なし
-   loadingが永久継続しない
-   error表示が隠蔽されない

1280 / 1440 / 1920px程度の主要幅も可能なら確認する。

------------------------------------------------------------------------

# 29. Performance / Resource

長時間監査が可能なら、

-   WebSocket数
-   temporary feed
-   callback accumulation
-   memory増加
-   reconnect loop
-   runtime object accumulation

を確認する。

symbol switchを繰り返してsubscription/resourceが増殖しないこと。

------------------------------------------------------------------------

# 30. AMS Anti-Flapping

AMS-6C v1:

``` text
selectionObservationInterval = 10 sec
minimumScoreAdvantage = 0.42
requiredConsecutiveWins = 5
minimumActiveDuration = 60 sec
switchCooldown = 120 sec
automaticSafetyRecoverySwitch = false
maxExecutablePositions = 1
```

がruntime contractと一致すること。

別のmagic numberが存在しないか確認する。

------------------------------------------------------------------------

# 31. Restart Safety

service/process restart後、

``` text
Live AUTO = OFF
approval = cleared
one-shot permission = cleared
candidate persistence = cleared
```

であること。

restartによってLive AUTOが自動復旧しないこと。

------------------------------------------------------------------------

# 32. Security / Credentials

以下を確認する。

-   API KEYをログ出力しない
-   SECRETをログ出力しない
-   PASSPHRASEをログ出力しない
-   Frontendへ送らない
-   error messageへ含めない
-   test artifactへ保存しない

値そのものを監査報告へ記載しない。

------------------------------------------------------------------------

# 33. Recorder / Replay 境界

Recorder / Replayは別担当領域として扱う。

今回の統合監査で勝手に修正・再設計しない。

TradingAI側との境界で重大な問題を発見した場合のみFindingとして記録する。

Recorder/Replay実装へ逸脱しない。

------------------------------------------------------------------------

# 34. Regression Test

現在存在する主要AMS testを確認する。

少なくとも関連する以下を対象候補とする。

``` text
AMS-0D
AMS-1A
AMS-1B
AMS-1C
AMS-1D
AMS-2A
AMS-2B
AMS-2C
AMS-2D
AMS-4A
AMS-4B
AMS-4C
AMS-5A
AMS-5B
AMS-6B
AMS-6C
AMS-6D
AMS-7A
AMS-7B
完成時点までの後続AMS
```

加えて、

``` text
Money Management
Exchange live status
Orderbook
Market Intelligence
Strategy
AI runtime
Governance
Execution
Emergency
Frontend Market Intelligence
Dashboard
```

の関連回帰を実行する。

全repository
testを無条件に実行して環境依存問題へ逸脱するのではなく、まず関連suiteを確実に通す。

------------------------------------------------------------------------

# 35. Build / Static Check

必要に応じて、

``` text
Python compile
git diff --check
Frontend tests
Frontend build
Lint
```

を実行する。

build artifactによる不要差分を作らないよう既存運用ルールに従う。

------------------------------------------------------------------------

# 36. Finding Severity

Findingは以下に分類する。

## CRITICAL

-   実注文安全性違反
-   wrong-symbol execution
-   Governance/Emergency bypass
-   credential leakage
-   uncontrolled Live switch

## HIGH

-   DOM/feed完全切断
-   active symbol authority split
-   old decision execution
-   symbol/runtime mismatch
-   MM authority誤使用
-   SafeSwitch safety violation

## MEDIUM

-   UI status不整合
-   Recent Trades欠落
-   non-critical stale display
-   reconnect/resource問題
-   calibration/runtime表示不整合

## LOW

-   warning
-   deprecation
-   cosmetic UI issue
-   non-critical diagnostics

------------------------------------------------------------------------

# 37. 修正方針

監査中に問題を発見しても、原則として即座に大規模修正しない。

まず、

``` text
Finding
Root Cause
Affected Path
Severity
Recommended Fix
```

を確定する。

ただし、監査継続不能な軽微かつ局所的問題のみ、明確に記録した上で最小修正を許容する。

安全機構の変更は別工程とする。

------------------------------------------------------------------------

# 38. 完成判定

以下が成立した場合に統合監査PASS候補とする。

-   activeSymbol authority一意
-   Market Feed正常
-   DOM正常表示
-   symbol/runtime consistency成立
-   old context rejection成立
-   Market Intelligence正常
-   Strategy/AI正常
-   MM authority正常
-   Governance precedence正常
-   Emergency precedence正常
-   Paper Execution正常
-   real order 0
-   Dashboard状態整合
-   Frontend重大errorなし
-   HIGH/CRITICAL Findingなし
-   関連regression PASS

MEDIUM/LOWのみ残る場合は、

``` text
PASS WITH FINDINGS
```

とする。

CRITICAL/HIGHが1件でも残る場合は、

``` text
FAIL
```

とする。

------------------------------------------------------------------------

# 39. Live移行判定

この監査PASSだけでReal Orderを有効化してはならない。

監査結果として別途、

``` text
Controlled Live Symbol Switch Readiness
Live AUTO Readiness
Real Order Readiness
```

をそれぞれ独立判定する。

Real Order permissionは別工程とする。

------------------------------------------------------------------------

# 40. 最終報告形式

以下の順で報告すること。

1.  Git State
2.  Audit Scope
3.  System Architecture Result
4.  Active Symbol Authority
5.  AMS
6.  Market Feed / WebSocket
7.  DOM / Order Book
8.  DOM Non-Display Root Cause
9.  Recent Trades
10. Market Intelligence
11. Feature Builder
12. Strategy
13. AI
14. Money Management
15. Governance
16. Emergency
17. Execution
18. Old Context Invalidation
19. Frontend / Dashboard
20. API / Transport
21. Browser Console
22. Backend Logs
23. Paper Integration
24. Symbol Switch Validation
25. Performance / Resource
26. Restart Safety
27. Security
28. Regression Tests
29. Findings
30. Fix Recommendations
31. Overall Audit Verdict
32. Controlled Live Symbol Switch Readiness
33. Live AUTO Readiness
34. Real Order Readiness

------------------------------------------------------------------------

# 41. 最終注意

本監査の目的は、

「各工程のtestがPASSした」

ことを確認するだけではない。

最終的に、

``` text
Market
→ Active Symbol
→ DOM
→ Intelligence
→ Strategy
→ AI
→ Money Management
→ Governance
→ Execution
→ Dashboard
```

が同じsymbol / runtime / authority
chainで一貫して動作していることを証明することである。

特に現在確認されている

「板情報（DOM）が表示されていない」

問題については、完成後監査で必ず原因を特定し、

EXPECTED STATE

なのか、

REGRESSION / BUG

なのかを明確に判定すること。

原因不明のままActual Live AUTOまたはReal Order工程へ進んではならない。
