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
    const temporary = await mkdtemp(join(directory, ".trading-decision-test-"));
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

const DISCLOSURE_TOGGLES = {
    currentActivity: "current-activity-title-toggle",
    decisionDetails: "lower-status-title-toggle",
    thirdSection: "runtime-meta-title-toggle",
};
const DISCLOSURE_BODIES = {
    currentActivity: "current-activity-title-content",
    decisionDetails: "lower-status-title-content",
    thirdSection: "runtime-meta-title-content",
};

const toggle = (renderer, testId) => {
    const button = findToggle(renderer.root, testId);
    assert.ok(button, `${testId} toggle button exists`);
    assert.equal(typeof button.props.onClick, "function");
    button.props.onClick();
    renderer.render();
};

test("TradingDecisionCard renders trading cycle title", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, { decision: {} });
    const nodes = descendants(renderer.root);
    const titles = nodes.filter((node) =>
        node.type === "h2" || (node.props && node.props.children &&
        (String(node.props.children).includes("TRADING CYCLE") || String(node.props.children).includes("トレーディングサイクル")))
    );
    assert.ok(titles.length > 0);
});

test("TradingDecisionCard renders all 15 stages", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, { decision: {} });
    const nodes = descendants(renderer.root);
    const stageLabels = [
        "Parameter Context",
        "Market Selection",
        "Market Data",
        "Feature Builder",
        "Micro Edge Strategy",
        "AI Decision / Review",
        "Money Management",
        "Governance",
        "Execution",
        "Position",
        "Exit Monitoring",
        "Settlement / Exit Execution",
        "Position Closed",
        "Trade / Parameter Performance Record",
        "Ready for Next Trade",
    ];

    const foundLabels = [];
    nodes.forEach((node) => {
        if (node.type === "div" && node.props?.className?.includes("trading-cycle-stage-label")) {
            const nodeText = String(node.props.children).trim();
            if (stageLabels.includes(nodeText)) {
                foundLabels.push(nodeText);
            }
        }
    });

    assert.equal(foundLabels.length, 15);
    stageLabels.forEach((label) => {
        assert.ok(foundLabels.includes(label));
    });
});

test("TradingDecisionCard renders current activity panel", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, { decision: {} });

    const hasActivityPanel = descendants(renderer.root).some((node) =>
        node.type === "section" && node.props?.className?.includes("current-activity-panel")
    );

    assert.ok(hasActivityPanel);
});

test("TradingDecisionCard renders lower status panel", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, { decision: {} });

    const hasLowerPanel = descendants(renderer.root).some((node) =>
        node.type === "section" && node.props?.className?.includes("lower-status-panel")
    );

    assert.ok(hasLowerPanel);
});

test("TradingDecisionCard displays selected symbol when available", async () => {
    const symbol = "BTC/USDT";
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        decision: {
            stages: {
                market: {
                    symbol,
                },
            },
        },
    });

    toggle(renderer, DISCLOSURE_TOGGLES.currentActivity);

    const hasSymbol = descendants(renderer.root).some((node) => {
        const nodeText = String(node.props?.children || "").trim();
        return nodeText === symbol;
    });

    assert.ok(hasSymbol);
});

test("TradingDecisionCard handles position open state", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        decision: {
            currentState: "POSITION OPEN",
            stages: {
                execution: {
                    positionState: "POSITION OPEN",
                },
            },
        },
    });

    const hasPositionStage = descendants(renderer.root).some((node) => {
        const nodeText = String(node.props?.children || "").trim();
        return nodeText === "Position";
    });

    assert.ok(hasPositionStage);
});

test("TradingDecisionCard displays correct labels for Japanese users", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, { decision: {} });

    const hasJapaneseTitle = descendants(renderer.root).some((node) => {
        const nodeText = String(node.props?.children || "").trim();
        return nodeText.includes("トレーディングサイクル");
    });

    assert.ok(hasJapaneseTitle);
});

test("TradingDecisionCard handles stopped state correctly", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        decision: {
            currentActivity: "BOT_STOPPED",
        },
    });

    // Check that all stages are NOT_REACHED
    const activeStages = descendants(renderer.root).filter((node) =>
        node.type === "div" && node.props?.["data-status"] === "CURRENT"
    );
    assert.equal(activeStages.length, 0);
});

test("TradingDecisionCard renders last order as a footer after the cycle stages", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        decision: {},
        lastOrderValue: "NONE THIS SESSION",
    });
    const nodes = descendants(renderer.root);
    const footer = nodes.find((node) => node.props?.["data-testid"] === "last-execution-activity");
    assert.ok(footer, "last-order footer present");
    const cycleIndex = nodes.findIndex(
        (node) => node.type === "section" && node.props?.className?.includes("trading-cycle-flow"),
    );
    const footerIndex = nodes.findIndex((node) => node === footer);
    assert.ok(cycleIndex >= 0, "cycle visualization present");
    assert.ok(footerIndex > cycleIndex, "last order appears after the cycle visualization");
    assert.equal(String(footer.props.children?.[0]?.props?.children).trim(), "LAST ORDER");
    assert.equal(String(footer.props.children?.[1]?.props?.children).trim(), "NONE THIS SESSION");
});

