/* =================================================
   PARAMETER PRESENTATION MODEL (static, bilingual).

   One centralized operator-facing model for grouping, impact/directness,
   direction hints, the Parameter Map and the How-To-Tune goals.  It is
   grounded in the completed code/authority audit
   (TRADINGAI-WORK-E-PARAMETER-IMPACT-PRIORITY-DEPENDENCY-AUDIT-1).

   It carries NO runtime authority, NO parameter values, NO ranges and NO
   writable state.  Configured/Effective/Runtime and scope authority keep
   coming from the canonical schema + API + page state.  Canonical
   identifiers are never translated.

   No profitability, win-rate or optimality claims are made here.
================================================= */

export const PARAMETER_GROUPS = Object.freeze([
    {
        id: "ENTRY",
        labelEn: "Entry / Trade Selection",
        labelJa: "エントリー / トレード選別",
        description: {
            en: "Parameters that directly decide whether a candidate entry may pass the strategy gates.",
            ja: "候補エントリーが戦略ゲートを通過できるかを直接左右するパラメーターです。",
        },
        parameters: [
            "minimumCompositeScore",
            "maximumStrategySpreadPct",
            "minimumStrategyConfidence",
        ],
    },
    {
        id: "MOMENTUM",
        labelEn: "Momentum / Response",
        labelJa: "モメンタム / 反応",
        description: {
            en: "Parameters that shape how momentum is observed and when it becomes usable.",
            ja: "モメンタムの観測方法と、利用可能になるタイミングを形作るパラメーターです。",
        },
        parameters: [
            "momentumWindowSeconds",
            "momentumMinimumWarmupSeconds",
        ],
    },
    {
        id: "EXIT",
        labelEn: "Exit / Holding",
        labelJa: "決済 / 保有",
        description: {
            en: "Parameters that control holding time and the soft deterioration exits while a position is open.",
            ja: "保有時間と、ポジション保有中のソフトな悪化決済を制御するパラメーターです。",
        },
        subgroups: [
            {
                id: "HOLDING_TIME",
                labelEn: "Holding Time",
                labelJa: "保有時間",
                parameters: ["minimumHoldMs", "maximumHoldMs"],
            },
            {
                id: "EXIT_DETERIORATION",
                labelEn: "Exit Deterioration",
                labelJa: "悪化決済",
                parameters: [
                    "exitMomentumMinimum",
                    "exitLiquidityQualityMinimum",
                    "exitSpreadQualityMinimum",
                ],
            },
        ],
    },
    {
        id: "DETECTOR",
        labelEn: "Detector / Calibration",
        labelJa: "検出 / キャリブレーション",
        description: {
            en: "Parameters that tune upstream detectors and references feeding the strategy gates.",
            ja: "戦略ゲートに供給される上流の検出器・基準を調整するパラメーターです。",
        },
        parameters: [
            "absorptionVolumePercentile",
            "liquidityQualityPercentile",
        ],
    },
]);

export const IMPACT_TYPES = Object.freeze({
    DIRECT_GATE: "DIRECT_GATE",
    DOWNSTREAM_GATE: "DOWNSTREAM_GATE",
    DIRECT_EXIT: "DIRECT_EXIT",
    TIMING: "TIMING",
    DETECTOR: "DETECTOR",
    DEPENDENT: "DEPENDENT",
    BACKSTOP: "BACKSTOP",
});

export const IMPACT_TYPE_LABELS = Object.freeze({
    [IMPACT_TYPES.DIRECT_GATE]: { en: "DIRECT GATE", ja: "直接ゲート" },
    [IMPACT_TYPES.DOWNSTREAM_GATE]: { en: "DOWNSTREAM GATE", ja: "下流ゲート" },
    [IMPACT_TYPES.DIRECT_EXIT]: { en: "DIRECT EXIT", ja: "直接決済" },
    [IMPACT_TYPES.TIMING]: { en: "TIMING", ja: "タイミング" },
    [IMPACT_TYPES.DETECTOR]: { en: "DETECTOR", ja: "検出" },
    [IMPACT_TYPES.DEPENDENT]: { en: "DEPENDENT", ja: "依存" },
    [IMPACT_TYPES.BACKSTOP]: { en: "BACKSTOP", ja: "最終時間制限" },
});

export const IMPACT_CLASSES = Object.freeze({
    VERY_HIGH: "VERY_HIGH",
    HIGH: "HIGH",
    MEDIUM: "MEDIUM",
    LOW: "LOW",
});

