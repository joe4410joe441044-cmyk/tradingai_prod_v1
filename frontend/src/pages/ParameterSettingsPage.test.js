import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

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
    const featureStub = moduleUrl(
        `export * from "${pathToFileURL(modelFile).href}";`
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

test("view renders runtime context read-only, primary=5, advanced=7 collapsed", async (context) => {
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

    assert.equal(
        textOf(findByTestId(tree, "primary-count")),
        "5",
    );
    assert.equal(
        textOf(findByTestId(tree, "advanced-count")),
        "7",
    );
    assert.ok(findByTestId(tree, "scope-PAPER"));
    assert.ok(findByTestId(tree, "scope-LIVE"));

    // Advanced is collapsed initially.
    assert.equal(findByTestId(tree, "advanced-parameters-content"), null);

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

test("advanced expands on demand", async (context) => {
    const page = await loadPage();
    if (!page) {
        context.skip("vite is not installed in this workspace");
        return;
    }
    const tree = page.ParameterSettingsView({
        ...baseProps,
        advancedExpanded: true,
    });
    assert.ok(findByTestId(tree, "advanced-parameters-content"));
    const text = textOf(tree);
    for (const group of [
        "Holding-Time",
        "Exit-Deterioration",
        "Momentum-Horizon",
        "Detector-Sensitivity",
    ]) {
        assert.match(text, new RegExp(group));
    }
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

test("page source contains no order / bot / optimization authority", async () => {
    const source = await readFile(
        new URL("./ParameterSettingsPage.jsx", import.meta.url),
        "utf8",
    );
    assert.doesNotMatch(source, /bot\/start|bot\/stop|live-order-entry/);
    assert.doesNotMatch(source, /Optimize|Auto Tune|Auto Apply|Best Parameters/);
    assert.doesNotMatch(source, /money-management|governance|market-intelligence/);
});

test("page structure keeps advanced collapsed and inputs read-only when locked", async () => {
    const source = await readFile(
        new URL("./ParameterSettingsPage.jsx", import.meta.url),
        "utf8",
    );
    assert.match(source, /export function ParameterSettingsView/);
    assert.match(source, /advancedExpanded = false/);
    assert.match(source, /useState\(false\)/);
    assert.match(source, /readOnly=\{!editable\}/);
    assert.match(source, /disabled=\{!editable\}/);
    assert.match(source, /LOCKED — LIVE legacy/);
    assert.match(source, /READ ONLY/);
});