test("all three trading cycle detail disclosures default to collapsed", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, { decision: {} });

    Object.entries(DISCLOSURE_TOGGLES).forEach(([key, testId]) => {
        const toggleNode = findToggle(renderer.root, testId);
        assert.ok(toggleNode, `${key} disclosure toggle exists`);
        assert.equal(toggleNode.props["aria-expanded"], false, `${key} defaults to collapsed`);
        assert.equal(
            findBodyById(renderer.root, DISCLOSURE_BODIES[key]),
            undefined,
            `${key} body hidden by default`,
        );
    });
});

test("CURRENT ACTIVITY body is hidden by default and shown after expand", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        decision: {
            stages: { market: { symbol: "ETH/USDT" } },
            currentStage: { label: "Realtime Data" },
            currentActivity: "FETCHING_DATA",
            nextStage: { label: "Execution" },
        },
    });

    assert.equal(
        findBodyById(renderer.root, DISCLOSURE_BODIES.currentActivity),
        undefined,
        "CURRENT ACTIVITY body hidden by default",
    );

    toggle(renderer, DISCLOSURE_TOGGLES.currentActivity);

    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.currentActivity).props["aria-expanded"],
        true,
    );
    const body = findBodyById(renderer.root, DISCLOSURE_BODIES.currentActivity);
    assert.ok(body, "CURRENT ACTIVITY body visible after expand");
    const bodyText = normalizedText(body);
    assert.equal(bodyText.includes("CURRENT STAGE"), true);
    assert.equal(bodyText.includes("CURRENT ACTION"), true);
    assert.equal(bodyText.includes("SELECTED SYMBOL"), true);
    assert.equal(bodyText.includes("NEXT STAGE"), true);

    // Re-collapse
    toggle(renderer, DISCLOSURE_TOGGLES.currentActivity);
    assert.equal(
        findBodyById(renderer.root, DISCLOSURE_BODIES.currentActivity),
        undefined,
        "CURRENT ACTIVITY body re-collapsed",
    );
});

test("DECISION DETAILS body is hidden by default and shown after expand", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        decision: {
            finalDecision: "BUY",
            currentState: "READY",
            blockingStage: "NONE",
            cycleId: "cycle-1",
        },
    });

    assert.equal(
        findBodyById(renderer.root, DISCLOSURE_BODIES.decisionDetails),
        undefined,
        "DECISION DETAILS body hidden by default",
    );

    toggle(renderer, DISCLOSURE_TOGGLES.decisionDetails);

    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.decisionDetails).props["aria-expanded"],
        true,
    );
    const body = findBodyById(renderer.root, DISCLOSURE_BODIES.decisionDetails);
    assert.ok(body, "DECISION DETAILS body visible after expand");
    const bodyText = normalizedText(body);
    assert.equal(bodyText.includes("FINAL DECISION"), true);
    assert.equal(bodyText.includes("CURRENT STATE"), true);
    assert.equal(bodyText.includes("BLOCKED AT"), true);
    assert.equal(bodyText.includes("REASON"), true);
    assert.equal(bodyText.includes("CYCLE ID"), true);
    assert.equal(bodyText.includes("PENDING ORDER"), true);
    assert.equal(bodyText.includes("LAST UPDATE"), true);
    assert.equal(bodyText.includes("STATE DURATION"), true);
});

test("third detail (RUNTIME STATUS) body is hidden by default and shown after expand", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, {
        decision: {
            mode: "PAPER",
            exchange: "PAPER",
            realOrderAllowed: false,
            bot: "RUNNING",
        },
    });

    assert.equal(
        findBodyById(renderer.root, DISCLOSURE_BODIES.thirdSection),
        undefined,
        "third detail body hidden by default",
    );

    toggle(renderer, DISCLOSURE_TOGGLES.thirdSection);

    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.thirdSection).props["aria-expanded"],
        true,
    );
    const body = findBodyById(renderer.root, DISCLOSURE_BODIES.thirdSection);
    assert.ok(body, "third detail body visible after expand");
    const bodyText = normalizedText(body);
    assert.equal(bodyText.includes("MODE"), true);
    assert.equal(bodyText.includes("EXCHANGE"), true);
    assert.equal(bodyText.includes("REAL ORDER"), true);
    assert.equal(bodyText.includes("BOT"), true);
    assert.equal(bodyText.includes("LOOP"), true);
    assert.equal(bodyText.includes("AUTO TRADE"), true);
});

test("the three trading cycle disclosures toggle independently", async () => {
    const Component = await loadComponent();
    const renderer = createRenderer(Component, { decision: {} });

    toggle(renderer, DISCLOSURE_TOGGLES.currentActivity);
    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.currentActivity).props["aria-expanded"],
        true,
    );
    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.decisionDetails).props["aria-expanded"],
        false,
    );
    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.thirdSection).props["aria-expanded"],
        false,
    );

    toggle(renderer, DISCLOSURE_TOGGLES.decisionDetails);
    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.currentActivity).props["aria-expanded"],
        true,
    );
    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.decisionDetails).props["aria-expanded"],
        true,
    );
    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.thirdSection).props["aria-expanded"],
        false,
    );

    // Collapsing one does not affect the others.
    toggle(renderer, DISCLOSURE_TOGGLES.currentActivity);
    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.currentActivity).props["aria-expanded"],
        false,
    );
    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.decisionDetails).props["aria-expanded"],
        true,
    );
    assert.equal(
        findToggle(renderer.root, DISCLOSURE_TOGGLES.thirdSection).props["aria-expanded"],
        false,
    );
});