export const IMPACT_CLASS_LABELS = Object.freeze({
    [IMPACT_CLASSES.VERY_HIGH]: { en: "VERY HIGH", ja: "非常に高い" },
    [IMPACT_CLASSES.HIGH]: { en: "HIGH", ja: "高い" },
    [IMPACT_CLASSES.MEDIUM]: { en: "MEDIUM", ja: "中程度" },
    [IMPACT_CLASSES.LOW]: { en: "LOW", ja: "低い" },
});

export const IMPACT_LEGEND = Object.freeze({
    en: "Impact describes how directly and broadly a parameter can change strategy behaviour. High impact does not mean good; low impact does not mean useless.",
    ja: "影響度は、そのパラメーターが戦略挙動をどれだけ直接的・広範囲に変え得るかを示します。影響度が高い＝良い、低い＝不要、という意味ではありません。",
});

/* Per-parameter presentation metadata, keyed by canonical name. */
export const PARAMETER_PRESENTATION = Object.freeze({
    minimumCompositeScore: {
        group: "ENTRY",
        impactType: IMPACT_TYPES.DIRECT_GATE,
        impactClass: IMPACT_CLASSES.VERY_HIGH,
        directionHint: {
            en: "↑ stricter Entry / ↓ looser Entry",
            ja: "↑ エントリーを厳しく / ↓ エントリーを緩く",
        },
    },
    maximumStrategySpreadPct: {
        group: "ENTRY",
        impactType: IMPACT_TYPES.DIRECT_GATE,
        impactClass: IMPACT_CLASSES.VERY_HIGH,
        directionHint: {
            en: "↑ wider spread accepted / ↓ narrower spread accepted",
            ja: "↑ 許容スプレッドを広く / ↓ 許容スプレッドを狭く",
        },
    },
    minimumStrategyConfidence: {
        group: "ENTRY",
        impactType: IMPACT_TYPES.DOWNSTREAM_GATE,
        impactClass: IMPACT_CLASSES.HIGH,
        directionHint: {
            en: "↑ stricter Entry / ↓ looser Entry (applied downstream)",
            ja: "↑ エントリーを厳しく / ↓ エントリーを緩く（下流で適用）",
        },
    },
    momentumWindowSeconds: {
        group: "MOMENTUM",
        impactType: IMPACT_TYPES.TIMING,
        impactClass: IMPACT_CLASSES.HIGH,
        directionHint: {
            en: "↑ smoother / slower momentum / ↓ more reactive / noisier",
            ja: "↑ なめらか・低速 / ↓ 反応は速く・ノイズ増",
        },
    },
    momentumMinimumWarmupSeconds: {
        group: "MOMENTUM",
        impactType: IMPACT_TYPES.DEPENDENT,
        impactClass: IMPACT_CLASSES.LOW,
        directionHint: {
            en: "↑ usable later / ↓ usable sooner",
            ja: "↑ 利用可能が遅く / ↓ 利用可能が早く",
        },
    },
    minimumHoldMs: {
        group: "EXIT",
        subgroup: "HOLDING_TIME",
        impactType: IMPACT_TYPES.DIRECT_EXIT,
        impactClass: IMPACT_CLASSES.HIGH,
        directionHint: {
            en: "↑ soft exits later / ↓ soft exits earlier",
            ja: "↑ ソフト決済を遅く / ↓ ソフト決済を早く",
        },
    },
    maximumHoldMs: {
        group: "EXIT",
        subgroup: "HOLDING_TIME",
        impactType: IMPACT_TYPES.BACKSTOP,
        impactClass: IMPACT_CLASSES.HIGH,
        directionHint: {
            en: "↑ longer hold / ↓ shorter hold",
            ja: "↑ 保有を長く / ↓ 保有を短く",
        },
    },
    exitMomentumMinimum: {
        group: "EXIT",
        subgroup: "EXIT_DETERIORATION",
        impactType: IMPACT_TYPES.DIRECT_EXIT,
        impactClass: IMPACT_CLASSES.MEDIUM,
        directionHint: {
            en: "↑ earlier momentum-decay exit / ↓ later",
            ja: "↑ モメンタム減衰で決済しやすく / ↓ しにくく",
        },
    },
    exitLiquidityQualityMinimum: {
        group: "EXIT",
        subgroup: "EXIT_DETERIORATION",
        impactType: IMPACT_TYPES.DIRECT_EXIT,
        impactClass: IMPACT_CLASSES.MEDIUM,
        directionHint: {
            en: "↑ earlier liquidity exit / ↓ later",
            ja: "↑ 流動性悪化で決済しやすく / ↓ しにくく",
        },
    },
    exitSpreadQualityMinimum: {
        group: "EXIT",
        subgroup: "EXIT_DETERIORATION",
        impactType: IMPACT_TYPES.DIRECT_EXIT,
        impactClass: IMPACT_CLASSES.MEDIUM,
        directionHint: {
            en: "↑ earlier spread exit / ↓ later",
            ja: "↑ スプレッド悪化で決済しやすく / ↓ しにくく",
        },
    },
    absorptionVolumePercentile: {
        group: "DETECTOR",
        impactType: IMPACT_TYPES.DETECTOR,
        impactClass: IMPACT_CLASSES.HIGH,
        directionHint: {
            en: "↑ stricter abnormal-depth detection / ↓ looser",
            ja: "↑ 異常板厚の検出を厳しく / ↓ 緩く",
        },
    },
    liquidityQualityPercentile: {
        group: "DETECTOR",
        impactType: IMPACT_TYPES.DETECTOR,
        impactClass: IMPACT_CLASSES.MEDIUM,
        directionHint: {
            en: "↑ stricter liquidity reference / ↓ looser",
            ja: "↑ 流動性基準を厳しく / ↓ 緩く",
        },
    },
});

