import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
    CYCLE_STAGES,
    GUIDE_BILINGUAL_FIELDS,
    GUIDE_PARAMETER_KEYS,
    LIVE_MIGRATION,
    PARAMETER_GUIDE,
} from "../features/parameter-settings/parameterGuide.js";

const directory = dirname(fileURLToPath(import.meta.url));
const moduleUrl = (source) =>
    `data:text/javascript,${encodeURIComponent(source)}`;

const textOf = (node) => {
    if (node == null || typeof node === "boolean") return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    if (typeof node.type === "function") return textOf(node.type(node.props));
    return textOf(node.props?.children);
};

const findByTestId = (node, testId) => {
    if (node == null || typeof node !== "object") return null;
    if (Array.isArray(node)) {
        for (const child of node) {
            const found = findByTestId(child, testId);
            if (found) return found;
        }
        return null;
    }
    if (node.props?.["data-testid"] === testId) return node;
    if (typeof node.type === "function") {
        return findByTestId(node.type(node.props), testId);
    }
    return findByTestId(node.props?.children, testId);
};

const collectTestIds = (node, ids = []) => {
    if (node == null || typeof node !== "object") return ids;
    if (Array.isArray(node)) {
        for (const child of node) collectTestIds(child, ids);
        return ids;
    }
    const id = node.props?.["data-testid"];
    if (id) ids.push(id);
    if (typeof node.type === "function") {
        collectTestIds(node.type(node.props), ids);
        return ids;
    }
    collectTestIds(node.props?.children, ids);
    return ids;
};

