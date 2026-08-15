# AI Advisor Role and Migration Specification

## 1. 文書の目的

本仕様書は、TradingAIにおける **AI
Advisorの正式な役割、権限、参照情報、Trading
AIとの分離、および現在ChatGPTと行っている開発・運用相談を将来的にAI
Advisorへ段階的に移行するための基本方針** を定義する。

中心原則：

> **Trading AIは「取引するためのAI」、AI
> Advisorは「TradingAIシステム全体を理解し、分析し、改善を助言するためのAI」である。**

------------------------------------------------------------------------

## 2. TradingAIに存在する2種類のAI

### 2.1 Trading AI --- 本線トレード判断AI

Trading AIは実際の売買パイプラインに属する。

``` text
Market Data
    ↓
Python Detectors
    ↓
Feature Builder
    ↓
Python Strategy
    ↓
Trading AI
    ↓
Money Management
    ↓
Governance
    ↓
Execution
```

主目的は、Python Strategyが生成したBUY /
SELL候補をレビューし、APPROVEまたはHOLDを判断すること。

原則としてPython StrategyがHOLDした候補をTrading AIが独自にBUY /
SELLへ昇格させない。

リアルタイム性、再現性、安全性、明確な入力authority、fail-closed設計を重視する。

### 2.2 AI Advisor --- システム監督・分析・改善助言AI

AI Advisorは売買本線のGateではない。

TradingAI全体を観測し、Trace、取引結果、Parameter、P&L、Runtime状態、Strategy、Trading
AI、Money
Management、Governance等を分析して、人間Operatorへ改善案を提示する。

``` text
                   AI Advisor
                       ↑
        ┌──────────────┼──────────────┐
        │              │              │
    E2E Trace      Parameters       P&L
    Strategy       MM/Governance   History
    Trading AI       Runtime       Replay
        └──────────────┼──────────────┘
                       ↑
                    TradingAI
```

AI
Advisorは原則として注文を発行しない。初期段階ではParameterやStrategyを自動変更しない。

------------------------------------------------------------------------

## 3. Trading AIとAI Advisorの責任分離

  項目               Trading AI             AI Advisor
  ------------------ ---------------------- ----------------------------
  主目的             リアルタイム取引判断   システム全体の分析・改善
  売買本線           入る                   入らない
  BUY / SELL承認     行う                   原則行わない
  注文への直接影響   あり                   なし
  動作速度           リアルタイム           非同期でも可
  E2E Trace          記録される判断主体     Traceを分析する側
  Parameter          使用する               評価・変更提案する
  P&L                判断結果として発生     長期的に分析する
  人間との関係       自動実行系             Advisor / Analyst
  初期権限           本線契約内             READ / ANALYZE / RECOMMEND

この責任境界を崩さない。

------------------------------------------------------------------------

## 4. AI Advisorの主要責務

### 4.1 システム状態分析

-   Strategy状態
-   Trading AI状態
-   Money Management状態
-   Governance状態
-   Execution状態
-   Runtime状態
-   Market Data freshness
-   異常・停止・block reason

### 4.2 E2E Trace分析

Decision単位のtraceIdを使用して以下を追跡する。

``` text
Market
↓
Strategy
↓
Trading AI
↓
Money Management
↓
Governance
↓
Execution
↓
Position
↓
Result / P&L
```

どの層で取引が停止したか、どの理由が多いか、どの条件が利益・損失へつながったかを分析する。

### 4.3 Parameter分析

現在値、過去値、変更日時、version、symbol、market regime、pass
rate、trade frequency、P&L、drawdown等を比較する。

### 4.4 P&L / Trade History分析

勝率、Profit Factor、Expectancy、Drawdown、Symbol別成績、Market
regime別成績、時間帯別成績、Strategy version別成績、Parameter
set別成績、Trading AI判断別成績、MM設定別成績などを扱う。

### 4.5 改善提案

「何を変えるか」だけでなく、「なぜ変えるべきか」「根拠は何か」「変更リスクは何か」を人間へ説明する。

------------------------------------------------------------------------

## 5. AI Advisorが行わないこと