export const presentationFor = (name) => PARAMETER_PRESENTATION[name] ?? null;

export const groupFor = (name) => presentationFor(name)?.group ?? null;

/* -----------------------------------------------------------------
   PARAMETER MAP — code-grounded flow, bilingual.
   Each step may carry parameter chips (canonical names).
----------------------------------------------------------------- */
export const PARAMETER_MAP_FLOW = Object.freeze([
    {
        id: "OBSERVATION",
        labelEn: "Market Observation",
        labelJa: "市場観測",
        note: {
            en: "Raw price, volume, spread and pressure from the market feed.",
            ja: "市場フィードからの生の価格・出来高・スプレッド・プレッシャー。",
        },
        chips: [],
    },
    {
        id: "DETECTOR",
        labelEn: "Detector / Feature",
        labelJa: "検出 / 特徴量",
        note: {
            en: "Rolling volume percentiles, normalized spread/liquidity quality and time-normalized momentum are computed here (indirect influence).",
            ja: "ローリング出来高パーセンタイル、正規化スプレッド／流動性品質、時間正規化モメンタムがここで計算されます（間接的な影響）。",
        },
        chips: [
            "absorptionVolumePercentile",
            "liquidityQualityPercentile",
            "momentumWindowSeconds",
            "momentumMinimumWarmupSeconds",
        ],
    },
    {
        id: "ENTRY",
        labelEn: "Entry Decision (AND gates)",
        labelJa: "エントリー判定（AND ゲート）",
        note: {
            en: "All hard gates must pass: spread safety, liquidity safety, momentum warmup, direction consistency and composite score. Failing any one blocks the entry.",
            ja: "すべてのハードゲートを通過する必要があります：スプレッド安全・流動性安全・モメンタム暖機・方向一致・総合スコア。1つでも失敗するとエントリーは阻止されます。",
        },
        chips: [
            "maximumStrategySpreadPct",
            "minimumCompositeScore",
        ],
    },
    {
        id: "CONFIDENCE",
        labelEn: "Downstream Confidence",
        labelJa: "下流 Confidence",
        note: {
            en: "After the strategy gates, the execution path applies a confidence floor (LOW_CONFIDENCE). Confidence is derived from edgeScore and momentum, so it is downstream of the composite gate.",
            ja: "戦略ゲートの後、実行経路が confidence の下限を適用します（LOW_CONFIDENCE）。confidence は edgeScore と momentum から派生するため、総合スコアゲートの下流に位置します。",
        },
        chips: ["minimumStrategyConfidence"],
    },
    {
        id: "POSITION",
        labelEn: "Position",
        labelJa: "ポジション",
        note: {
            en: "When a position opens, the parameter authority is captured for that position (snapshot-at-entry).",
            ja: "ポジションが建つと、そのポジション用にパラメーター権限が記録されます（snapshot-at-entry）。",
        },
        chips: [],
    },
    {
        id: "EXIT_MONITORING",
        labelEn: "Exit Monitoring",
        labelJa: "決済監視",
        note: {
            en: "Per price tick: SL, TP and trailing are checked first (outside Work E). Then the strategy evaluates reversal, liquidity deterioration, spread deterioration, momentum decay (after minimum hold) and MAX_HOLD (after maximum hold).",
            ja: "価格ティックごとに、まず SL・TP・トレーリングを判定します（Work E の範囲外）。その後、戦略が反転 → 流動性悪化 → スプレッド悪化 → モメンタム減衰（最低保有時間後）→ MAX_HOLD（最大保有時間後）を判定します。",
        },
        chips: [
            "minimumHoldMs",
            "exitMomentumMinimum",
            "exitLiquidityQualityMinimum",
            "exitSpreadQualityMinimum",
            "maximumHoldMs",
        ],
    },
    {
        id: "CLOSE",
        labelEn: "Exit / Close",
        labelJa: "決済 / クローズ",
        note: {
            en: "Exactly one close may commit per position. SL/TP/trailing, emergency flatten and manual close are separate authority.",
            ja: "1ポジションにつき1回だけクローズが確定します。SL/TP/トレーリング・緊急フラット・手動クローズは別系統の権限です。",
        },
        chips: [],
    },
]);

