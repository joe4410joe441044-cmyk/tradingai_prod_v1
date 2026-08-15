# Parameter問題

## 1. 目的

TradingAI / Micro
Edge戦略における「Parameter問題」を、今後の設計・運用上の重要課題として整理する。

本システムの最終目的は、単に安全に動作することではなく、**実際にトレードを成立させ、リスクを管理しながら利益を追求すること**である。

開発段階では安全性・決定論・fail-closedを重視して固定Parameterを設定してきた。しかしProductionに近い自然市場で検証を開始した結果、Parameterが厳しすぎることで、システムが正常でもトレードや市場切替がほとんど発生しない可能性が明確になった。

今後は、安全性、取引機会、期待利益、過剰フィルタリング、過剰最適化、市場レジームへの適応、Python
/ AI / 人間の役割分担を一体として考える。

## 2. 今回実際に発生した問題

Auto Market Selectionでは、候補市場と現在市場のScore Advantageについて
`minimumScoreAdvantage = 0.42` を採用していた。

Production観測では、AMS-7E-R2で約0.29～0.418、AMS-7E-R3-R1で0～約0.166、追加100サンプルで0～約0.217となり、0.42では自然市場で切替条件がほとんど成立しなかった。

一方、過去のBTCUSDT観測では約0.416～0.426の領域も確認されている。つまり0.42が数学的に不可能なのではなく、**市場・active
symbol・market regimeによってParameterの実効性が大きく変わる**。

Calibrationでは `0.20`
が推奨された。今回100サンプルのほぼp95付近であり、5 consecutive
wins、60秒minimum active
duration、120秒cooldownとの組合せでは、約10.8分の観測で仮想switch
1回、oscillation 0だった。ただし0.20が永久的な正解という意味ではない。

## 3. Parameter問題とは何か

Parameter問題とは、TradingAIの判断を構成する多数の閾値・期間・重み・制限値について、**何を固定し、何を市場に応じて変化させ、誰がその値を決定するのか**という問題である。

Parameterが緩すぎれば、ノイズをEdgeと誤認し、過剰売買、手数料・Slippage増加、Drawdown増加につながる可能性がある。

反対に厳しすぎれば、HOLDばかりになり、市場切替やEntryが成立せず、Micro
Edgeを取り逃がし、「安全だが利益を生まないBot」になる可能性がある。

## 4. Parameter増加の危険

開発を進めると異常状態や例外を防ぐために条件を追加したくなる。しかし
`条件A AND 条件B AND 条件C...`
と増やすほど、すべてを同時に満たす確率は低下する。

各Parameter単体では合理的でも、システム全体では
**Over-filtering（過剰フィルタリング）** が発生し得る。

Micro
Edgeは巨大な一回の優位性を待つ戦略ではなく、小さな統計的優位性を多数回積み上げる思想を持つため、取引機会を過度に減らすParameter設計は戦略そのものと衝突する可能性がある。

## 5. Overfittingとの関係

Parameterを過去データに合わせすぎると、Backtestでは優秀でもLiveでは機能しない可能性がある。これはParameter
Overfittingの問題である。

threshold、confidence、volatility filter、spread limit、liquidity
requirement、cooldown、consecutive wins、stop loss、take
profit、position
sizingなどを過去データへ細かく合わせ続ければ、過去相場専用Botになる危険がある。

Parameter最適化の目的は、**過去利益の最大化ではなく、未知の市場でも再現可能なEdgeを維持すること**でなければならない。

## 6. Parameterは何個あるのか

Micro Edgeシステム全体ではParameterは単一thresholdだけではない。Market
Microstructure、Scanner / Ranking、Strategy、AI Decision、Market
Selection、Execution、Money Management、Governance / Safety、Timing /
Freshnessなどに存在する。

完成時に数十個規模でも不自然ではない。ただし重要なのは総数ではなく、**実際に利益・取引頻度・リスクへ大きく影響する主要Parameterを特定すること**である。

## 7. Parameterの3分類

### A. Safety Parameter

原則として自動最適化しない。Emergency条件、realOrderAllowed、最大損失、最大Drawdown、最大Exposure、Position上限、API
freshness、authority
consistencyなど。利益Parameterではなく破綻防止Parameterである。

