/* =================================================
   PARAMETER GUIDE metadata (static, operator-facing, bilingual).

   This module is a centralized explanation layer only.  It is NOT a second
   parameter authority and does not carry configured/effective/runtime values,
   ranges or writable state.  Runtime values, ranges and scope authority keep
   coming from the canonical schema + API + page state.

   Every statement below is grounded in the current source tree:

   - backend/strategy/parameters/registry.py        (canonical metadata)
   - backend/strategy/parameters/baselines.py       (LIVE migration classes)
   - backend/strategy/parameters/resolver.py        (LIVE runtime authority)
   - backend/strategy/normalized_parameters.py      (PAPER calibration)
   - backend/strategy/MicrostructureEdgeStrategy.py (entry gates / exits)
   - backend/aggregation/MicrostructureStateBuilder.py (features / percentiles)

   Each explanatory field is bilingual: { en, ja }.  DIRECT EFFECT describes
   the code-level threshold/window that changes.  POSSIBLE TRADING EFFECT
   describes plausible downstream behaviour and is deliberately
   non-deterministic: it never claims performance, win rate or profitability.
   Canonical identifiers (minimumCompositeScore, LOW_COMPOSITE_SCORE,
   MAX_HOLD, MOMENTUM_DECAY, ...) are never translated.
================================================= */

export const LIVE_MIGRATION = Object.freeze({
    EXACT: "exact",
    IMPERFECT_UNIT_MAPPING: "imperfect-unit-mapping",
    NO_LEGACY_EQUIVALENT: "no-legacy-equivalent",
});

export const LIVE_MIGRATION_LABELS = Object.freeze({
    [LIVE_MIGRATION.EXACT]: "LIVE exact legacy equivalent",
    [LIVE_MIGRATION.IMPERFECT_UNIT_MAPPING]:
        "LIVE imperfect unit mapping — legacy value is not a canonical percent",
    [LIVE_MIGRATION.NO_LEGACY_EQUIVALENT]:
        "LIVE no active legacy equivalent — observability only",
});

export const LIVE_MIGRATION_LABELS_JA = Object.freeze({
    [LIVE_MIGRATION.EXACT]: "LIVE 旧実装と等価",
    [LIVE_MIGRATION.IMPERFECT_UNIT_MAPPING]:
        "LIVE の単位対応が不完全 — 旧実装値は canonical なパーセントではありません",
    [LIVE_MIGRATION.NO_LEGACY_EQUIVALENT]:
        "LIVE に対応する旧実装が存在しません — 参照専用（observability）",
});

/* LIVE values whose legacy runtime semantic is not proven equivalent to the
   canonical unit.  The UI must not present a canonical suffix for these. */
export const LEGACY_RAW_PARAMETERS = Object.freeze([
    "maximumStrategySpreadPct",
]);

export const LEGACY_RAW_NOTE = Object.freeze({
    en: "This LIVE value is legacy raw and is not a canonical percent. No unit conversion is applied.",
    ja: "この LIVE 値は旧実装の生値であり、canonical なパーセントではありません。単位変換は行いません。",
});

export const RELATED_NOTE = Object.freeze({
    en: "These parameters share a coupling group or the same decision / exit path.",
    ja: "これらのパラメーターは、同じ結合グループ、または同じ判定・決済経路を共有します。",
});

/* Canonical Trading Cycle stage names (bilingual). */
export const CYCLE_STAGES = Object.freeze({
    0: { en: "Parameter Context", ja: "パラメーターコンテキスト" },
    1: { en: "Market Selection", ja: "市場選定" },
    2: { en: "Market Data", ja: "市場データ" },
    3: { en: "Feature Builder", ja: "特徴量ビルダー" },
    4: { en: "Micro Edge Strategy", ja: "マイクロエッジ戦略" },
    5: { en: "AI Decision / Review", ja: "AI 判定・レビュー" },
    6: { en: "Money Management", ja: "資金管理" },
    7: { en: "Governance", ja: "ガバナンス" },
    8: { en: "Execution", ja: "執行" },
    9: { en: "Position", ja: "ポジション" },
    10: { en: "Exit Monitoring", ja: "決済監視" },
    11: { en: "Settlement / Exit Execution", ja: "決済・クローズ執行" },
    12: { en: "Position Closed", ja: "ポジションクローズ" },
    13: { en: "Trade / Parameter Performance Record", ja: "トレード・パラメーター実績記録" },
    14: { en: "Ready for Next Trade", ja: "次トレード準備完了" },
});

