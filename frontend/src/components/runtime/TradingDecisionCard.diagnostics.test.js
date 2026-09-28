import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import * as React from "react";
import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const modelUrl = new URL("./tradingCycleModel.js", import.meta.url).href;

const loadComponent = async () => {
    const source = new URL("./TradingDecisionCard.jsx", import.meta.url);
    const transformed = await transformWithOxc(
        await readFile(source, "utf8"),
        fileURLToPath(source),
    );
    const temporary = await mkdtemp(join(directory, ".trading-decision-diag-test-"));
    const output = join(temporary, "TradingDecisionCard.mjs");
    try {
        let code = transformed.code.replace(
            /from ['"]\.\/tradingCycleModel['"];/,
            `from "${modelUrl}";`,
        );
        await writeFile(output, code);
        return (await import(`${pathToFileURL(output).href}?t=${Date.now()}`)).default;
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

const createRenderer = (Component, props) => {
    const internals = React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
    const values = [];
    let currentProps = props;
    let hookIndex = 0;
    let root;
    const dispatcher = {
        useState(initial) {
            const index = hookIndex++;
            if (values.length <= index) values[index] = typeof initial === "function" ? initial() : initial;
            return [values[index], (next) => {
                values[index] = typeof next === "function" ? next(values[index]) : next;
            }];
        },
        useEffect() {},
    };
    const render = (nextProps) => {
        if (nextProps) currentProps = { ...currentProps, ...nextProps };
        hookIndex = 0;
        const previous = internals.H;
        internals.H = dispatcher;
        try { root = Component(currentProps); } finally { internals.H = previous; }
        return root;
    };
    render();
    return { get root() { return root; }, render };
};

const descendants = (node) => {
    if (node == null || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    if (typeof node.type === "function") return descendants(node.type(node.props));
    return [node, ...descendants(node.props?.children)];
};
const text = (node) => {
    if (node == null || node === false) return "";
    if (["string", "number"].includes(typeof node)) return String(node);
    if (Array.isArray(node)) return node.map(text).join(" ");
    return typeof node === "object" ? text(node.props?.children) : "";
};
const normalizedText = (node) => text(node).replace(/\s+/g, " ").trim();
const findToggle = (root, testId) => descendants(root).find(
    (node) => node.props?.["data-testid"] === testId,
);
const findBodyById = (root, id) => descendants(root).find(
    (node) => node.props?.id === id,
);

const findDrawer = (root) => descendants(root).find(
    (node) => node.props?.["data-testid"] === "trading-cycle-diagnostics-drawer",
);
const countDrawers = (root) => descendants(root).filter(
    (node) => node.props?.["data-testid"] === "trading-cycle-diagnostics-drawer",
).length;
const findDrawerClose = (root) => descendants(root).find(
    (node) => node.props?.["data-testid"] === "trading-cycle-drawer-close",
);
const findDialog = (root) => descendants(root).find(
    (node) => node.props?.role === "dialog",
);
const withinDrawer = (root, id) => {
    const drawer = findDrawer(root);
    return Boolean(drawer) && descendants(drawer).some((node) => node.props?.id === id);
};

const stepToggleId = (index) => `trading-cycle-step-${index}-toggle`;
const stepBodyId = (index) => `trading-cycle-step-${index}-content`;

const buildStep = (index) => {
    if (index === 4) {
        return {
            index,
            key: `step-${index}`,
            name: "Micro Edge Strategy",
            status: "BLOCKED",
            reasonCode: "LOW_COMPOSITE_SCORE",
            reasonText: "Micro Edge Strategy blocked entry: COMPOSITE_SCORE is 0.42, required >= 0.55",
            current: { edgeScore: 0.42, blockingCondition: "COMPOSITE_SCORE" },
            required: { minimumCompositeScore: 0.55 },
            comparison: "BLOCK",
            blockerType: "PARAMETER",
            actionable: "YES",
            relatedParameters: [
                { key: "minimumCompositeScore", currentSetting: 0.55, scope: "PAPER" },
            ],
            parameterLocation: { route: "/parameter-settings", anchor: null },
            nextCondition: "ENTRY_ALLOWED",
            nextStep: 5,
            source: "tradingDecision.entryReadiness",
            evaluatedAt: 1000,
            freshness: { state: "FRESH", ageSeconds: 0, evaluatedAt: 1000 },
            dependencyState: null,
            rootBlockerStep: null,
        };
    }
    const future = index > 4;
    return {
        index,
        key: `step-${index}`,
        name: `Step ${index}`,
        status: index === 5 ? "BYPASSED" : future ? "WAITING" : "COMPLETED",
        reasonCode: future ? "STEP_OK" : "STEP_EVALUATED",
        reasonText: `Step ${index} reason`,
        current: index === 13 ? null : `current-${index}`,
        required: `required-${index}`,
        comparison: future ? "WAITING" : "PASS",
        blockerType: index === 5 ? "MODE" : "NONE",
        actionable: index === 5 ? "CONDITIONAL" : "NO",
        relatedParameters: [],
        parameterLocation: null,
        nextCondition: `next-condition-${index}`,
        nextStep: index + 1,
        source: `test.source.${index}`,
        evaluatedAt: 1000,
        freshness: { state: "FRESH", ageSeconds: 0, evaluatedAt: 1000 },
        dependencyState: future ? "WAITING_FOR_STEP_4" : null,
        rootBlockerStep: future ? 4 : null,
    };
};

const diagnosticsFixture = () => ({
    schemaVersion: 1,
    cycleState: "BLOCKED",
    rootBlocker: {
        step: 4,
        reasonCode: "LOW_COMPOSITE_SCORE",
        reasonText: "Micro Edge Strategy blocked entry: COMPOSITE_SCORE is 0.42, required >= 0.55",
        blockerType: "PARAMETER",
        source: "tradingDecision.entryReadiness",
        evaluatedAt: 1000,
    },
    rootBlockerStep: 4,
    steps: Array.from({ length: 15 }, (_, index) => buildStep(index)),
});

const renderCard = async (overrides = {}) => {
    const Component = await loadComponent();
    const diagnostics = overrides.diagnostics === undefined
        ? diagnosticsFixture()
        : overrides.diagnostics;
    const renderer = createRenderer(Component, {
        decision: { currentStageIndex: 4, currentActivity: "EVALUATING_STRATEGY" },
        diagnostics,
        ...overrides,
    });
    return renderer;
};

const openStep = (renderer, index) => {
    const button = findToggle(renderer.root, stepToggleId(index));
    assert.ok(button, `step ${index} toggle exists`);
    button.props.onClick();
    renderer.render();
};

test("every STEP renders a details control collapsed by default and no drawer", async () => {
    const renderer = await renderCard();

    for (let index = 0; index < 15; index += 1) {
        const toggle = findToggle(renderer.root, stepToggleId(index));
        assert.ok(toggle, `step ${index} disclosure exists`);
        assert.equal(toggle.props["aria-expanded"], false, `step ${index} collapsed`);
        assert.equal(findBodyById(renderer.root, stepBodyId(index)), undefined);
    }
    assert.equal(findDrawer(renderer.root), undefined, "no drawer by default");
    assert.equal(countDrawers(renderer.root), 0);
});

test("all 15 stage cards remain rendered with diagnostics present", async () => {
    const renderer = await renderCard();
    const labels = descendants(renderer.root).filter(
        (node) => typeof node.props?.className === "string"
            && node.props.className.includes("trading-cycle-stage-label"),
    );
    assert.equal(labels.length, 15);
});

test("all 15 DETAILS controls remain rendered", async () => {
    const renderer = await renderCard();
    const controls = descendants(renderer.root).filter(
        (node) => typeof node.props?.className === "string"
            && node.props.className.split(/\s+/).includes("trading-cycle-step-toggle"),
    );
    assert.equal(controls.length, 15);
});

test("clicking STEP 4 opens the overlay drawer showing STEP 4 diagnostics", async () => {
    const renderer = await renderCard();

    openStep(renderer, 4);

    assert.equal(
        findToggle(renderer.root, stepToggleId(4)).props["aria-expanded"],
        true,
    );
    assert.equal(findToggle(renderer.root, stepToggleId(6)).props["aria-expanded"], false);

    const drawer = findDrawer(renderer.root);
    assert.ok(drawer, "drawer rendered");
    assert.equal(countDrawers(renderer.root), 1, "exactly one drawer");
    assert.equal(drawer.props.role, "dialog");

    const drawerText = normalizedText(drawer);
    assert.equal(drawerText.includes("TRADING CYCLE DIAGNOSTICS"), true);
    assert.equal(drawerText.includes("STEP 4"), true);
    assert.equal(drawerText.includes("Micro Edge Strategy"), true);
    assert.equal(drawerText.includes("STATUS: BLOCKED"), true);

    assert.equal(withinDrawer(renderer.root, stepBodyId(4)), true);

    const bodyText = normalizedText(findBodyById(renderer.root, stepBodyId(4)));
    assert.equal(bodyText.includes("WHY"), true);
    assert.equal(bodyText.includes("CURRENT"), true);
    assert.equal(bodyText.includes("REQUIRED"), true);
    assert.equal(bodyText.includes("LOW_COMPOSITE_SCORE"), true);
    assert.equal(bodyText.includes("0.42"), true);
    assert.equal(bodyText.includes("0.55"), true);
});

test("drawer surfaces comparison, root blocker, action, next condition and source", async () => {
    const renderer = await renderCard();
    openStep(renderer, 4);

    const bodyText = normalizedText(findBodyById(renderer.root, stepBodyId(4)));
    assert.equal(bodyText.includes("COMPARISON"), true);
    assert.equal(bodyText.includes("ROOT BLOCKER"), true);
    assert.equal(bodyText.includes("BLOCKER TYPE"), true);
    assert.equal(bodyText.includes("OPERATOR ACTION"), true);
    assert.equal(bodyText.includes("RELATED PARAMETER"), true);
    assert.equal(bodyText.includes("NEXT CONDITION"), true);
    assert.equal(bodyText.includes("NEXT STEP"), true);
    assert.equal(bodyText.includes("SOURCE"), true);
    assert.equal(bodyText.includes("FRESHNESS"), true);
});

test("the old inline STEP panel no longer renders under the cycle", async () => {
    const renderer = await renderCard();
    openStep(renderer, 4);

    const wrappers = descendants(renderer.root).filter(
        (node) => typeof node.props?.className === "string"
            && node.props.className.includes("trading-cycle-stage-details"),
    );
    assert.ok(wrappers.length >= 15);
    wrappers.forEach((wrapper) => {
        assert.equal(
            descendants(wrapper).some((node) => node.props?.id === stepBodyId(4)),
            false,
            "diagnostics panel must not render inline under the step",
        );
    });
});

test("clicking another STEP switches the same single drawer without closing", async () => {
    const renderer = await renderCard();

    openStep(renderer, 4);
    assert.equal(countDrawers(renderer.root), 1);

    openStep(renderer, 9);

    assert.equal(countDrawers(renderer.root), 1, "still exactly one drawer");
    assert.equal(findToggle(renderer.root, stepToggleId(4)).props["aria-expanded"], false);
    assert.equal(findToggle(renderer.root, stepToggleId(9)).props["aria-expanded"], true);
    assert.equal(findBodyById(renderer.root, stepBodyId(4)), undefined);
    assert.equal(withinDrawer(renderer.root, stepBodyId(9)), true);

    const drawerText = normalizedText(findDrawer(renderer.root));
    assert.equal(drawerText.includes("STEP 9"), true);
});

test("the drawer close button closes it and preserves the cycle", async () => {
    const renderer = await renderCard();
    openStep(renderer, 4);

    const close = findDrawerClose(renderer.root);
    assert.ok(close, "close button exists");
    assert.ok(close.props["aria-label"], "close button has accessible name");
    close.props.onClick();
    renderer.render();

    assert.equal(findDrawer(renderer.root), undefined, "drawer closed");
    assert.equal(findToggle(renderer.root, stepToggleId(4)).props["aria-expanded"], false);
    assert.equal(
        descendants(renderer.root).filter(
            (node) => typeof node.props?.className === "string"
                && node.props.className.includes("trading-cycle-stage-label"),
        ).length,
        15,
        "cycle still renders 15 STEP cards",
    );
});

test("Escape key closes the drawer", async () => {
    const renderer = await renderCard();
    openStep(renderer, 4);

    const dialog = findDialog(renderer.root);
    assert.ok(dialog, "dialog present");
    dialog.props.onKeyDown({ key: "Escape", stopPropagation() {} });
    renderer.render();

    assert.equal(findDrawer(renderer.root), undefined, "drawer closed by Escape");
});

test("root blocker is announced on the owning STEP inside the drawer", async () => {
    const renderer = await renderCard();
    openStep(renderer, 4);

    const bodyText = normalizedText(findBodyById(renderer.root, stepBodyId(4)));
    assert.equal(bodyText.includes("THIS STEP (ROOT BLOCKER)"), true);
    assert.equal(bodyText.includes("PARAMETER"), true);
    assert.equal(bodyText.includes("YES"), true);
});

test("downstream STEPs display WAITING FOR STEP n inside the drawer", async () => {
    const renderer = await renderCard();
    openStep(renderer, 6);

    const bodyText = normalizedText(findBodyById(renderer.root, stepBodyId(6)));
    assert.equal(bodyText.includes("WAITING FOR STEP 4"), true);
});

test("bypassed AI STEP is displayed as BYPASSED", async () => {
    const renderer = await renderCard();
    const aiStage = descendants(renderer.root).find(
        (node) => typeof node.props?.className === "string"
            && node.props.className.includes("trading-cycle-stage")
            && node.props["data-status"] === "BYPASSED",
    );
    assert.ok(aiStage, "AI STEP renders a BYPASSED status");
});

test("missing canonical values render as NOT AVAILABLE rather than guessed", async () => {
    const renderer = await renderCard();
    openStep(renderer, 13);

    const bodyText = normalizedText(findBodyById(renderer.root, stepBodyId(13)));
    assert.equal(bodyText.includes("NOT AVAILABLE"), true);
});

test("card without diagnostics still renders STD sections and a safe empty drawer", async () => {
    const renderer = await renderCard({ diagnostics: null });

    assert.equal(findToggle(renderer.root, "current-activity-title-toggle") != null, true);
    assert.equal(findToggle(renderer.root, "lower-status-title-toggle") != null, true);
    assert.equal(findToggle(renderer.root, "runtime-meta-title-toggle") != null, true);

    openStep(renderer, 4);
    const body = findBodyById(renderer.root, stepBodyId(4));
    assert.ok(body, "empty diagnostics panel still renders in the drawer");
    assert.equal(withinDrawer(renderer.root, stepBodyId(4)), true);
    assert.equal(normalizedText(body).includes("NOT AVAILABLE"), true);
});