### B. Strategy Parameter

Calibration対象。Score Advantage、Confidence threshold、Microstructure
threshold、Momentum、Spread、Liquidity、consecutive wins、active
duration、cooldownなど。市場状態で最適値が変化する可能性が高い。

### C. Money Management Parameter

資産状態とStrategy Edgeに応じて調整する。Risk per Trade、Position
Size、Exposure、Kelly fraction、Drawdown時の縮小率など。Strategy
Parameterとは別Authorityとして扱う。

## 8. 人間・Python・AIの役割

### 人間

最大許容損失、最大Drawdown、Risk上限、自動化範囲、Parameter変更許容範囲、運用停止判断などの**政策・境界条件**を決定する。Live中に数十個を継続手動調整する設計にはしない。

### Python

市場データ収集、Distribution、Backtest、Walk-forward
validation、Parameter sensitivity、Trade frequency、Expected
Value、Drawdown、Slippage/fee影響など、決定論的・統計的処理を担当する。

### AI

Parameterを無制限に自由生成する役割にはしない。市場レジーム解釈、変更候補評価、複数指標の矛盾評価、異常Calibration検出、Pythonが提示した候補からの選択・抑制などを担当する。

基本思想は、**Pythonが測定し、AIが文脈を評価し、人間が許容範囲を決める**。

## 9. Bot Start後の理想像

通常運用では、ユーザーがBot
Startを行った後に毎回Parameterを手動調整することを前提にしない。

Human Policy → Python Measurement / Calibration → AI Regime Assessment →
Approved Parameter Range → Strategy → Money Management → Governance →
Execution

という構造を目指す。

人間は「トレードするたびにParameterを決める人」ではなく、**自動運転システムが動ける範囲を決める人**になる。

## 10. Parameterを増やす基準

新Parameter追加時は最低限、何を解決するか、既存Parameterでは解決不能か、Entry/Switch頻度への影響、Expected
Valueへの影響、Drawdownへの影響、Live観測可能性、他Parameterとの相関を確認する。

効果を説明できないParameterは増やさない。

## 11. 今後必要なParameter管理

Parameterをコード中の固定値として散在させ続けず、将来的にParameter
Registryのような一元管理を検討する。

Parameter Name、Category、Current Value、Default
Value、Minimum、Maximum、Authority、Fixed / Adaptive、Last
Calibration、Calibration Source、Confidence、Production
Resultを追跡し、「なぜこの値なのか」を説明可能にする。

## 12. 利益を評価軸から外さない

Parameter評価ではSafetyだけを評価しない。Net Profit、Expected
Value、Profit Factor、Win Rate、Average Win / Loss、Drawdown、Trade
Frequency、Fee / Slippage、Capital Efficiencyなどを組み合わせる。

重要なのは、**最も安全なParameterではなく、許容Riskの範囲内で最も優れたRisk-adjusted
returnを生むParameter**を探すことである。

## 13. 現時点の方針

Score Advantageは Current Production `0.42`、Calibration Recommendation
`0.20`。

0.20は有力候補だが単一短期観測だけで永久固定しない。Limited Live / Paper
/ Read-only Calibrationを利用し、symbol別、volatility
regime別、liquidity regime別、時間帯別、market
condition別に有効性を評価する。

## 14. 今後の設計原則

-   Parameterは多ければ良いわけではない。
-   Safety ParameterとProfit Parameterを混同しない。
-   Safetyを維持しながら取引機会を殺さない。
-   固定値を「正解」とみなさずProduction観測で検証する。
-   Pythonは測定、AIは評価、人間は境界と目的を決める。
-   Parameter変更そのものではなく利益・Risk・取引頻度への影響を評価する。
-   Micro Edgeでは、小さなEdgeを取る機会を過剰なGateで消さない。

## 15. 最終目標

最終目標はParameterをゼロにすることでも、すべてをAIに任せることでもない。

**人間が利益目標とRisk許容範囲を定義し、PythonとAIがその範囲内で市場に適応しながらParameterを運用し、Bot
Start後は原則として自動でMicro
Edgeを探索・判断・取引できる状態**を目指す。

この「Parameter問題」は、TradingAI完成後も継続的に管理すべき運用・研究テーマとして扱う。