const loadPage = async () => {
    let transformWithOxc;
    try {
        ({ transformWithOxc } = await import("vite"));
    } catch {
        return null;
    }
    const source = new URL("./ParameterSettingsPage.jsx", import.meta.url);
    const transformed = await transformWithOxc(
        await readFile(source, "utf8"),
        fileURLToPath(source),
    );
    const modelFile = join(
        directory,
        "..",
        "features",
        "parameter-settings",
        "parameterSettingsModel.js",
    );
    const guideFile = join(
        directory,
        "..",
        "features",
        "parameter-settings",
        "parameterGuide.js",
    );
    const presentationFile = join(
        directory,
        "..",
        "features",
        "parameter-settings",
        "parameterPresentation.js",
    );
    const featureStub = moduleUrl(
        `export * from "${pathToFileURL(modelFile).href}";`
        + `export * from "${pathToFileURL(guideFile).href}";`
        + `export * from "${pathToFileURL(presentationFile).href}";`
        + "export const useParameterSettings=()=>({});",
    );
    const pollingStub = moduleUrl(
        "export default ()=>({data:null,loading:false,error:false});",
    );
    const accountStub = moduleUrl(
        "export const fetchBotStatus=async()=>({data:{},receivedAt:0});",
    );
    const code = transformed.code
        .replace(
            'from "../features/parameter-settings";',
            `from "${featureStub}";`,
        )
        .replace('from "../hooks/usePolling";', `from "${pollingStub}";`)
        .replace(
            'from "../components/runtime/accountRuntimeModel";',
            `from "${accountStub}";`,
        );
    const temporary = await mkdtemp(join(directory, ".ps-page-test-"));
    const output = join(temporary, "ParameterSettingsPage.mjs");
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?render`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

const schema = {
    parameters: [
        { name: "minimumCompositeScore", labelEn: "Composite Entry Score", labelJa: "総合エントリースコア", unit: "normalized score (0.0-1.0)", minimum: 0, maximum: 1, minimumInclusive: true, maximumInclusive: true, precision: 6, valueType: "float", tier: "PRIMARY", editable: true, description: "entry score" },
        { name: "maximumStrategySpreadPct", labelEn: "Maximum Strategy Spread", labelJa: "最大スプレッド", unit: "percent (0-100 scale)", minimum: 0, maximum: 5, minimumInclusive: false, maximumInclusive: true, precision: 6, valueType: "float", tier: "PRIMARY", editable: true, description: "spread" },
        { name: "momentumWindowSeconds", labelEn: "Momentum Window", labelJa: "モメンタム窓", unit: "seconds", minimum: 5, maximum: 600, minimumInclusive: true, maximumInclusive: true, precision: 6, valueType: "float", tier: "PRIMARY", editable: true, description: "momentum" },
        { name: "minimumStrategyConfidence", labelEn: "Minimum Confidence", labelJa: "最小信頼度", unit: "normalized score (0.0-1.0)", minimum: 0, maximum: 1, minimumInclusive: true, maximumInclusive: true, precision: 6, valueType: "float", tier: "PRIMARY", editable: true, description: "confidence" },
        { name: "maximumHoldMs", labelEn: "Maximum Hold", labelJa: "最大保有時間", unit: "milliseconds", minimum: 100, maximum: 60000, minimumInclusive: true, maximumInclusive: true, precision: 0, valueType: "int", tier: "PRIMARY", editable: true, description: "hold" },
        { name: "minimumHoldMs", labelEn: "Minimum Hold", labelJa: "最小保有時間", unit: "milliseconds", minimum: 0, maximum: 60000, minimumInclusive: true, maximumInclusive: true, precision: 0, valueType: "int", tier: "ADVANCED", editable: true, description: "min hold" },
        { name: "exitMomentumMinimum", labelEn: "Exit Momentum Minimum", labelJa: "決済モメンタム下限", unit: "normalized score (0.0-1.0)", minimum: 0, maximum: 1, minimumInclusive: true, maximumInclusive: true, precision: 6, valueType: "float", tier: "ADVANCED", editable: true, description: "exit momentum" },
        { name: "exitLiquidityQualityMinimum", labelEn: "Exit Liquidity Quality Minimum", labelJa: "決済流動性品質下限", unit: "normalized score (0.0-1.0)", minimum: 0, maximum: 1, minimumInclusive: true, maximumInclusive: true, precision: 6, valueType: "float", tier: "ADVANCED", editable: true, description: "exit liquidity" },
        { name: "exitSpreadQualityMinimum", labelEn: "Exit Spread Quality Minimum", labelJa: "決済スプレッド品質下限", unit: "normalized score (0.0-1.0)", minimum: 0, maximum: 1, minimumInclusive: true, maximumInclusive: true, precision: 6, valueType: "float", tier: "ADVANCED", editable: true, description: "exit spread" },
        { name: "momentumMinimumWarmupSeconds", labelEn: "Momentum Warmup", labelJa: "モメンタム暖機", unit: "seconds", minimum: 0, maximum: 600, minimumInclusive: true, maximumInclusive: true, precision: 6, valueType: "float", tier: "ADVANCED", editable: true, description: "warmup" },
        { name: "absorptionVolumePercentile", labelEn: "Absorption Volume Percentile", labelJa: "吸収出来高パーセンタイル", unit: "normalized percentile (0.0-1.0)", minimum: 0, maximum: 1, minimumInclusive: false, maximumInclusive: true, precision: 6, valueType: "float", tier: "ADVANCED", editable: true, description: "absorption" },
        { name: "liquidityQualityPercentile", labelEn: "Liquidity Quality Percentile", labelJa: "流動性品質パーセンタイル", unit: "normalized percentile (0.0-1.0)", minimum: 0, maximum: 1, minimumInclusive: false, maximumInclusive: true, precision: 6, valueType: "float", tier: "ADVANCED", editable: true, description: "liquidity" },
    ],
};

const configuration = {
    parameterSetId: "strategy-params/PAPER",
    scope: "PAPER",
    configuredRevision: 7,
    effectiveRevision: 5,
    status: "PENDING",
    source: "PARAMETER_SETTINGS",
    parameters: {
        minimumCompositeScore: 0.4,
        maximumStrategySpreadPct: 0.5,
        momentumWindowSeconds: 60,
        minimumStrategyConfidence: 0.3,
        maximumHoldMs: 3000,
        minimumHoldMs: 500,
        exitMomentumMinimum: 0.4,
        exitLiquidityQualityMinimum: 0.3,
        exitSpreadQualityMinimum: 0.3,
        momentumMinimumWarmupSeconds: 20,
        absorptionVolumePercentile: 0.9,
        liquidityQualityPercentile: 0.9,
    },
};

const effective = {
    effectiveRevision: 5,
    validation: { isValid: true, errors: [], warnings: [] },
    warnings: [],
    parameters: { ...configuration.parameters, minimumCompositeScore: 0.34 },
};

const runtime = {
    runtimeSnapshotAvailable: true,
    effectiveRevision: 4,
    featureContract: "TIME_SYMBOL_NORMALIZED_V1",
    capturedAt: "2026-01-01T00:00:00.000000Z",
    parameters: { minimumCompositeScore: 0.3 },
};

const baseProps = {
    scope: "PAPER",
    schema,
    configuration,
    effective,
    runtime,
    status: { status: "OK", scopes: { PAPER: { health: "OK" } } },
    botStatus: {
        symbol: "BTCUSDT",
        timeframe: "1m",
        mode: "paper",
        sl_percent: 1,
        tp_percent: 2,
        trailingStop: true,
    },
    draft: { ...configuration.parameters },
};

test("route and navigation register PARAMETER SETTINGS", async () => {
    const [app, navigation] = await Promise.all([
        readFile(new URL("../App.jsx", import.meta.url), "utf8"),
        readFile(
            new URL("../components/AppNavigation.jsx", import.meta.url),
            "utf8",
        ),
    ]);
    assert.match(app, /from "\.\/pages\/ParameterSettingsPage"/);
    assert.match(app, /PARAMETER_SETTINGS_PATH = "\/parameter-settings"/);
    assert.match(navigation, /PARAMETER SETTINGS/);
    assert.match(navigation, /PARAMETER_SETTINGS_PATH/);
    assert.match(navigation, /"\/parameter-settings"/);
});

test("view renders runtime context read-only and four functional groups", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView(baseProps);
    const text = textOf(tree);

    assert.match(text, /PARAMETER SETTINGS（パラメーター設定）/);
    assert.match(text, /Runtime Context/);
    assert.match(text, /READ ONLY/);
    assert.match(text, /BTCUSDT/);
    assert.match(text, /OFF \/ NOT_INSTALLED \/ NONE/);

    assert.equal(textOf(findByTestId(tree, "group-count-ENTRY")), "3");
    assert.equal(textOf(findByTestId(tree, "group-count-MOMENTUM")), "2");
    assert.equal(textOf(findByTestId(tree, "group-count-EXIT")), "5");
    assert.equal(textOf(findByTestId(tree, "group-count-DETECTOR")), "2");
    assert.ok(findByTestId(tree, "scope-PAPER"));
    assert.ok(findByTestId(tree, "scope-LIVE"));

    // Primary/Advanced are no longer the main organization.
    assert.equal(findByTestId(tree, "primary-parameters-section"), null);
    assert.equal(findByTestId(tree, "advanced-parameters-section"), null);

    // Configured / Effective / Runtime are distinguished.
    assert.match(text, /Configured/);
    assert.match(text, /Effective/);
    assert.match(text, /Runtime/);
    assert.match(text, /0\.50 %/);
    assert.match(text, /Configured revision/);
    assert.match(text, /Effective revision/);
    assert.match(text, /Runtime revision/);
    assert.match(text, /PENDING/);

    // No MM / Governance / Market Selection / Execution authority controls.
    assert.doesNotMatch(
        text,
        /Governance|Money Management|Market Selection|Auto Tune|Optimize|Profile/,
    );
});

const PRIMARY_NAMES = [
    "minimumCompositeScore",
    "maximumStrategySpreadPct",
    "momentumWindowSeconds",
    "minimumStrategyConfidence",
    "maximumHoldMs",
];

test("all twelve parameters render once as structured icon cards in groups", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView(baseProps);
    const ids = collectTestIds(tree);

    for (const name of ALL_NAMES) {
        assert.equal(
            ids.filter((id) => id === `parameter-row-${name}`).length,
            1,
            name,
        );
        assert.ok(ids.includes(`parameter-icon-${name}`), name);
    }
    assert.equal(
        ids.filter((id) => id.startsWith("parameter-row-")).length,
        12,
    );
    assert.equal(
        ids.filter((id) => id.startsWith("parameter-icon-")).length,
        12,
    );

    // Functional group order: ENTRY -> MOMENTUM -> EXIT -> DETECTOR.
    assert.ok(ids.indexOf("group-ENTRY") < ids.indexOf("group-MOMENTUM"));
    assert.ok(ids.indexOf("group-MOMENTUM") < ids.indexOf("group-EXIT"));
    assert.ok(ids.indexOf("group-EXIT") < ids.indexOf("group-DETECTOR"));

    // Runtime Context is below the editable parameters.
    assert.ok(ids.includes("runtime-context-section"));
    assert.ok(
        ids.indexOf("group-DETECTOR") < ids.indexOf("runtime-context-section"),
    );

    // Each card keeps Configured / Effective / Runtime distinct.
    for (const name of ALL_NAMES) {
        const card = textOf(findByTestId(tree, `parameter-row-${name}`));
        assert.match(card, /Configured/);
        assert.match(card, /Effective/);
        assert.match(card, /Runtime/);
    }
});

test("authority details are collapsed at the bottom with the moved explanations", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const collapsed = page.ParameterSettingsView(baseProps);
    assert.equal(findByTestId(collapsed, "authority-details-content"), null);
    assert.doesNotMatch(
        textOf(collapsed),
        /Scope selector changes which parameter configuration is viewed or edited/,
    );

    const expanded = page.ParameterSettingsView({
        ...baseProps,
        authorityExpanded: true,
    });
    const content = findByTestId(expanded, "authority-details-content");
    assert.ok(content);
    const text = textOf(content);
    assert.match(text, /does NOT change the running bot mode/);
    assert.match(text, /Snapshot-at-entry/);
    assert.match(text, /PENDING/);
});

test("runtime context and AI remain read-only", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView(baseProps);
    const runtimeText = textOf(findByTestId(tree, "runtime-context-section"));
    assert.match(runtimeText, /READ ONLY/);
    assert.match(runtimeText, /OFF \/ NOT_INSTALLED \/ NONE/);
    assert.match(runtimeText, /BTCUSDT/);
});

test("page exposes no apply-now or auto-optimization control", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView(baseProps);
    const text = textOf(tree);
    assert.doesNotMatch(
        text,
        /Apply Now|Auto Tune|Auto Apply|Best Parameters|Optimize/,
    );
});

test("functional groups have the audit-defined membership and exit subgroups", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView(baseProps);
    const ids = collectTestIds(tree);

    for (const [groupId, names] of Object.entries(GROUPS)) {
        assert.ok(ids.includes(`group-${groupId}`), groupId);
        assert.equal(
            textOf(findByTestId(tree, `group-count-${groupId}`)),
            String(names.length),
            groupId,
        );
        const groupIds = collectTestIds(findByTestId(tree, `group-${groupId}`));
        for (const name of names) {
            assert.ok(
                groupIds.includes(`parameter-row-${name}`),
                `${groupId}:${name}`,
            );
        }
    }

    assert.ok(ids.includes("subgroup-HOLDING_TIME"));
    assert.ok(ids.includes("subgroup-EXIT_DETERIORATION"));
    const holding = collectTestIds(findByTestId(tree, "subgroup-HOLDING_TIME"));
    assert.ok(holding.includes("parameter-row-minimumHoldMs"));
    assert.ok(holding.includes("parameter-row-maximumHoldMs"));
    const deterioration = collectTestIds(
        findByTestId(tree, "subgroup-EXIT_DETERIORATION"),
    );
    for (const name of [
        "exitMomentumMinimum",
        "exitLiquidityQualityMinimum",
        "exitSpreadQualityMinimum",
    ]) {
        assert.ok(deterioration.includes(`parameter-row-${name}`), name);
    }
});

test("impact and direction metadata use the audit presentation model", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView(baseProps);
    const ids = collectTestIds(tree);
    for (const name of ALL_NAMES) {
        assert.ok(ids.includes(`parameter-impact-${name}`), name);
        assert.ok(ids.includes(`parameter-direction-${name}`), name);
    }
    assert.match(
        textOf(findByTestId(tree, "parameter-impact-minimumCompositeScore")),
        /DIRECT GATE/,
    );
    assert.match(
        textOf(findByTestId(tree, "parameter-impact-minimumCompositeScore")),
        /直接ゲート/,
    );
    assert.match(
        textOf(findByTestId(tree, "parameter-impact-minimumCompositeScore")),
        /VERY HIGH/,
    );
    assert.match(
        textOf(findByTestId(tree, "parameter-impact-minimumStrategyConfidence")),
        /DOWNSTREAM GATE/,
    );
    assert.match(
        textOf(findByTestId(tree, "parameter-impact-maximumHoldMs")),
        /BACKSTOP/,
    );
    assert.match(
        textOf(findByTestId(tree, "parameter-impact-momentumMinimumWarmupSeconds")),
        /DEPENDENT/,
    );
    assert.match(
        textOf(findByTestId(tree, "parameter-impact-absorptionVolumePercentile")),
        /DETECTOR/,
    );
});

test("parameter map opens with bilingual flow, all 12 chips and outside authority", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView({ ...baseProps, mapOpen: true });
    assert.ok(findByTestId(tree, "map-modal"));
    const ids = collectTestIds(tree);
    for (const name of ALL_NAMES) {
        assert.ok(ids.includes(`map-chip-${name}`), name);
    }
    const mapText = textOf(findByTestId(tree, "map-modal"));
    assert.match(mapText, /Market Observation/);
    assert.match(mapText, /市場観測/);
    assert.match(mapText, /Entry Decision/);
    assert.match(mapText, /エントリー判定/);
    assert.match(mapText, /Not controlled here/);
    assert.match(mapText, /ここでは制御しないもの/);
    assert.match(mapText, /Stop Loss/);
    assert.match(mapText, /Trailing/);
    assert.match(mapText, /Configured/);
    assert.match(mapText, /snapshot-at-entry/);
});

test("how to tune exposes exactly ten bilingual goals without numeric recommendations", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView({ ...baseProps, tuneOpen: true });
    assert.ok(findByTestId(tree, "tune-modal"));
    const ids = collectTestIds(tree);
    assert.equal(
        ids.filter((id) => id.startsWith("tune-goal-")).length,
        10,
    );
    for (const id of ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]) {
        assert.ok(findByTestId(tree, `tune-goal-${id}`), id);
    }
    const tuneText = textOf(findByTestId(tree, "tune-modal"));
    assert.match(tuneText, /弱いエントリーを減らす/);
    assert.match(tuneText, /エントリー機会を増やす/);
    assert.match(tuneText, /Direct effect/);
    assert.match(tuneText, /直接影響/);
    assert.match(tuneText, /Possible consequence/);
    assert.match(tuneText, /起こり得る結果/);
    assert.doesNotMatch(
        tuneText,
        /win rate|guaranteed|best setting|optimal value/i,
    );
    assert.doesNotMatch(tuneText, /推奨値|最適な値/);
});

test("guide corrections reflect the audit snapshot and timing findings", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    assert.equal(PARAMETER_GUIDE.maximumStrategySpreadPct.snapshotAtEntry, false);
    assert.equal(PARAMETER_GUIDE.momentumWindowSeconds.snapshotAtEntry, false);
    assert.equal(PARAMETER_GUIDE.maximumHoldMs.snapshotAtEntry, true);
    assert.equal(PARAMETER_GUIDE.minimumHoldMs.snapshotAtEntry, true);
    assert.equal(PARAMETER_GUIDE.absorptionVolumePercentile.snapshotAtEntry, false);

    const guideSource = await readFile(
        new URL(
            "../features/parameter-settings/parameterGuide.js",
            import.meta.url,
        ),
        "utf8",
    );
    assert.match(guideSource, /CURRENT parameter authority/);
    assert.match(guideSource, /recomputed every feature\/strategy cycle/);
    assert.match(guideSource, /applied downstream by the execution path/);
    assert.match(guideSource, /last resort in the strategy exit order/);
    assert.match(guideSource, /detector -> feature -> gate/);
});

test("LIVE scope shows confirmation and locks unmigrated parameters", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const liveTree = page.ParameterSettingsView({
        ...baseProps,
        scope: "LIVE",
        liveConfirmationOpen: true,
    });
    const liveText = textOf(liveTree);
    assert.match(liveText, /CONFIRM LIVE SAVE/);
    assert.match(liveText, /LOCKED/);
    assert.match(liveText, /SAVE LIVE CONFIGURATION/);
    assert.ok(findByTestId(liveTree, "parameter-lock-maximumStrategySpreadPct"));
});

test("409 conflict and 422 validation are rendered", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const conflictTree = page.ParameterSettingsView({
        ...baseProps,
        conflict: { configuredRevision: 8 },
    });
    assert.match(textOf(conflictTree), /Stale revision \(8\)/);

    const invalidTree = page.ParameterSettingsView({
        ...baseProps,
        saveState: {
            phase: "INVALID",
            backend: { message: "configuration failed canonical validation" },
            fieldErrors: { minimumCompositeScore: "must be >= 0" },
        },
    });
    assert.match(
        textOf(invalidTree),
        /configuration failed canonical validation/,
    );
    assert.match(textOf(invalidTree), /must be >= 0/);
});

const ADVANCED_NAMES = [
    "minimumHoldMs",
    "exitMomentumMinimum",
    "exitLiquidityQualityMinimum",
    "exitSpreadQualityMinimum",
    "momentumMinimumWarmupSeconds",
    "absorptionVolumePercentile",
    "liquidityQualityPercentile",
];

const GROUPS = {
    ENTRY: [
        "minimumCompositeScore",
        "maximumStrategySpreadPct",
        "minimumStrategyConfidence",
    ],
    MOMENTUM: ["momentumWindowSeconds", "momentumMinimumWarmupSeconds"],
    EXIT: [
        "minimumHoldMs",
        "maximumHoldMs",
        "exitMomentumMinimum",
        "exitLiquidityQualityMinimum",
        "exitSpreadQualityMinimum",
    ],
    DETECTOR: ["absorptionVolumePercentile", "liquidityQualityPercentile"],
};

const ALL_NAMES = Object.values(GROUPS).flat();

test("guide definitions cover exactly the canonical twelve parameters", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    assert.equal(GUIDE_PARAMETER_KEYS.length, 12);
    assert.deepEqual(
        [...GUIDE_PARAMETER_KEYS].sort(),
        [...PRIMARY_NAMES, ...ADVANCED_NAMES].sort(),
    );

    const validMigrations = [
        LIVE_MIGRATION.EXACT,
        LIVE_MIGRATION.IMPERFECT_UNIT_MAPPING,
        LIVE_MIGRATION.NO_LEGACY_EQUIVALENT,
    ];
    for (const key of GUIDE_PARAMETER_KEYS) {
        const guide = PARAMETER_GUIDE[key];
        for (const field of ["labelEn", "labelJa"]) {
            assert.ok(
                typeof guide[field] === "string" && guide[field].length > 0,
                `${key}.${field}`,
            );
        }
        for (const field of GUIDE_BILINGUAL_FIELDS) {
            assert.ok(
                typeof guide[field]?.en === "string"
                && guide[field].en.length > 0,
                `${key}.${field}.en`,
            );
            assert.ok(
                typeof guide[field]?.ja === "string"
                && guide[field].ja.length > 0,
                `${key}.${field}.ja`,
            );
            assert.match(
                guide[field].ja,
                /[\u3040-\u30ff\u4e00-\u9fff]/u,
                `${key}.${field}.ja is not Japanese`,
            );
        }
        assert.ok(Array.isArray(guide.related), `${key}.related`);
        assert.ok(
            Array.isArray(guide.cycleStages) && guide.cycleStages.length > 0,
            `${key}.cycleStages`,
        );
        assert.ok(
            validMigrations.includes(guide.liveMigration),
            `${key}.liveMigration`,
        );
        const prose = [
            guide.controls.en,
            guide.valueMeaning.en,
            guide.increase.en,
            guide.decrease.en,
            guide.directEffect.en,
            guide.possibleTradingEffect.en,
        ].join(" ");
        assert.doesNotMatch(
            prose,
            /guarantee|increase profit|win rate|best value|optimize performance|recommend/i,
            `${key} performance claim`,
        );
        const proseJa = [
            guide.controls.ja,
            guide.valueMeaning.ja,
            guide.increase.ja,
            guide.decrease.ja,
            guide.directEffect.ja,
            guide.possibleTradingEffect.ja,
        ].join(" ");
        assert.doesNotMatch(
            proseJa,
            /勝率が上が|利益が増|最適な値|推奨値|必ず.*(損失|利益)|保証/,
            `${key} Japanese performance claim`,
        );
    }

    // Every canonical cycle stage used by a Guide is labelled bilingually.
    for (const key of GUIDE_PARAMETER_KEYS) {
        for (const stage of PARAMETER_GUIDE[key].cycleStages) {
            assert.ok(CYCLE_STAGES[stage], `${key} stage ${stage}`);
            assert.ok(CYCLE_STAGES[stage].en && CYCLE_STAGES[stage].ja);
        }
    }
});

test("guide definitions are bilingual for every explanatory field", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    assert.equal(GUIDE_PARAMETER_KEYS.length, 12);
    assert.equal(GUIDE_BILINGUAL_FIELDS.length, 8);

    for (const key of GUIDE_PARAMETER_KEYS) {
        const guide = PARAMETER_GUIDE[key];
        for (const field of GUIDE_BILINGUAL_FIELDS) {
            // Japanese must be a genuine translation, not a copy of English.
            assert.notEqual(
                guide[field].en,
                guide[field].ja,
                `${key}.${field} EN/JA identical`,
            );
        }
    }
});

test("a guide trigger exists for every one of the twelve parameters", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView(baseProps);
    const ids = collectTestIds(tree);
    for (const name of ALL_NAMES) {
        assert.ok(ids.includes(`parameter-guide-${name}`), name);
    }
    assert.equal(
        ids.filter((id) => id.startsWith("parameter-guide-")).length,
        12,
    );
});

test("guide trigger selects the correct parameter without writing", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const opened = [];
    let saved = 0;
    const tree = page.ParameterSettingsView({
        ...baseProps,
        onOpenGuide: (name) => opened.push(name),
        onSave: () => { saved += 1; },
    });
    for (const name of ALL_NAMES) {
        findByTestId(tree, `parameter-guide-${name}`).props.onClick({
            currentTarget: {},
        });
    }
    assert.deepEqual(opened, ALL_NAMES);
    assert.equal(saved, 0);
});

test("guide modal opens with dynamic current values and closes via X/backdrop", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const closed = [];
    const tree = page.ParameterSettingsView({
        ...baseProps,
        guideKey: "minimumCompositeScore",
        onCloseGuide: () => closed.push("close"),
    });
    assert.ok(findByTestId(tree, "guide-modal"));
    assert.match(
        textOf(findByTestId(tree, "guide-title")),
        /Composite Entry Score/,
    );
    const values = textOf(findByTestId(tree, "guide-current-values"));
    assert.match(values, /0\.40/);
    assert.match(values, /0\.34/);
    assert.match(values, /0\.30/);
    const modalText = textOf(findByTestId(tree, "guide-modal"));
    assert.match(modalText, /Direct effect/);
    assert.match(modalText, /Possible trading effect/);

    const exitTree = page.ParameterSettingsView({
        ...baseProps,
        guideKey: "maximumHoldMs",
    });
    assert.match(
        textOf(findByTestId(exitTree, "guide-modal")),
        /Snapshot-at-entry/,
    );

    findByTestId(tree, "guide-close").props.onClick();
    assert.equal(closed.length, 1);
    findByTestId(tree, "guide-backdrop").props.onClick();
    assert.equal(closed.length, 2);

    let stopped = 0;
    findByTestId(tree, "guide-modal").props.onClick({
        stopPropagation: () => { stopped += 1; },
    });
    assert.equal(stopped, 1);
});

test("guide modal values follow the scope and legacy raw display", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const paper = page.ParameterSettingsView({
        ...baseProps,
        guideKey: "maximumStrategySpreadPct",
    });
    assert.match(
        textOf(findByTestId(paper, "guide-configured")),
        /0\.50 %/,
    );

    const live = page.ParameterSettingsView({
        ...baseProps,
        scope: "LIVE",
        guideKey: "maximumStrategySpreadPct",
    });
    const liveConfigured = textOf(findByTestId(live, "guide-configured"));
    assert.doesNotMatch(liveConfigured, /%/);
    assert.match(liveConfigured, /0\.5/);
    assert.ok(findByTestId(live, "guide-legacy-note"));
    assert.match(
        textOf(findByTestId(live, "guide-legacy-en")),
        /legacy raw/i,
    );
    assert.match(
        textOf(findByTestId(live, "guide-legacy-ja")),
        /旧実装/,
    );
    assert.match(
        textOf(findByTestId(live, "guide-authority-en")),
        /locked/i,
    );
    assert.match(
        textOf(findByTestId(live, "guide-authority-ja")),
        /ロック/,
    );
});

test("percentile parameters are not shown with a percent suffix", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView({
        ...baseProps,
        advancedExpanded: true,
    });
    for (const name of [
        "absorptionVolumePercentile",
        "liquidityQualityPercentile",
    ]) {
        const text = textOf(findByTestId(tree, `parameter-row-${name}`));
        assert.match(text, /0\.90/);
        assert.doesNotMatch(text, /0\.90 %/);
    }
});

test("page source contains no order / bot / optimization authority", async () => {
    const source = await readFile(
        new URL("./ParameterSettingsPage.jsx", import.meta.url),
        "utf8",
    );
    assert.doesNotMatch(source, /bot\/start|bot\/stop|live-order-entry/);
    assert.doesNotMatch(source, /Optimize|Auto Tune|Auto Apply|Best Parameters/);
    assert.doesNotMatch(source, /money-management|governance|market-intelligence/);
});

test("page structure keeps inputs read-only when locked and includes the panels", async () => {
    const source = await readFile(
        new URL("./ParameterSettingsPage.jsx", import.meta.url),
        "utf8",
    );
    assert.match(source, /export function ParameterSettingsView/);
    assert.match(source, /mapOpen = false/);
    assert.match(source, /tuneOpen = false/);
    assert.match(source, /useState\(false\)/);
    assert.match(source, /readOnly=\{!editable\}/);
    assert.match(source, /disabled=\{!editable\}/);
    assert.match(source, /LOCKED — LIVE legacy/);
    assert.match(source, /READ ONLY/);
    assert.match(source, /ps-param-input/);
    assert.match(source, /account-runtime-overview/);
    assert.match(source, /authority-details-toggle/);
    assert.match(source, /ParameterGuideModal/);
    assert.match(source, /ParameterMapModal/);
    assert.match(source, /HowToTuneModal/);
    assert.match(source, /ps-guide-trigger/);
    assert.match(source, /guideKey = null/);
});

test("guide metadata module is static and never writes configuration", async () => {
    const guideSource = await readFile(
        new URL(
            "../features/parameter-settings/parameterGuide.js",
            import.meta.url,
        ),
        "utf8",
    );
    assert.doesNotMatch(
        guideSource,
        /fetch\(|updateParameterSettingsConfiguration|onSave|api\//,
    );
    assert.doesNotMatch(
        guideSource,
        /Optimize|Auto Tune|Auto Apply|Apply Now/,
    );

    const presentationSource = await readFile(
        new URL(
            "../features/parameter-settings/parameterPresentation.js",
            import.meta.url,
        ),
        "utf8",
    );
    assert.doesNotMatch(
        presentationSource,
        /fetch\(|updateParameterSettingsConfiguration|onSave|api\//,
    );
    assert.doesNotMatch(
        presentationSource,
        /Optimize|Auto Tune|Auto Apply|Apply Now/,
    );
});

test("guide typography is substantially enlarged in the stylesheet", async () => {
    const css = await readFile(
        new URL("../styles/parameter-settings.css", import.meta.url),
        "utf8",
    );
    // Body explanation uses a responsive clamp with a >=16px floor.
    assert.match(
        css,
        /\.ps-page \.ps-guide-text\s*\{[^}]*font-size:\s*clamp\(\s*1[6-9]px/s,
    );
    // Section headings and the modal title are enlarged too.
    assert.match(
        css,
        /\.ps-page \.ps-guide-section h3\s*\{[^}]*font-size:\s*clamp\(\s*1[6-9]px/s,
    );
    assert.match(
        css,
        /\.ps-page \.ps-guide-modal__header h2\s*\{[^}]*font-size:\s*clamp\(\s*2[2-9]px/s,
    );
    assert.match(
        css,
        /\.ps-page \.ps-guide-values strong\s*\{[^}]*font-size:\s*clamp\(\s*1[89]px/s,
    );
    // The previous tiny body rule must be gone.
    assert.doesNotMatch(css, /\.ps-page \.ps-guide-section p\s*\{/);
    // Bilingual text styling exists.
    assert.match(css, /\.ps-page \.ps-guide-lang\s*\{/);
    assert.match(css, /\.ps-page \.ps-guide-text--ja\s*\{/);
});