export const PARAMETER_MAP_NOTES = Object.freeze([
    {
        id: "direct_indirect",
        labelEn: "Direct vs indirect",
        labelJa: "直接 / 間接",
        en: "Direct controls (gates and exit thresholds) act on the decision every cycle or while positioned. Indirect controls (detector percentiles, momentum horizon) shape the features that feed those gates.",
        ja: "直接制御（ゲートと決済しきい値）は、毎サイクルまたは保有中に判定へ作用します。間接制御（検出器パーセンタイル・モメンタム期間）は、ゲートに供給される特徴量を形作ります。",
    },
    {
        id: "detector_path",
        labelEn: "Detector path",
        labelJa: "検出器の経路",
        en: "absorptionVolumePercentile and liquidityQualityPercentile are rolling quantile ranks (0.90 = 90th percentile, not 90%). They feed the liquidity-safety gate and a 0.20 edge weight — they are not the final entry comparison.",
        ja: "absorptionVolumePercentile と liquidityQualityPercentile はローリング分位（0.90 = 90パーセンタイル、90% ではありません）です。流動性安全ゲートと edge の 0.20 の重みに供給され、最終的なエントリー比較そのものではありません。",
    },
    {
        id: "entry_gates",
        labelEn: "Entry gates are AND conditions",
        labelJa: "エントリーゲートは AND 条件",
        en: "Every hard gate must pass. The evaluation order only decides which reason is reported first; a change to one gate can be invisible while a different gate fails.",
        ja: "すべてのハードゲートを通過する必要があります。評価順はどの理由が最初に報告されるかを決めるだけです。別のゲートが失敗している間は、あるゲートの変更が見えなくなることがあります。",
    },
    {
        id: "confidence",
        labelEn: "Composite vs confidence",
        labelJa: "総合スコアと Confidence",
        en: "confidence = edgeScore * (0.5 + momentum * 0.5), so confidence <= edgeScore. It is not identical to the composite gate and is applied downstream.",
        ja: "confidence = edgeScore * (0.5 + momentum * 0.5) であり、confidence <= edgeScore です。総合スコアゲートとは同一ではなく、下流で適用されます。",
    },
    {
        id: "min_hold",
        labelEn: "Minimum hold dependencies",
        labelJa: "最低保有時間の依存関係",
        en: "Momentum decay only runs after minimumHoldMs. Before it, liquidity/spread exits require two consecutive confirmations. Reversal and SL/TP/emergency/manual closes bypass it.",
        ja: "モメンタム減衰は minimumHoldMs 経過後のみ実行されます。それ以前の流動性・スプレッド決済は2回の連続確認が必要です。反転および SL/TP/緊急・手動クローズは制限を受けません。",
    },
    {
        id: "max_hold",
        labelEn: "Maximum hold backstop",
        labelJa: "最大保有時間のバックストップ",
        en: "maximumHoldMs is the last resort in the strategy exit order; any earlier strategy or safety exit may occur first.",
        ja: "maximumHoldMs は戦略決済順の最後の手段です。それより早い戦略決済や安全決済が先に発生し得ます。",
    },
    {
        id: "spread",
        labelEn: "Entry spread vs exit spread",
        labelJa: "エントリーのスプレッドと決済のスプレッド",
        en: "maximumStrategySpreadPct is an entry percent limit (and feeds the formal spread-safety exit). exitSpreadQualityMinimum is a separate normalized quality floor. They are not interchangeable.",
        ja: "maximumStrategySpreadPct はエントリーのパーセント上限です（正式なスプレッド安全決済にも使われます）。exitSpreadQualityMinimum は別の正規化品質下限です。互換ではありません。",
    },
    {
        id: "snapshot",
        labelEn: "snapshot-at-entry",
        labelJa: "エントリー時スナップショット",
        en: "Exit thresholds (minimum hold, maximum hold, exit momentum/liquidity/spread) are read from the entry snapshot. Entry gates and feature/detector parameters are evaluated each runtime cycle. The formal spread-safety exit reads the current authority.",
        ja: "決済しきい値（最低保有・最大保有・決済モメンタム／流動性／スプレッド）はエントリー時スナップショットから読み取られます。エントリーゲートと特徴量・検出器パラメーターは毎サイクル評価されます。正式なスプレッド安全決済は現在の権限を参照します。",
    },
    {
        id: "cer",
        labelEn: "Configured / Effective / Runtime",
        labelJa: "Configured / Effective / Runtime",
        en: "Configured = editable operator value. Effective = promoted canonical value. Runtime = the actual snapshot captured at entry; never fabricated from Configured.",
        ja: "Configured = 操作者が編集する値。Effective = 昇格済みの canonical 値。Runtime = エントリー時に取得された実スナップショット。Configured から捏造されることはありません。",
    },
    {
        id: "scopes",
        labelEn: "PAPER vs LIVE authority",
        labelJa: "PAPER と LIVE の権限差",
        en: "PAPER uses the normalized contract (TIME_SYMBOL_NORMALIZED_V1). LIVE keeps the legacy contract and exposes only proven-equivalent parameters; maximumStrategySpreadPct is legacy raw and the detector/momentum fallbacks have no active LIVE equivalent.",
        ja: "PAPER は正規化契約（TIME_SYMBOL_NORMALIZED_V1）を使用します。LIVE は旧来の契約を維持し、等価性が確認されたパラメーターのみを公開します。maximumStrategySpreadPct は legacy raw で、検出器・モメンタムのフォールバックは LIVE に対応する実体がありません。",
    },
]);

