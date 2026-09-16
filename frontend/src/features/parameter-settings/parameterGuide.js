/* =================================================
   PARAMETER GUIDE metadata (static, operator-facing).

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

   DIRECT EFFECT describes the code-level threshold/window that changes.
   POSSIBLE TRADING EFFECT describes plausible downstream behaviour and is
   deliberately non-deterministic: it never claims performance, win rate or
   profitability.
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

/* LIVE values whose legacy runtime semantic is not proven equivalent to the
   canonical unit.  The UI must not present a canonical suffix for these. */
export const LEGACY_RAW_PARAMETERS = Object.freeze([
    "maximumStrategySpreadPct",
]);

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
        controls:
            "The minimum composite decision score the Micro Edge Strategy requires before an entry can be allowed.",
        valueMeaning:
            "A normalized score from 0.0 to 1.0. The strategy computes edgeScore as a weighted blend of pressure imbalance (0.35), momentum (0.30), spread quality (0.15) and liquidity quality (0.20).",
        increase:
            "The compositeDecisionScore gate becomes stricter: edgeScore must be higher for the entry gate to pass.",
        decrease:
            "The compositeDecisionScore gate becomes looser: a lower edgeScore can pass.",
        directEffect:
            "In the normalized contract the hard gate compares edgeScore >= minimumCompositeScore; failing it sets the suppression reason LOW_COMPOSITE_SCORE.",
        possibleTradingEffect:
            "A stricter gate may reduce the number of candidates that pass this gate, but actual entries also depend on the other hard gates and downstream stages.",
        related: ["minimumStrategyConfidence", "maximumStrategySpreadPct"],
        cycleStages: [3, 4],
        applicationTiming:
            "Applies at the next Micro Edge Strategy decision boundary; not applied retroactively to an already-open position.",
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote:
            "LIVE runtime authority carries this value (legacy MIN_EDGE_SCORE equivalent).",
    },
    maximumStrategySpreadPct: {
        labelEn: "Maximum Strategy Spread",
        labelJa: "最大スプレッド",
        controls:
            "The maximum symbol-normalized spread percent accepted by the strategy spread-safety gate.",
        valueMeaning:
            "A percent on the 0-100 scale, where 0.50 means 0.50 percent. The value is compared against the symbol-normalized spreadPct when the canonical authority is present.",
        increase:
            "The spread-safety gate accepts a wider spread before flagging ABNORMAL_SPREAD.",
        decrease:
            "The spread-safety gate accepts only a narrower spread.",
        directEffect:
            "evaluate_spread_safety compares spreadPct <= maximumStrategySpreadPct when the canonical authority is present; otherwise the legacy absolute-price threshold MAX_SPREAD is used.",
        possibleTradingEffect:
            "A wider tolerance may allow more entries that would otherwise be rejected for spread, and may also change the spread-divergence exit; the final outcome also depends on liquidity, momentum and downstream conditions.",
        related: ["minimumCompositeScore", "exitSpreadQualityMinimum"],
        cycleStages: [2, 4, 10],
        applicationTiming:
            "Entry spread gate applies at the next strategy cycle. The spread-divergence exit reads the entry snapshot for an open position.",
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.IMPERFECT_UNIT_MAPPING,
        liveAuthorityNote:
            "The legacy LIVE constant MAX_SPREAD is an absolute price threshold (0.0005), not a canonical percent, and is excluded from the LIVE runtime authority. This value is observability-only and is shown as legacy raw.",
    },
    momentumWindowSeconds: {
        labelEn: "Momentum Window",
        labelJa: "モメンタム窓",
        controls:
            "The causal momentum horizon, in seconds, used by the normalized momentum feature.",
        valueMeaning:
            "A duration in seconds (5 to 600). It sets how much sampled price history is retained for the momentum calculation.",
        increase:
            "The momentum lookback becomes longer, using more sampled history.",
        decrease:
            "The momentum lookback becomes shorter and more reactive.",
        directEffect:
            "MicrostructureStateBuilder.compute_strategy_momentum_features derives the retained bucket span from window_seconds.",
        possibleTradingEffect:
            "A longer or shorter horizon can change momentum direction/validity and therefore the MOMENTUM_WARMUP, CONFLICTING_MOMENTUM and momentum-decay outcomes; other conditions still apply.",
        related: ["momentumMinimumWarmupSeconds"],
        cycleStages: [3, 4, 10],
        applicationTiming:
            "Applies at the next feature/strategy cycle; open positions keep the momentum thresholds captured at entry.",
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.NO_LEGACY_EQUIVALENT,
        liveAuthorityNote:
            "The legacy LIVE contract does not read this parameter; the LIVE value is a MicrostructureStateBuilder fallback and is excluded from the LIVE runtime authority.",
    },
    minimumStrategyConfidence: {
        labelEn: "Minimum Confidence",
        labelJa: "最小信頼度",
        controls:
            "The minimum confidence floor the strategy requires before an entry can be allowed.",
        valueMeaning:
            "A normalized score from 0.0 to 1.0. The strategy computes confidence as edgeScore * (0.5 + momentum * 0.5).",
        increase:
            "The weak-confidence gate becomes stricter: confidence must be higher to pass.",
        decrease:
            "The weak-confidence gate becomes looser.",
        directEffect:
            "The entry decision compares edgeScore-derived confidence >= minimumStrategyConfidence; failing it sets the suppression reason LOW_CONFIDENCE.",
        possibleTradingEffect:
            "A stricter floor may reduce entries that pass this gate; the actual number also depends on the other gates. If it exceeds the composite score, the backend emits a cross-field warning that the confidence floor may never bind.",
        related: ["minimumCompositeScore"],
        cycleStages: [4, 5],
        applicationTiming:
            "Applies at the next strategy decision boundary; not retroactive to an open position.",
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote:
            "LIVE runtime authority carries this value (legacy MIN_CONFIDENCE equivalent).",
    },
    maximumHoldMs: {
        labelEn: "Maximum Hold",
        labelJa: "最大保有時間",
        controls:
            "The hard maximum holding time before a formal MAX_HOLD exit.",
        valueMeaning:
            "An integer number of milliseconds (100 to 60000).",
        increase:
            "A position may be held longer before the hard MAX_HOLD bound forces an exit.",
        decrease:
            "The hard MAX_HOLD bound is reached sooner.",
        directEffect:
            "The exit evaluator returns MAX_HOLD once holding_duration_ms >= maximumHoldMs.",
        possibleTradingEffect:
            "This changes when a position is forced closed by time; realised outcome still depends on market movement while open.",
        related: ["minimumHoldMs"],
        cycleStages: [10, 11],
        applicationTiming:
            "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote:
            "LIVE runtime authority carries this value (legacy MAX_HOLD_MS equivalent).",
    },
    minimumHoldMs: {
        labelEn: "Minimum Hold",
        labelJa: "最小保有時間",
        controls:
            "The soft-exit floor that gates reversal and momentum-decay exits.",
        valueMeaning:
            "An integer number of milliseconds (0 to 60000).",
        increase:
            "Soft microstructure exits must wait longer before they may fire.",
        decrease:
            "Soft microstructure exits may fire earlier.",
        directEffect:
            "The exit evaluator only runs the momentum-decay branch once holding_duration_ms >= minimumHoldMs; early liquidity/spread exits before the floor require repeated confirmation. Safety exits and the ExecutionEngine SL/TP authority are not gated by this floor.",
        possibleTradingEffect:
            "A longer floor may keep positions open through short adverse noise; the eventual exit reason still depends on liquidity, spread and momentum conditions.",
        related: ["maximumHoldMs"],
        cycleStages: [10],
        applicationTiming:
            "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote:
            "LIVE runtime authority carries this value (legacy MIN_HOLD_MS equivalent).",
    },
    exitMomentumMinimum: {
        labelEn: "Exit Momentum Minimum",
        labelJa: "決済モメンタム下限",
        controls:
            "The momentum-decay exit threshold used after the minimum hold floor.",
        valueMeaning:
            "A normalized score from 0.0 to 1.0 compared against the current momentum score.",
        increase:
            "The momentum-decay exit triggers more readily, because the required momentum floor is higher.",
        decrease:
            "The momentum-decay exit triggers less readily.",
        directEffect:
            "The exit evaluator returns MOMENTUM_DECAY when momentum_score < exitMomentumMinimum (after minimumHoldMs).",
        possibleTradingEffect:
            "This can change how long a decaying position is held; the realised outcome still depends on price movement and the other exit conditions.",
        related: [
            "momentumWindowSeconds",
            "exitLiquidityQualityMinimum",
            "exitSpreadQualityMinimum",
        ],
        cycleStages: [10],
        applicationTiming:
            "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote:
            "LIVE runtime authority carries this value (legacy EXIT_MOMENTUM_MIN equivalent).",
    },
    exitLiquidityQualityMinimum: {
        labelEn: "Exit Liquidity Quality Minimum",
        labelJa: "決済流動性品質下限",
        controls:
            "The liquidity-deterioration exit threshold.",
        valueMeaning:
            "A normalized score from 0.0 to 1.0 compared against the current liquidity quality.",
        increase:
            "The liquidity-deterioration exit triggers more readily, because the required liquidity floor is higher.",
        decrease:
            "The liquidity-deterioration exit triggers less readily.",
        directEffect:
            "The exit evaluator returns LIQUIDITY_DETERIORATION when liquidity_quality < exitLiquidityQualityMinimum, or when formal liquidity safety reports unsafe.",
        possibleTradingEffect:
            "This can change how quickly a position is closed when liquidity weakens; the realised outcome still depends on the market at that moment.",
        related: ["liquidityQualityPercentile", "exitSpreadQualityMinimum"],
        cycleStages: [10],
        applicationTiming:
            "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote:
            "LIVE runtime authority carries this value (legacy EXIT_LIQUIDITY_QUALITY_MIN equivalent).",
    },
    exitSpreadQualityMinimum: {
        labelEn: "Exit Spread Quality Minimum",
        labelJa: "決済スプレッド品質下限",
        controls:
            "The spread-divergence exit threshold.",
        valueMeaning:
            "A normalized score from 0.0 to 1.0 compared against the current spread quality.",
        increase:
            "The spread-divergence exit triggers more readily, because the required spread quality floor is higher.",
        decrease:
            "The spread-divergence exit triggers less readily.",
        directEffect:
            "The exit evaluator returns SPREAD_DIVERGENCE when spread_quality < exitSpreadQualityMinimum, or when formal spread safety reports unsafe.",
        possibleTradingEffect:
            "This can change how quickly a position is closed when the spread widens; the realised outcome still depends on the market at that moment.",
        related: ["maximumStrategySpreadPct", "exitLiquidityQualityMinimum"],
        cycleStages: [10],
        applicationTiming:
            "Evaluated while a position is open, using the exit thresholds captured at entry (snapshot-at-entry).",
        snapshotAtEntry: true,
        liveMigration: LIVE_MIGRATION.EXACT,
        liveAuthorityNote:
            "LIVE runtime authority carries this value (legacy EXIT_SPREAD_QUALITY_MIN equivalent).",
    },
    momentumMinimumWarmupSeconds: {
        labelEn: "Momentum Warmup",
        labelJa: "モメンタム暖機",
        controls:
            "The minimum elapsed causal history before momentum is considered usable.",
        valueMeaning:
            "A duration in seconds (0 to 600).",
        increase:
            "Momentum stays unusable for longer after history begins.",
        decrease:
            "Momentum becomes usable sooner.",
        directEffect:
            "MicrostructureStateBuilder.compute_strategy_momentum_features requires the elapsed history to reach minimum_warmup_seconds before momentum is ready.",
        possibleTradingEffect:
            "A longer warmup can delay momentum-dependent entries (MOMENTUM_WARMUP); actual entry timing still depends on the other gates.",
        related: ["momentumWindowSeconds"],
        cycleStages: [3, 4],
        applicationTiming:
            "Applies at the next feature/strategy cycle.",
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.NO_LEGACY_EQUIVALENT,
        liveAuthorityNote:
            "The legacy LIVE contract does not read this parameter; the LIVE value is a MicrostructureStateBuilder fallback and is excluded from the LIVE runtime authority.",
    },
    absorptionVolumePercentile: {
        labelEn: "Absorption Volume Percentile",
        labelJa: "吸収出来高パーセンタイル",
        controls:
            "The rolling volume percentile that marks abnormal depth for the absorption detector.",
        valueMeaning:
            "A normalized percentile rank from 0.0 to 1.0, not a percent. 0.90 selects the 90th percentile of the symbol's prior volume history; it is used as an interpolation position over sorted prior observations.",
        increase:
            "The abnormal-depth threshold becomes stricter (a more extreme volume percentile).",
        decrease:
            "The abnormal-depth threshold becomes less strict.",
        directEffect:
            "MicrostructureStateBuilder derives absorption_volume_threshold = rolling_percentile(history, absorptionVolumePercentile).",
        possibleTradingEffect:
            "This can change how often the absorption detector flags abnormal depth, which may influence momentum/entry evidence; the actual decision still depends on the other detector and gate conditions.",
        related: ["liquidityQualityPercentile"],
        cycleStages: [2, 3, 4],
        applicationTiming:
            "Applies at the next feature/strategy cycle.",
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.NO_LEGACY_EQUIVALENT,
        liveAuthorityNote:
            "The legacy LIVE contract does not read this parameter; the LIVE value is a MicrostructureStateBuilder fallback and is excluded from the LIVE runtime authority.",
    },
    liquidityQualityPercentile: {
        labelEn: "Liquidity Quality Percentile",
        labelJa: "流動性品質パーセンタイル",
        controls:
            "The rolling volume percentile used as the symbol-relative liquidity quality reference.",
        valueMeaning:
            "A normalized percentile rank from 0.0 to 1.0, not a percent. 0.90 selects the 90th percentile of the symbol's prior volume history as the reference.",
        increase:
            "The liquidity quality reference becomes stricter (a higher prior-volume percentile).",
        decrease:
            "The liquidity quality reference becomes less strict.",
        directEffect:
            "MicrostructureStateBuilder derives liquidity_quality_reference = rolling_percentile(history, liquidityQualityPercentile) to make depth quality symbol-relative.",
        possibleTradingEffect:
            "This can change the computed liquidity quality used by entry and exit comparisons; the actual outcome still depends on the other conditions.",
        related: ["absorptionVolumePercentile", "exitLiquidityQualityMinimum"],
        cycleStages: [2, 3, 4],
        applicationTiming:
            "Applies at the next feature/strategy cycle.",
        snapshotAtEntry: false,
        liveMigration: LIVE_MIGRATION.NO_LEGACY_EQUIVALENT,
        liveAuthorityNote:
            "The legacy LIVE contract does not read this parameter; the LIVE value is a MicrostructureStateBuilder fallback and is excluded from the LIVE runtime authority.",
    },
});

export const GUIDE_PARAMETER_KEYS = Object.freeze(
    Object.keys(PARAMETER_GUIDE),
);

export const guideFor = (name) => PARAMETER_GUIDE[name] ?? null;

export const relatedLabel = (name) => RELATED_LABELS[name] ?? name;

export const liveMigrationLabel = (migration) => (
    LIVE_MIGRATION_LABELS[migration] ?? "LIVE migration state unavailable"
);