const RELATED_LABELS = Object.freeze({
    minimumCompositeScore: "Composite Entry Score（総合エントリースコア）",
    maximumStrategySpreadPct: "Maximum Strategy Spread（最大スプレッド）",
    momentumWindowSeconds: "Momentum Window（モメンタム窓）",
    minimumStrategyConfidence: "Minimum Confidence（最小信頼度）",
    maximumHoldMs: "Maximum Hold（最大保有時間）",
    minimumHoldMs: "Minimum Hold（最小保有時間）",
    exitMomentumMinimum: "Exit Momentum Minimum（決済モメンタム下限）",
    exitLiquidityQualityMinimum:
        "Exit Liquidity Quality Minimum（決済流動性品質下限）",
    exitSpreadQualityMinimum:
        "Exit Spread Quality Minimum（決済スプレッド品質下限）",
    momentumMinimumWarmupSeconds: "Momentum Warmup（モメンタム暖機）",
    absorptionVolumePercentile:
        "Absorption Volume Percentile（吸収出来高パーセンタイル）",
    liquidityQualityPercentile:
        "Liquidity Quality Percentile（流動性品質パーセンタイル）",
});

export const PARAMETER_GUIDE = Object.freeze({
    minimumCompositeScore: {
        labelEn: "Composite Entry Score",
        labelJa: "総合エントリースコア",
        controls: {
            en: "The minimum composite decision score the Micro Edge Strategy requires before an entry can be allowed.",
            ja: "Micro Edge Strategy がエントリーを許可する前に要求する、総合判定スコア（composite decision score）の最低値です。",
        },
        valueMeaning: {
            en: "A normalized score from 0.0 to 1.0. The strategy computes edgeScore as a weighted blend of pressure imbalance (0.35), momentum (0.30), spread quality (0.15) and liquidity quality (0.20).",
            ja: "0.0〜1.0 の正規化スコアです。戦略は pressure imbalance（0.35）、momentum（0.30）、spread quality（0.15）、liquidity quality（0.20）の重み付き合成として edgeScore を計算します。",
        },
        increase: {
            en: "The compositeDecisionScore gate becomes stricter: edgeScore must be higher for the entry gate to pass.",
            ja: "compositeDecisionScore ゲートが厳しくなります。エントリー条件を通過するには、より高い edgeScore が必要になります。",
        },
        decrease: {
            en: "The compositeDecisionScore gate becomes looser: a lower edgeScore can pass.",
            ja: "compositeDecisionScore ゲートが緩くなります。より低い edgeScore でも通過できるようになります。",
        },
        directEffect: {
            en: "In the normalized contract the hard gate compares edgeScore >= minimumCompositeScore; failing it sets the suppression reason LOW_COMPOSITE_SCORE.",
            ja: "正規化契約では、ハードゲートが edgeScore >= minimumCompositeScore を比較します。満たさない場合は抑制理由 LOW_COMPOSITE_SCORE が設定されます。",
        },
        possibleTradingEffect: {
            en: "A stricter gate may reduce the number of candidates that pass this gate, but actual entries also depend on the other hard gates and downstream stages.",
            ja: "ゲートを厳しくすると、この条件を通過する候補は一般に少なくなる可能性があります。ただし実際のエントリーは、他のハードゲートや後続ステージにも依存します。",
        },
        related: ["minimumStrategyConfidence", "maximumStrategySpreadPct"],
        cycleStages: [3, 4],
        applicationTiming: {
            en: "Applies at the next Micro Edge Strategy decision boundary; not applied retroactively to an already-open position.",
            ja: "次の Micro Edge Strategy の判定タイミングから適用されます。すでに保有中のポジションに遡って適用されることはありません。",
        },
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote: {
            en: "LIVE runtime authority carries this value (legacy MIN_EDGE_SCORE equivalent).",
            ja: "LIVE の runtime authority がこの値を保持します（旧実装の MIN_EDGE_SCORE に相当）。",
        },
    },
    maximumStrategySpreadPct: {
        labelEn: "Maximum Strategy Spread",
        labelJa: "最大スプレッド",
        controls: {
            en: "The maximum symbol-normalized spread percent accepted by the strategy spread-safety gate.",
            ja: "戦略の spread-safety ゲートが許容する、シンボル正規化スプレッド（%）の最大値です。",
        },
        valueMeaning: {
            en: "A percent on the 0-100 scale, where 0.50 means 0.50 percent. The value is compared against the symbol-normalized spreadPct when the canonical authority is present.",
            ja: "0〜100 スケールのパーセントで、0.50 は 0.50% を意味します。canonical authority が存在する場合、シンボル正規化された spreadPct と比較されます。",
        },
        increase: {
            en: "The spread-safety gate accepts a wider spread before flagging ABNORMAL_SPREAD.",
            ja: "spread-safety ゲートは、ABNORMAL_SPREAD と判定するまでの許容スプレッドを広げます。",
        },
        decrease: {
            en: "The spread-safety gate accepts only a narrower spread.",
            ja: "spread-safety ゲートが許容するスプレッドは、より狭い範囲に限られます。",
        },
        directEffect: {
            en: "evaluate_spread_safety compares spreadPct <= maximumStrategySpreadPct when the canonical authority is present; otherwise the legacy absolute-price threshold MAX_SPREAD is used.",
            ja: "canonical authority が存在する場合、evaluate_spread_safety は spreadPct <= maximumStrategySpreadPct を比較します。存在しない場合は、旧実装の価格差絶対値しきい値 MAX_SPREAD が使用されます。",
        },
        possibleTradingEffect: {
            en: "A wider tolerance may allow more entries that would otherwise be rejected for spread, and may also change the spread-divergence exit; the final outcome also depends on liquidity, momentum and downstream conditions.",
            ja: "許容幅を広げると、スプレッドを理由に拒否されていたエントリーが増える可能性があり、spread-divergence 決済にも影響し得ます。最終的な結果は、流動性・モメンタム・後続条件にも依存します。",
        },
        related: ["minimumCompositeScore", "exitSpreadQualityMinimum"],
        cycleStages: [2, 4, 10],
        applicationTiming: {
            en: "Entry spread gate applies at the next strategy cycle. The formal spread-safety component of the exit reads the CURRENT parameter authority (not the entry snapshot); the separate spread-quality comparison uses the entry snapshot.",
            ja: "エントリーのスプレッドゲートは次の戦略サイクルから適用されます。決済の正式なスプレッド安全判定は現在のパラメーター権限を参照し（エントリー時スナップショットではありません）、別のスプレッド品質比較はエントリー時スナップショットを使用します。",
        },
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.IMPERFECT_UNIT_MAPPING,
        liveAuthorityNote: {
            en: "The legacy LIVE constant MAX_SPREAD is an absolute price threshold (0.0005), not a canonical percent, and is excluded from the LIVE runtime authority. This value is observability-only and is shown as legacy raw.",
            ja: "旧実装の LIVE 定数 MAX_SPREAD は価格差の絶対値しきい値（0.0005）であり、canonical なパーセントではありません。LIVE runtime authority からは除外されています。この値は参照専用（observability）であり、legacy raw として表示されます。",
        },
    },
    momentumWindowSeconds: {
        labelEn: "Momentum Window",
        labelJa: "モメンタム窓",
        controls: {
            en: "The causal momentum horizon, in seconds, used by the normalized momentum feature.",
            ja: "正規化モメンタム特徴量が使用する、因果的なモメンタム対象期間（秒）です。",
        },
        valueMeaning: {
            en: "A duration in seconds (5 to 600). It sets how much sampled price history is retained for the momentum calculation.",
            ja: "秒単位の期間（5〜600）です。モメンタム計算のために保持するサンプリング済み価格履歴の量を決めます。",
        },
        increase: {
            en: "The momentum lookback becomes longer, using more sampled history.",
            ja: "モメンタムの参照期間が長くなり、より多くのサンプリング履歴を使用します。",
        },
        decrease: {
            en: "The momentum lookback becomes shorter and more reactive.",
            ja: "モメンタムの参照期間が短くなり、より反応が速くなります。",
        },
        directEffect: {
            en: "MicrostructureStateBuilder.compute_strategy_momentum_features derives the retained bucket span from window_seconds.",
            ja: "MicrostructureStateBuilder.compute_strategy_momentum_features が、保持するバケット幅を window_seconds から導出します。",
        },
        possibleTradingEffect: {
            en: "A longer or shorter horizon can change momentum direction/validity and therefore the MOMENTUM_WARMUP, CONFLICTING_MOMENTUM and momentum-decay outcomes; other conditions still apply.",
            ja: "期間を長く／短くすると、モメンタムの方向や有効性が変わり、その結果 MOMENTUM_WARMUP・CONFLICTING_MOMENTUM・momentum decay の判定が変わり得ます。ただし他の条件も影響します。",
        },
        related: ["momentumMinimumWarmupSeconds"],
        cycleStages: [3, 4, 10],
        applicationTiming: {
            en: "Momentum features are recomputed every feature/strategy cycle (not part of the entry snapshot), so this affects both new entries and the live exit evaluation.",
            ja: "モメンタム特徴量は毎特徴量／戦略サイクルで再計算されます（エントリー時スナップショットには含まれません）。そのため、新規エントリーと保有中の決済判定の両方に影響します。",
        },
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.NO_LEGACY_EQUIVALENT,
        liveAuthorityNote: {
            en: "The legacy LIVE contract does not read this parameter; the LIVE value is a MicrostructureStateBuilder fallback and is excluded from the LIVE runtime authority.",
            ja: "旧実装の LIVE 契約はこのパラメーターを読み取りません。LIVE の値は MicrostructureStateBuilder のフォールバックであり、LIVE runtime authority からは除外されています。",
        },
    },
    minimumStrategyConfidence: {
        labelEn: "Minimum Confidence",
        labelJa: "最小信頼度",
        controls: {
            en: "The minimum confidence floor the strategy requires before an entry can be allowed.",
            ja: "戦略がエントリーを許可する前に要求する、confidence（信頼度）の最低値です。",
        },
        valueMeaning: {
            en: "A normalized score from 0.0 to 1.0. The strategy computes confidence as edgeScore * (0.5 + momentum * 0.5).",
            ja: "0.0〜1.0 の正規化スコアです。戦略は confidence を edgeScore * (0.5 + momentum * 0.5) として計算します。",
        },
        increase: {
            en: "The weak-confidence gate becomes stricter: confidence must be higher to pass.",
            ja: "weak-confidence ゲートが厳しくなります。通過するには、より高い confidence が必要になります。",
        },
        decrease: {
            en: "The weak-confidence gate becomes looser.",
            ja: "weak-confidence ゲートが緩くなります。",
        },
        directEffect: {
            en: "In the normalized PAPER contract the strategy hard-gate set does NOT include confidence; the gate is applied downstream by the execution path (LOW_CONFIDENCE). It compares confidence >= minimumStrategyConfidence, where confidence = edgeScore * (0.5 + momentum * 0.5), so confidence <= edgeScore. In the legacy LIVE contract the strategy weak-confidence branch applies.",
            ja: "正規化された PAPER 契約では、戦略のハードゲート群に confidence は含まれません。このゲートは実行経路の下流で適用されます（LOW_CONFIDENCE）。confidence >= minimumStrategyConfidence を比較し、confidence = edgeScore * (0.5 + momentum * 0.5) のため confidence <= edgeScore です。旧来の LIVE 契約では戦略の weak-confidence 分岐が適用されます。",
        },
        possibleTradingEffect: {
            en: "A stricter floor may reduce entries that pass this gate; the actual number also depends on the other gates. If it exceeds the composite score, the backend emits a cross-field warning that the confidence floor may never bind.",
            ja: "下限を厳しくすると、このゲートを通過するエントリーは一般に少なくなる可能性があります。実際の件数は他のゲートにも依存します。composite score を上回る場合、バックエンドは「confidence floor が機能しない可能性がある」というクロスフィールド警告を出力します。",
        },
        related: ["minimumCompositeScore"],
        cycleStages: [4, 5],
        applicationTiming: {
            en: "Applies at the next strategy decision boundary; not retroactive to an open position.",
            ja: "次の戦略判定タイミングから適用されます。保有ポジションに遡って適用されることはありません。",
        },
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote: {
            en: "LIVE runtime authority carries this value (legacy MIN_CONFIDENCE equivalent).",
            ja: "LIVE の runtime authority がこの値を保持します（旧実装の MIN_CONFIDENCE に相当）。",
        },
    },
    maximumHoldMs: {
        labelEn: "Maximum Hold",
        labelJa: "最大保有時間",
        controls: {
            en: "The hard maximum holding time before a formal MAX_HOLD exit.",
            ja: "正式な MAX_HOLD 決済が発生するまでの、ハードな最大保有時間です。",
        },
        valueMeaning: {
            en: "An integer number of milliseconds (100 to 60000).",
            ja: "ミリ秒単位の整数値（100〜60000）です。",
        },
        increase: {
            en: "A position may be held longer before the hard MAX_HOLD bound forces an exit.",
            ja: "ハードな MAX_HOLD により強制決済されるまでの保有時間が長くなります。",
        },
        decrease: {
            en: "The hard MAX_HOLD bound is reached sooner.",
            ja: "ハードな MAX_HOLD に到達するのが早くなります。",
        },
        directEffect: {
            en: "The exit evaluator returns MAX_HOLD once holding_duration_ms >= maximumHoldMs. It is the last resort in the strategy exit order, so any earlier strategy or safety exit may occur first.",
            ja: "決済評価は holding_duration_ms >= maximumHoldMs となった時点で MAX_HOLD を返します。これは戦略決済順の最後の手段であり、それより早い戦略決済や安全決済が先に発生し得ます。",
        },
        possibleTradingEffect: {
            en: "This changes when a position is forced closed by time; realised outcome still depends on market movement while open.",
            ja: "時間による強制決済のタイミングが変わります。実現結果は、保有中の市場変動にも依存します。",
        },
        related: ["minimumHoldMs"],
        cycleStages: [10, 11],
        applicationTiming: {
            en: "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
            ja: "ポジション保有中に評価され、エントリー時に取得した決済しきい値（snapshot-at-entry）を使用します。",
        },
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote: {
            en: "LIVE runtime authority carries this value (legacy MAX_HOLD_MS equivalent).",
            ja: "LIVE の runtime authority がこの値を保持します（旧実装の MAX_HOLD_MS に相当）。",
        },
    },
    minimumHoldMs: {
        labelEn: "Minimum Hold",
        labelJa: "最小保有時間",
        controls: {
            en: "The soft-exit floor that gates reversal and momentum-decay exits.",
            ja: "reversal（反転）および momentum-decay のソフト決済を制御する、最低保有時間の下限です。",
        },
        valueMeaning: {
            en: "An integer number of milliseconds (0 to 60000).",
            ja: "ミリ秒単位の整数値（0〜60000）です。",
        },
        increase: {
            en: "Soft microstructure exits must wait longer before they may fire.",
            ja: "ソフトなマイクロストラクチャ決済が発動するまで、より長く待つ必要があります。",
        },
        decrease: {
            en: "Soft microstructure exits may fire earlier.",
            ja: "ソフトなマイクロストラクチャ決済がより早く発動できるようになります。",
        },
        directEffect: {
            en: "The exit evaluator only runs the momentum-decay branch once holding_duration_ms >= minimumHoldMs; early liquidity/spread exits before the floor require repeated confirmation. Microstructure reversal is immediate and is not gated by this floor, and safety exits (SL/TP/trailing, emergency flatten, manual close) are outside this authority.",
            ja: "決済評価は holding_duration_ms >= minimumHoldMs となって初めて momentum-decay 分岐を実行します。下限前の早期の流動性・スプレッド決済は、繰り返し確認を必要とします。マイクロストラクチャ反転は即時で、この下限の対象外です。また安全決済（SL/TP/トレーリング・緊急フラット・手動クローズ）はこの権限の範囲外です。",
        },
        possibleTradingEffect: {
            en: "A longer floor may keep positions open through short adverse noise; the eventual exit reason still depends on liquidity, spread and momentum conditions.",
            ja: "下限を長くすると、短期的な不利なノイズの間もポジションを保持し続ける可能性があります。最終的な決済理由は、流動性・スプレッド・モメンタムの状況にも依存します。",
        },
        related: ["maximumHoldMs"],
        cycleStages: [10],
        applicationTiming: {
            en: "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
            ja: "ポジション保有中に評価され、エントリー時に取得した決済しきい値（snapshot-at-entry）を使用します。",
        },
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote: {
            en: "LIVE runtime authority carries this value (legacy MIN_HOLD_MS equivalent).",
            ja: "LIVE の runtime authority がこの値を保持します（旧実装の MIN_HOLD_MS に相当）。",
        },
    },
    exitMomentumMinimum: {
        labelEn: "Exit Momentum Minimum",
        labelJa: "決済モメンタム下限",
        controls: {
            en: "The momentum-decay exit threshold used after the minimum hold floor.",
            ja: "最低保有時間の下限を過ぎた後に使用される、momentum-decay 決済のしきい値です。",
        },
        valueMeaning: {
            en: "A normalized score from 0.0 to 1.0 compared against the current momentum score.",
            ja: "現在のモメンタムスコアと比較される、0.0〜1.0 の正規化スコアです。",
        },
        increase: {
            en: "The momentum-decay exit triggers more readily, because the required momentum floor is higher.",
            ja: "要求されるモメンタムの下限が高くなるため、momentum-decay 決済が発動しやすくなります。",
        },
        decrease: {
            en: "The momentum-decay exit triggers less readily.",
            ja: "momentum-decay 決済が発動しにくくなります。",
        },
        directEffect: {
            en: "The exit evaluator returns MOMENTUM_DECAY when momentum_score < exitMomentumMinimum (after minimumHoldMs).",
            ja: "決済評価は、momentum_score < exitMomentumMinimum の場合に MOMENTUM_DECAY を返します（minimumHoldMs 経過後）。",
        },
        possibleTradingEffect: {
            en: "This can change how long a decaying position is held; the realised outcome still depends on price movement and the other exit conditions.",
            ja: "モメンタムが減衰したポジションを保有する時間が変わり得ます。実現結果は、価格変動や他の決済条件にも依存します。",
        },
        related: [
            "momentumWindowSeconds",
            "exitLiquidityQualityMinimum",
            "exitSpreadQualityMinimum",
        ],
        cycleStages: [10],
        applicationTiming: {
            en: "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
            ja: "ポジション保有中に評価され、エントリー時に取得した決済しきい値（snapshot-at-entry）を使用します。",
        },
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote: {
            en: "LIVE runtime authority carries this value (legacy EXIT_MOMENTUM_MIN equivalent).",
            ja: "LIVE の runtime authority がこの値を保持します（旧実装の EXIT_MOMENTUM_MIN に相当）。",
        },
    },
    exitLiquidityQualityMinimum: {
        labelEn: "Exit Liquidity Quality Minimum",
        labelJa: "決済流動性品質下限",
        controls: {
            en: "The liquidity-deterioration exit threshold.",
            ja: "流動性悪化（liquidity-deterioration）決済のしきい値です。",
        },
        valueMeaning: {
            en: "A normalized score from 0.0 to 1.0 compared against the current liquidity quality.",
            ja: "現在の流動性品質（liquidity quality）と比較される、0.0〜1.0 の正規化スコアです。",
        },
        increase: {
            en: "The liquidity-deterioration exit triggers more readily, because the required liquidity floor is higher.",
            ja: "要求される流動性の下限が高くなるため、流動性悪化決済が発動しやすくなります。",
        },
        decrease: {
            en: "The liquidity-deterioration exit triggers less readily.",
            ja: "流動性悪化決済が発動しにくくなります。",
        },
        directEffect: {
            en: "The exit evaluator returns LIQUIDITY_DETERIORATION when liquidity_quality < exitLiquidityQualityMinimum, or when formal liquidity safety reports unsafe.",
            ja: "決済評価は、liquidity_quality < exitLiquidityQualityMinimum の場合、または正式な流動性安全判定が unsafe を報告した場合に LIQUIDITY_DETERIORATION を返します。",
        },
        possibleTradingEffect: {
            en: "This can change how quickly a position is closed when liquidity weakens; the realised outcome still depends on the market at that moment.",
            ja: "流動性が弱まった際にポジションを決済する速さが変わり得ます。実現結果は、その時点の市場状況にも依存します。",
        },
        related: ["liquidityQualityPercentile", "exitSpreadQualityMinimum"],
        cycleStages: [10],
        applicationTiming: {
            en: "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
            ja: "ポジション保有中に評価され、エントリー時に取得した決済しきい値（snapshot-at-entry）を使用します。",
        },
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote: {
            en: "LIVE runtime authority carries this value (legacy EXIT_LIQUIDITY_QUALITY_MIN equivalent).",
            ja: "LIVE の runtime authority がこの値を保持します（旧実装の EXIT_LIQUIDITY_QUALITY_MIN に相当）。",
        },
    },
    exitSpreadQualityMinimum: {
        labelEn: "Exit Spread Quality Minimum",
        labelJa: "決済スプレッド品質下限",
        controls: {
            en: "The spread-divergence exit threshold.",
            ja: "スプレッド乖離（spread-divergence）決済のしきい値です。",
        },
        valueMeaning: {
            en: "A normalized score from 0.0 to 1.0 compared against the current spread quality.",
            ja: "現在のスプレッド品質（spread quality）と比較される、0.0〜1.0 の正規化スコアです。",
        },
        increase: {
            en: "The spread-divergence exit triggers more readily, because the required spread quality floor is higher.",
            ja: "要求されるスプレッド品質の下限が高くなるため、spread-divergence 決済が発動しやすくなります。",
        },
        decrease: {
            en: "The spread-divergence exit triggers less readily.",
            ja: "spread-divergence 決済が発動しにくくなります。",
        },
        directEffect: {
            en: "The exit evaluator returns SPREAD_DIVERGENCE when spread_quality < exitSpreadQualityMinimum, or when formal spread safety reports unsafe.",
            ja: "決済評価は、spread_quality < exitSpreadQualityMinimum の場合、または正式なスプレッド安全判定が unsafe を報告した場合に SPREAD_DIVERGENCE を返します。",
        },
        possibleTradingEffect: {
            en: "This can change how quickly a position is closed when the spread widens; the realised outcome still depends on the market at that moment.",
            ja: "スプレッドが拡大した際にポジションを決済する速さが変わり得ます。実現結果は、その時点の市場状況にも依存します。",
        },
        related: ["maximumStrategySpreadPct", "exitLiquidityQualityMinimum"],
        cycleStages: [10],
        applicationTiming: {
            en: "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
            ja: "ポジション保有中に評価され、エントリー時に取得した決済しきい値（snapshot-at-entry）を使用します。",
        },
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote: {
            en: "LIVE runtime authority carries this value (legacy EXIT_SPREAD_QUALITY_MIN equivalent).",
            ja: "LIVE の runtime authority がこの値を保持します（旧実装の EXIT_SPREAD_QUALITY_MIN に相当）。",
        },
    },
    momentumMinimumWarmupSeconds: {
        labelEn: "Momentum Warmup",
        labelJa: "モメンタム暖機",
        controls: {
            en: "The minimum elapsed causal history before momentum is considered usable.",
            ja: "モメンタムが利用可能と見なされるまでに必要な、最低経過時間（因果的履歴）です。",
        },
        valueMeaning: {
            en: "A duration in seconds (0 to 600).",
            ja: "秒単位の期間（0〜600）です。",
        },
        increase: {
            en: "Momentum stays unusable for longer after history begins.",
            ja: "履歴の蓄積が始まってから、モメンタムが利用可能になるまでの時間が長くなります。",
        },
        decrease: {
            en: "Momentum becomes usable sooner.",
            ja: "モメンタムがより早く利用可能になります。",
        },
        directEffect: {
            en: "MicrostructureStateBuilder.compute_strategy_momentum_features requires the elapsed history to reach minimum_warmup_seconds before momentum is ready.",
            ja: "MicrostructureStateBuilder.compute_strategy_momentum_features は、モメンタムが ready になる前に、経過履歴が minimum_warmup_seconds に到達することを要求します。",
        },
        possibleTradingEffect: {
            en: "A longer warmup can delay momentum-dependent entries (MOMENTUM_WARMUP); actual entry timing still depends on the other gates.",
            ja: "暖機時間を長くすると、モメンタムに依存するエントリーが遅れる可能性があります（MOMENTUM_WARMUP）。実際のエントリータイミングは他のゲートにも依存します。",
        },
        related: ["momentumWindowSeconds"],
        cycleStages: [3, 4],
        applicationTiming: {
            en: "Applies at the next feature/strategy cycle.",
            ja: "次の特徴量／戦略サイクルから適用されます。",
        },
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.NO_LEGACY_EQUIVALENT,
        liveAuthorityNote: {
            en: "The legacy LIVE contract does not read this parameter; the LIVE value is a MicrostructureStateBuilder fallback and is excluded from the LIVE runtime authority.",
            ja: "旧実装の LIVE 契約はこのパラメーターを読み取りません。LIVE の値は MicrostructureStateBuilder のフォールバックであり、LIVE runtime authority からは除外されています。",
        },
    },
    absorptionVolumePercentile: {
        labelEn: "Absorption Volume Percentile",
        labelJa: "吸収出来高パーセンタイル",
        controls: {
            en: "The rolling volume percentile that marks abnormal depth for the absorption detector.",
            ja: "absorption 検出器が異常な板厚（abnormal depth）を判定するために使用する、ローリング出来高パーセンタイルです。",
        },
        valueMeaning: {
            en: "A normalized percentile rank from 0.0 to 1.0, not a percent. 0.90 selects the 90th percentile of the symbol's prior volume history; it is used as an interpolation position over sorted prior observations.",
            ja: "パーセントではなく、0.0〜1.0 の正規化パーセンタイル順位です。0.90 はそのシンボルの過去出来高履歴の 90 パーセンタイルを選択し、ソート済みの過去観測値に対する補間位置として使用されます。",
        },
        increase: {
            en: "The abnormal-depth threshold becomes stricter (a more extreme volume percentile).",
            ja: "異常板厚のしきい値が厳しくなります（より極端な出来高パーセンタイル）。",
        },
        decrease: {
            en: "The abnormal-depth threshold becomes less strict.",
            ja: "異常板厚のしきい値が緩くなります。",
        },
        directEffect: {
            en: "MicrostructureStateBuilder derives absorption_volume_threshold = rolling_percentile(history, absorptionVolumePercentile). The resulting absorptionDetected flag becomes the liquidity-safety entry gate and a liquidity-deterioration exit trigger (detector -> feature -> gate), not a direct final comparison.",
            ja: "MicrostructureStateBuilder は absorption_volume_threshold = rolling_percentile(history, absorptionVolumePercentile) を導出します。その結果の absorptionDetected フラグが流動性安全のエントリーゲートおよび流動性悪化決済のトリガーとなります（検出器 → 特徴量 → ゲート）。直接の最終比較ではありません。",
        },
        possibleTradingEffect: {
            en: "This can change how often the absorption detector flags abnormal depth, which may influence momentum/entry evidence; the actual decision still depends on the other detector and gate conditions.",
            ja: "absorption 検出器が異常板厚を検出する頻度が変わり、モメンタム／エントリーの根拠に影響し得ます。実際の判定は他の検出器やゲート条件にも依存します。",
        },
        related: ["liquidityQualityPercentile"],
        cycleStages: [2, 3, 4],
        applicationTiming: {
            en: "Applies at the next feature/strategy cycle.",
            ja: "次の特徴量／戦略サイクルから適用されます。",
        },
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.NO_LEGACY_EQUIVALENT,
        liveAuthorityNote: {
            en: "The legacy LIVE contract does not read this parameter; the LIVE value is a MicrostructureStateBuilder fallback and is excluded from the LIVE runtime authority.",
            ja: "旧実装の LIVE 契約はこのパラメーターを読み取りません。LIVE の値は MicrostructureStateBuilder のフォールバックであり、LIVE runtime authority からは除外されています。",
        },
    },
    liquidityQualityPercentile: {
        labelEn: "Liquidity Quality Percentile",
        labelJa: "流動性品質パーセンタイル",
        controls: {
            en: "The rolling volume percentile used as the symbol-relative liquidity quality reference.",
            ja: "シンボル相対の流動性品質（liquidity quality）の基準として使用される、ローリング出来高パーセンタイルです。",
        },
        valueMeaning: {
            en: "A normalized percentile rank from 0.0 to 1.0, not a percent. 0.90 selects the 90th percentile of the symbol's prior volume history as the reference.",
            ja: "パーセントではなく、0.0〜1.0 の正規化パーセンタイル順位です。0.90 はそのシンボルの過去出来高履歴の 90 パーセンタイルを基準として選択します。",
        },
        increase: {
            en: "The liquidity quality reference becomes stricter (a higher prior-volume percentile).",
            ja: "流動性品質の基準が厳しくなります（より高い過去出来高パーセンタイル）。",
        },
        decrease: {
            en: "The liquidity quality reference becomes less strict.",
            ja: "流動性品質の基準が緩くなります。",
        },
        directEffect: {
            en: "MicrostructureStateBuilder derives liquidity_quality_reference = rolling_percentile(history, liquidityQualityPercentile) to make depth quality symbol-relative. The resulting normalizedLiquidityQuality feeds a 0.20 edge weight and the liquidity-exit comparison (detector -> feature -> gate).",
            ja: "MicrostructureStateBuilder は、板厚品質をシンボル相対にするため liquidity_quality_reference = rolling_percentile(history, liquidityQualityPercentile) を導出します。その結果の normalizedLiquidityQuality が edge の 0.20 の重みと流動性決済の比較に供給されます（検出器 → 特徴量 → ゲート）。",
        },
        possibleTradingEffect: {
            en: "This can change the computed liquidity quality used by entry and exit comparisons; the actual outcome still depends on the other conditions.",
            ja: "エントリーおよび決済の比較に使用される流動性品質の計算値が変わり得ます。実際の結果は他の条件にも依存します。",
        },
        related: ["absorptionVolumePercentile", "exitLiquidityQualityMinimum"],
        cycleStages: [2, 3, 4],
        applicationTiming: {
            en: "Applies at the next feature/strategy cycle.",
            ja: "次の特徴量／戦略サイクルから適用されます。",
        },
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.NO_LEGACY_EQUIVALENT,
        liveAuthorityNote: {
            en: "The legacy LIVE contract does not read this parameter; the LIVE value is a MicrostructureStateBuilder fallback and is excluded from the LIVE runtime authority.",
            ja: "旧実装の LIVE 契約はこのパラメーターを読み取りません。LIVE の値は MicrostructureStateBuilder のフォールバックであり、LIVE runtime authority からは除外されています。",
        },
    },
});

export const GUIDE_PARAMETER_KEYS = Object.freeze(
    Object.keys(PARAMETER_GUIDE),
);

export const GUIDE_BILINGUAL_FIELDS = Object.freeze([
    "controls",
    "valueMeaning",
    "increase",
    "decrease",
    "directEffect",
    "possibleTradingEffect",
    "applicationTiming",
    "liveAuthorityNote",
]);

export const guideFor = (name) => PARAMETER_GUIDE[name] ?? null;

export const relatedLabel = (name) => RELATED_LABELS[name] ?? name;

export const liveMigrationLabel = (migration) => (
    LIVE_MIGRATION_LABELS[migration] ?? "LIVE migration state unavailable"
);

export const liveMigrationLabelJa = (migration) => (
    LIVE_MIGRATION_LABELS_JA[migration] ?? "LIVE の移行状態は不明です"
);

export const cycleStageLabel = (stage) => (
    CYCLE_STAGES[stage] ?? {
        en: `Stage ${stage}`,
        ja: `ステージ ${stage}`,
    }
);