初期設計では以下を許可しない。

-   Real Order発行
-   Positionの直接操作
-   Fund movement
-   Governance bypass
-   Money Management bypass
-   Trading AI bypass
-   Parameterの無承認変更
-   Strategyの無承認変更
-   Live設定の無承認変更
-   Safety thresholdの無承認緩和

AdvisorはExecution authorityではない。

------------------------------------------------------------------------

## 6. 初期権限モデル

``` text
READ
 ↓
ANALYZE
 ↓
RECOMMEND
 ↓
Human Approval
 ↓
Change Workflow
```

AI
Advisorが改善を提案し、人間が根拠を確認して承認した後、正式な変更工程へ進む。

------------------------------------------------------------------------

## 7. 将来的な権限拡張

-   LEVEL 0 --- READ ONLY
-   LEVEL 1 --- RECOMMEND
-   LEVEL 2 --- PREPARE：変更案・simulation・calibration
    candidateを生成するが適用しない
-   LEVEL 3 --- APPLY WITH APPROVAL：人間の明示承認後のみ適用
-   LEVEL 4 --- AUTO WITH LIMITS：事前定義された安全範囲内のみ自動調整

LEVEL 4は長期的選択肢であり、初期目標ではない。

------------------------------------------------------------------------

## 8. AI Advisorが理解すべき3種類の情報

### A. Design Knowledge

Trading philosophy、Micro Edge思想、Architecture、Trading AI、Money
Management、Governance、Parameter設計、安全方針、人間authority。

### B. Current State

Current Strategy version、Parameter set、Trading AI
version、Runtime、Active symbol、Market regime、MM、Governance、System
health。

### C. Historical Evidence

E2E Trace、Trade history、P&L、Parameter history、Strategy version
history、AI decision history、Replay、Error / Block history、Calibration
history。

AI Advisorはこの3つを組み合わせて助言する。

------------------------------------------------------------------------

## 9. 正式ドキュメントへの移行

現在ChatGPTとの会話に存在する設計知識をrepository内の正式仕様へ移す。

候補：

``` text
docs/
├── SYSTEM_ARCHITECTURE.md
├── TRADING_PHILOSOPHY.md
├── TRADING_AI_SPEC.md
├── AI_ADVISOR_SPEC.md
├── PARAMETER_ARCHITECTURE.md
├── MONEY_MANAGEMENT_SPEC.md
├── E2E_TRACE_SPEC.md
├── OPERATING_POLICY.md
└── CHANGE_HISTORY.md
```

会話memoryをauthoritative specificationとせず、version-controlled
Markdownを正本とする。

------------------------------------------------------------------------

## 10. E2E Traceとの連携

AI Advisorの主要情報源の一つをE2E Traceとする。

Decision数、Strategy ALLOW、Trading AI APPROVE、MM ALLOW、Governance
ALLOW、Executed、Suppressed、Blocked、Incomplete、Failed等を集計し、さらにstop
reason、Parameter、Market regime、Symbol、P&Lと相関させる。

------------------------------------------------------------------------

## 11. Parameter Historyとの連携

Parameter変更はversion化して記録する。

最低限：

``` text
parameterSetId
version
timestamp
changedBy
approvalSource
parameterName
oldValue
newValue
unit
reason
calibrationEvidence
applicableMode
applicableSymbol
```

結果側にはdecisionCount、tradeCount、winRate、netPnL、drawdown、profitFactor、expectancy等を関連付けられる構造を目標とする。

------------------------------------------------------------------------

## 12. 「変更 → 結果」を追跡可能にする

AI Advisorは、

``` text
何を変更したか
↓
市場条件はどうだったか
↓
Decisionがどう変わったか
↓
Trade数がどう変わったか
↓
利益・損失がどう変わったか
↓
Riskがどう変わったか
```

を追跡できることを目標とする。

単なる会話記憶ではなく、実際のsystem evidenceから改善を評価する。

------------------------------------------------------------------------

## 13. Replayとの連携

Replayは補助的分析sourceとする。

用途：