export const PARAMETER_MAP_OUTSIDE = Object.freeze([
    { en: "Stop Loss (SL) / Take Profit (TP) — ExecutionEngine config", ja: "損切り（SL）／利確（TP）— ExecutionEngine 設定" },
    { en: "Trailing stop — ExecutionEngine config", ja: "トレーリングストップ — ExecutionEngine 設定" },
    { en: "Governance safety authority", ja: "Governance の安全権限" },
    { en: "Execution safety / order mechanics", ja: "Execution の安全・注文機構" },
    { en: "Emergency close / flatten", ja: "緊急クローズ / フラット" },
    { en: "Manual close (Work D)", ja: "手動クローズ（Work D）" },
    { en: "Money Management risk / sizing", ja: "Money Management のリスク・サイズ" },
    { en: "Market Selection symbol", ja: "Market Selection の銘柄" },
    { en: "LIVE activation / realOrderAllowed (Work AA)", ja: "LIVE 有効化 / realOrderAllowed（Work AA）" },
]);

/* -----------------------------------------------------------------
   HOW TO TUNE — the 10 audit-defined goals, bilingual.
----------------------------------------------------------------- */
export const TUNING_GOALS = Object.freeze([
    {
        id: "A",
        titleEn: "Reduce weak / low-quality Entries",
        titleJa: "弱いエントリーを減らす",
        whenEn: "When too many marginal candidates pass the gates.",
        whenJa: "境界的な候補が多く通過しすぎるとき。",
        primary: ["minimumCompositeScore", "minimumStrategyConfidence", "maximumStrategySpreadPct"],
        secondary: ["absorptionVolumePercentile", "liquidityQualityPercentile"],
        directEffect: {
            en: "The entry gates become stricter (composite, confidence, spread, liquidity).",
            ja: "エントリーゲート（総合スコア・信頼度・スプレッド・流動性）が厳しくなります。",
        },
        possibleConsequence: {
            en: "Fewer candidates may pass; actual entries also depend on the other ANDed gates.",
            ja: "通過する候補は減る可能性があります。実際のエントリーは他の AND ゲートにも依存します。",
        },
        watchOut: {
            en: "Do not assume improved profitability; over-tightening can stop entries.",
            ja: "収益改善を前提にしないでください。厳しくしすぎるとエントリーが停止し得ます。",
        },
    },
    {
        id: "B",
        titleEn: "Allow more Entries",
        titleJa: "エントリー機会を増やす",
        whenEn: "When entries are too rare.",
        whenJa: "エントリーが少なすぎるとき。",
        primary: ["minimumCompositeScore", "minimumStrategyConfidence", "maximumStrategySpreadPct"],
        secondary: ["absorptionVolumePercentile", "liquidityQualityPercentile", "momentumMinimumWarmupSeconds"],
        directEffect: {
            en: "The gates become looser.",
            ja: "ゲートが緩くなります。",
        },
        possibleConsequence: {
            en: "More candidates may pass; other gates and market state still apply.",
            ja: "通過する候補は増える可能性があります。他のゲートや市場状態にも依存します。",
        },
        watchOut: {
            en: "Looser gates may admit lower-quality candidates.",
            ja: "緩めると質の低い候補が入る可能性があります。",
        },
    },
    {
        id: "C",
        titleEn: "React faster to short-term momentum",
        titleJa: "短期 Momentum への反応を速くする",
        whenEn: "When momentum reactions feel too slow.",
        whenJa: "モメンタムの反応が遅すぎると感じるとき。",
        primary: ["momentumWindowSeconds"],
        secondary: [],
        directEffect: {
            en: "The retained momentum sample span becomes shorter.",
            ja: "モメンタムの保持サンプル幅が短くなります。",
        },
        possibleConsequence: {
            en: "Direction alignment, edge, reversal and decay respond faster but noisier.",
            ja: "方向一致・edge・反転・減衰は速く反応しますが、ノイズが増えます。",
        },
        watchOut: {
            en: "Warmup must stay <= window; noise can increase false reversals.",
            ja: "warmup は window 以下である必要があります。ノイズにより誤った反転が増え得ます。",
        },
    },
    {
        id: "D",
        titleEn: "Smooth / stabilize momentum observation",
        titleJa: "Momentum 観測を安定化する",
        whenEn: "When momentum appears noisy.",
        whenJa: "モメンタムがノイジーに見えるとき。",
        primary: ["momentumWindowSeconds"],
        secondary: [],
        directEffect: {
            en: "The retained momentum sample span becomes longer.",
            ja: "モメンタムの保持サンプル幅が長くなります。",
        },
        possibleConsequence: {
            en: "Momentum becomes smoother but slower; entry/exit momentum effects lag.",
            ja: "モメンタムは安定しますが遅くなり、エントリー・決済のモメンタム影響が遅れます。",
        },
        watchOut: {
            en: "Keep warmup <= window; reaction becomes slower.",
            ja: "warmup ≤ window を維持してください。反応は遅くなります。",
        },
    },
    {
        id: "E",
        titleEn: "Exit deteriorating trades earlier",
        titleJa: "悪化したトレードから早く Exit する",
        whenEn: "When deteriorating positions are held too long.",
        whenJa: "悪化したポジションが長く保有されすぎるとき。",
        primary: ["exitMomentumMinimum", "exitLiquidityQualityMinimum", "exitSpreadQualityMinimum"],
        secondary: ["minimumHoldMs"],
        directEffect: {
            en: "The exit thresholds trigger more readily; a lower minimum hold lets soft exits fire sooner.",
            ja: "決済しきい値が発動しやすくなり、最低保有時間を下げるとソフト決済が早く発動できます。",
        },
        possibleConsequence: {
            en: "Positions close earlier on deterioration.",
            ja: "悪化時にポジションが早く決済される可能性があります。",
        },
        watchOut: {
            en: "Momentum decay is gated by minimumHoldMs; pre-hold liquidity/spread need 2 confirmations; SL/TP are unaffected.",
            ja: "momentum decay は minimumHoldMs に制限されます。保有時間前の流動性・スプレッドは2回の確認が必要です。SL/TP は対象外です。",
        },
    },
    {
        id: "F",
        titleEn: "Allow trades more time before soft Exit",
        titleJa: "早すぎる Soft Exit を抑える",
        whenEn: "When soft exits fire too early.",
        whenJa: "ソフト決済が早すぎるとき。",
        primary: ["minimumHoldMs"],
        secondary: [],
        directEffect: {
            en: "Soft exits wait longer; momentum decay runs later and pre-hold exits need confirmations.",
            ja: "ソフト決済がより長く待機します。momentum decay は遅く実行され、保有時間前の決済は確認が必要です。",
        },
        possibleConsequence: {
            en: "Positions may be held through short adverse noise.",
            ja: "短期的な不利ノイズの間もポジションが保有され得ます。",
        },
        watchOut: {
            en: "Reversal, SL, TP, emergency and manual closes are not gated.",
            ja: "反転・SL・TP・緊急・手動クローズは制限されません。",
        },
    },
    {
        id: "G",
        titleEn: "Shorten maximum holding duration",
        titleJa: "最大保有時間を短くする",
        whenEn: "When positions are held longer than desired by time.",
        whenJa: "時間的にポジションが長く保有されすぎるとき。",
        primary: ["maximumHoldMs"],
        secondary: [],
        directEffect: {
            en: "MAX_HOLD is reached sooner.",
            ja: "MAX_HOLD に早く到達します。",
        },
        possibleConsequence: {
            en: "Time-based force close happens earlier.",
            ja: "時間による強制決済が早まります。",
        },
        watchOut: {
            en: "Must stay strictly greater than minimumHoldMs.",
            ja: "minimumHoldMs より厳密に大きい必要があります。",
        },
    },
    {
        id: "H",
        titleEn: "Make liquidity deterioration Exit more sensitive",
        titleJa: "Liquidity 悪化への Exit 感度を上げる",
        whenEn: "When weak liquidity should trigger exits sooner.",
        whenJa: "流動性の弱まりでより早く決済したいとき。",
        primary: ["exitLiquidityQualityMinimum"],
        secondary: ["liquidityQualityPercentile"],
        directEffect: {
            en: "The liquidity-quality exit comparison triggers more readily.",
            ja: "流動性品質の決済比較が発動しやすくなります。",
        },
        possibleConsequence: {
            en: "Liquidity-driven exits may occur earlier.",
            ja: "流動性起因の決済が早まる可能性があります。",
        },
        watchOut: {
            en: "Formal liquidity safety can exit independently; pre-hold requires confirmations.",
            ja: "正式な流動性安全判定は独立して決済し得ます。保有時間前は確認が必要です。",
        },
    },
    {
        id: "I",
        titleEn: "Make spread deterioration Exit more sensitive",
        titleJa: "Spread 悪化への Exit 感度を上げる",
        whenEn: "When widening spreads should trigger exits sooner.",
        whenJa: "スプレッド拡大でより早く決済したいとき。",
        primary: ["exitSpreadQualityMinimum"],
        secondary: [],
        directEffect: {
            en: "The spread-divergence exit triggers more readily.",
            ja: "spread-divergence 決済が発動しやすくなります。",
        },
        possibleConsequence: {
            en: "Spread-driven exits may occur earlier.",
            ja: "スプレッド起因の決済が早まる可能性があります。",
        },
        watchOut: {
            en: "The formal spread-safety component uses maximumStrategySpreadPct (current authority); the entry spread gate is separate.",
            ja: "正式なスプレッド安全判定は maximumStrategySpreadPct（現在の権限）を使用します。エントリーのスプレッドゲートとは別です。",
        },
    },
    {
        id: "J",
        titleEn: "Change detector selectivity",
        titleJa: "Detector 選別感度を変更する",
        whenEn: "When abnormal-depth or liquidity-quality detection should be stricter or looser.",
        whenJa: "異常板厚や流動性品質の検出を厳しく／緩くしたいとき。",
        primary: ["absorptionVolumePercentile", "liquidityQualityPercentile"],
        secondary: [],
        directEffect: {
            en: "Rolling percentile thresholds/references change.",
            ja: "ローリングパーセンタイルのしきい値・基準が変化します。",
        },
        possibleConsequence: {
            en: "Absorption flags and liquidity quality change, affecting the liquidity gate, edge and liquidity exit.",
            ja: "吸収フラグや流動性品質が変化し、流動性ゲート・edge・流動性決済に影響します。",
        },
        watchOut: {
            en: "These are quantile ranks (0.90 = 90th percentile), not percentages; calibration warmup applies.",
            ja: "これらは分位（0.90 = 90パーセンタイル）であり、パーセントではありません。キャリブレーションの暖機が適用されます。",
        },
    },
]);