-   特定Tradeの再分析
-   Failure / Block再現
-   Parameter変更前後比較
-   Strategy version比較
-   Market regime比較

Live / Paper / Replayを明確に区別し、Replay結果を実績と混同しない。

------------------------------------------------------------------------

## 14. AI Advisor UI

単なるChat画面だけではなく、将来的に以下を統合する。

-   Current Assessment
-   Findings
-   Recommendations
-   Evidence
-   Ask Advisor

質問例：

-   最近なぜ取引が少ない？
-   昨日の損失原因は？
-   今のParameterは適切？
-   Trading AIがHOLDしすぎていない？
-   MMを変更する必要はある？
-   今一番直すべき場所は？
-   前回のParameter変更は成功だった？

------------------------------------------------------------------------

## 15. ChatGPTからAI Advisorへの移行

現在の外部ChatGPTは、Architecture相談、開発工程整理、Codex/OpenCode指示作成、Parameter問題整理、Paper/E2E
Trace解析、改善方針、UI構成、安全性と利益追求のバランス整理等を担っている。

完成後は、このうち日常的な運用・分析相談をAI Advisorへ段階的に移す。

------------------------------------------------------------------------

## 16. 移行後の役割分担

### AI Advisor

日常運用担当：

-   TradingAI状態
-   Trade/P&L分析
-   Parameter分析
-   Block原因分析
-   改善提案
-   Replay分析
-   System health分析

### 外部ChatGPT

外部Architect / Second Opinion：

-   大規模Architecture変更
-   新module設計
-   AI Advisor自体の改善
-   Advisor判断の外部監査
-   新Strategy思想
-   大規模Safety設計
-   重大障害のSecond Opinion

------------------------------------------------------------------------

## 17. 段階的Migration Plan

### Phase 1 --- Build

外部ChatGPT中心でTradingAIを完成させる。

### Phase 2 --- Data Foundation

E2E Trace、Parameter history、Trade history、P&L、Runtime
state、Strategy/Trading AI version、Replayを安定させる。

### Phase 3 --- Advisor Read-Only Integration

AI Advisorが上記情報をREADできるようにする。変更権限は与えない。

### Phase 4 --- Parallel Evaluation

同じPaper/Live結果について外部ChatGPT分析とAI Advisor分析を比較する。

### Phase 5 --- Daily Advisor Migration

品質確認後、日常相談をAI Advisorへ移す。

### Phase 6 --- External Oversight

外部ChatGPTは必要時の設計・監査・Second Opinionへ移行する。

------------------------------------------------------------------------

## 18. Parallel Evaluation

AI Advisor完成直後に全面依存しない。

同じデータをAI Advisorと外部AI/Human
Reviewへ渡し、原因特定精度、Parameter提案品質、P&L解釈、Safety認識、過剰最適化傾向、根拠提示、不明時の扱いを比較する。

------------------------------------------------------------------------

## 19. AI Advisorの「学習」の意味

単純な会話記憶だけを意味しない。

重要なのは、

``` text
Specification
+
Historical Data
+
Parameter Versions
+
E2E Trace
+
Trade Results
+
P&L
+
Market Regime
+
Human Decisions
```

を参照し、過去と現在を比較できることである。

将来的にML、RAG、long-term memory等を追加する場合も、authoritative data
foundationを優先する。

------------------------------------------------------------------------

## 20. Human Authority

最終的な運用責任は人間Operatorに残す。

初期段階ではParameter、Strategy、Live、Risk、Money Management、Trading
AI、Governance等の変更についてAI Advisorは提案までとする。

------------------------------------------------------------------------

## 21. 利益追求との関係

AI Advisorの目的は単にシステムを安全にすることではない。

TradingAIは取引システムであり、最終目的には利益追求がある。

AdvisorはTrade opportunity、Expected
Value、Profit、Compounding、Drawdown、Ruin risk、Execution
quality、Opportunity lossを総合評価する。

「取引しなければ安全」という方向へ過剰最適化せず、同時に利益だけを追ってSafetyを無視しない。

目標：

> **保護された状態で、持続可能なExpected Valueと利益を最大化すること。**

------------------------------------------------------------------------

## 22. AI Advisor成功条件

最低条件候補：

1.  TradingAI Architectureを正しく説明できる
2.  Current Parameterを正しく取得できる
3.  E2E Traceを追跡できる
4.  No Trade理由を正しく説明できる
5.  Trade結果をStrategy/Trading AI/MM/Governanceまで遡れる
6.  P&LをParameter/versionと相関できる
7.  不明な情報を推測で補完しない
8.  改善提案にEvidenceを提示できる
9.  Safety boundaryを理解する
10. 利益追求とRiskを両方評価する
11. 人間承認なしに本線を変更しない
12. 外部レビューとの比較で十分な品質を示す

------------------------------------------------------------------------

## 23. 将来の理想状態

``` text
あなた:
「最近どう？」

AI Advisor:
「直近3日間の取引結果とE2E Traceを分析しました。
 Strategy ALLOW率は正常範囲ですが、
 Trading AI HOLD率が過去基準より上昇しています。

 主因は高Volatility regimeでのMomentum disagreementです。

 現時点ではStrategy変更は推奨しません。
 Trading AI Momentum calibrationをPaperで再評価することを推奨します。

 根拠となるTraceを表示できます。」
```

人間は細かな内部Parameterを毎回監視する必要がなくなる一方、必要ならEvidenceまで掘り下げられる。

------------------------------------------------------------------------

## 24. 最終Architecture原則

``` text
REAL-TIME TRADING LINE

Market
  ↓
Python Detectors
  ↓
Feature Builder
  ↓
Python Strategy
  ↓
Trading AI
  ↓
Money Management
  ↓
Governance
  ↓
Execution
  ↓
Trade / P&L


ADVISORY LINE

Specification
E2E Trace
Parameters
Trading AI Decisions
MM / Governance
Trade History
P&L
Replay
Runtime
  ↓
AI Advisor
  ↓
Analysis
Recommendation
Explanation
  ↓
Human Operator
```

------------------------------------------------------------------------

## 25. 固定方針

1.  Trading AIとAI Advisorは別AIとして扱う。
2.  Trading AIは売買本線に存在する。
3.  AI Advisorは本線の外側からシステム全体を監視する。
4.  AI Advisorを売買成立の必須Gateにしない。
5.  AI Advisorは初期段階ではREAD / ANALYZE / RECOMMENDまで。
6.  E2E Traceを重要な分析根拠とする。
7.  Parameter変更履歴と結果をversion付きで保存する。
8.  会話memoryではなくrepository仕様書とsystem dataを正本とする。
9.  外部ChatGPT相談体制からAI Advisorへ段階的に移行する。
10. 移行期間中はParallel Evaluationを行う。
11. AI Advisor成熟後も外部AIをArchitecture/監査/Second
    Opinionに利用できる。
12. Safetyだけでなく、Riskを管理しながら持続的利益追求を支援する。

------------------------------------------------------------------------

## 26. 現時点での位置付け

TradingAIおよびAI Advisorは開発中であり、本書はAI
Advisorの最終実装完了を意味しない。

今後、

-   Trading AI完成
-   Paper E2E成立
-   E2E Trace安定
-   Parameter history整備
-   Trade/P&L history整備
-   AI Advisor read-only integration
-   Parallel Evaluation

を経て段階的に実装・検証する。

------------------------------------------------------------------------

# Conclusion

TradingAIでは、

**Trading AI = 取引判断**

**AI Advisor = TradingAI全体の監督・分析・改善助言**

として明確に分離する。

AI
Advisorは、現在外部ChatGPTと行っている日常的なTradingAI分析・相談の多くを、将来的にTradingAI内部で担うことを目標とする。

移行は一括ではなく、

**Build → Data Foundation → Read-Only Advisor → Parallel Evaluation →
Daily Advisor Migration**

の順で段階的に行う。

最終的には、AI
AdvisorがTradingAI自身のSpecification、Trace、Parameter、Trade、P&L、Runtimeを直接理解し、人間Operatorへ根拠付きの改善提案を行える状態を目標とする。
