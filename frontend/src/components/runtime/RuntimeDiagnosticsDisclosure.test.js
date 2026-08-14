import assert from "node:assert/strict";
import {
    mkdtemp,
    readFile,
    rm,
    writeFile,
} from "node:fs/promises";
import {
    dirname,
    join,
} from "node:path";
import test from "node:test";
import {
    fileURLToPath,
    pathToFileURL,
} from "node:url";

import {
    transformWithOxc,
} from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const moduleUrl = (source) => `data:text/javascript,${encodeURIComponent(source)}`;

let disclosurePromise;

const loadDisclosure = async () => {
    const sourceUrl = new URL("./RuntimeDiagnosticsDisclosure.jsx", import.meta.url);
    const sourcePath = fileURLToPath(sourceUrl);
    const source = await readFile(sourceUrl, "utf8");
    const transformed = await transformWithOxc(
        source,
        sourcePath,
    );
    const tempDir = await mkdtemp(
        join(directory, ".runtime-diagnostics-disclosure-test-")
    );
    const tempFile = join(tempDir, "RuntimeDiagnosticsDisclosure.mjs");
    const reactStub = moduleUrl(
        "export const useState=(initializer)=>{"
        + "if(globalThis.__disclosureState===undefined){"
        + "globalThis.__disclosureState=typeof initializer==='function'?initializer():initializer;"
        + "}"
        + "return[globalThis.__disclosureState,(value)=>{"
        + "globalThis.__disclosureState=typeof value==='function'?value(globalThis.__disclosureState):value;"
        + "globalThis.__disclosureRenders=(globalThis.__disclosureRenders||0)+1;"
        + "}];};",
    );
    const runtimeOverviewStub = moduleUrl(
        "export default()=>({type:'section',props:{children:'RUNTIME OVERVIEW STUB'}});",
    );
    const decisionFlowStub = moduleUrl(
        "export default()=>({type:'section',props:{children:'DECISION FLOW STUB'}});",
    );
    const diagnosticsStub = moduleUrl(
        "export default()=>({type:'section',props:{children:'DIAGNOSTICS STUB'}});",
    );
    const timelineStub = moduleUrl(
        "export default()=>({type:'section',props:{children:'RUNTIME TIMELINE STUB'}});",
    );
    const stageInspectorStub = moduleUrl(
        "export default()=>({type:'section',props:{children:'STAGE INSPECTOR STUB'}});",
    );
    const code = transformed.code
        .replace('from "react";', `from "${reactStub}";`)
        .replace('from "./RuntimeOverviewPanel";', `from "${runtimeOverviewStub}";`)
        .replace('from "./DecisionFlowPanel";', `from "${decisionFlowStub}";`)
        .replace('from "./DiagnosticsPanel";', `from "${diagnosticsStub}";`)
        .replace('from "./RuntimeTimelinePanel";', `from "${timelineStub}";`)
        .replace('from "./StageInspectorPanel";', `from "${stageInspectorStub}";`);

    try {
        await writeFile(tempFile, code);
        return await import(`${pathToFileURL(tempFile).href}?t=${Date.now()}`);
    } finally {
        await rm(
            tempDir,
            {
                force: true,
                recursive: true,
            },
        );
    }
};

const getDisclosure = () => {
    if (!disclosurePromise) {
        disclosurePromise = loadDisclosure();
    }

    return disclosurePromise;
};

const childrenOf = (element) => {
    if (!element || typeof element !== "object") {
        return [];
    }

    const children = element.props?.children;

    if (children === undefined || children === null) {
        return [];
    }

    return Array.isArray(children)
        ? children
        : [children];
};

const findElement = (element, predicate) => {
    if (
        element
        && typeof element === "object"
        && predicate(element)
    ) {
        return element;
    }

    for (const child of childrenOf(element)) {
        const match = findElement(child, predicate);

        if (match) {
            return match;
        }
    }

    return null;
};

const collectText = (value) => {
    if (value === null || value === undefined || value === false) {
        return "";
    }

    if (typeof value === "string" || typeof value === "number") {
        return String(value);
    }

    if (Array.isArray(value)) {
        return value.map(collectText).join(" ");
    }

    if (typeof value === "object") {
        if (typeof value.type === "function") {
            return collectText(value.type(value.props));
        }

        return collectText(value.props?.children);
    }

    return "";
};

const baseProps = {
    runtimeHealth: {
        running: false,
        stages: [],
        loops: [],
        timeline: [],
        pipelineStatus: "UNKNOWN",
        runtimeEngine: { status: "--", healthy: false },
        browserWebSocket: { status: "--", connected: false },
        exchangeWebSocket: { status: "--", connected: false },
        executionEngine: { status: "--", available: false },
        executionAuthority: { status: "--" },
        executionEnabled: false,
        tradingAction: { status: "--", reason: "--", decision: "--" },
        latencyMs: null,
        health: "CRITICAL",
        blockingReason: "SNAPSHOT_MISSING",
        issues: ["SNAPSHOT_MISSING"],
    },
    displayedHealth: "CRITICAL",
    displayedBlockingReason: "SNAPSHOT_MISSING",
    browserWsConnected: false,
    selectedStageId: "trading-runtime",
    onSelectStage: () => {},
    selectedStage: { id: "trading-runtime" },
};

test("Runtime diagnostics disclosure renders a toggle that is collapsed by default", async () => {
    globalThis.__disclosureState = undefined;
    const { default: RuntimeDiagnosticsDisclosure } = await getDisclosure();
    const element = RuntimeDiagnosticsDisclosure(baseProps);
    const button = findElement(
        element,
        (candidate) => candidate.type === "button",
    );

    assert.ok(button);
    assert.equal(button.props.type, "button");
    assert.equal(button.props["aria-expanded"], false);
    assert.equal(
        button.props["aria-controls"],
        "runtime-diagnostics-panel",
    );
    assert.equal(
        collectText(button.props.children),
        "▶ RUNTIME & DIAGNOSTICS COLLAPSED",
    );

    const panel = findElement(
        element,
        (candidate) => candidate.props?.id === "runtime-diagnostics-panel",
    );

    assert.ok(panel);
    assert.equal(panel.props.hidden, true);
});

test("Runtime diagnostics disclosure expands and collapses on toggle clicks", async () => {
    globalThis.__disclosureState = undefined;
    const { default: RuntimeDiagnosticsDisclosure } = await getDisclosure();
    const initial = RuntimeDiagnosticsDisclosure(baseProps);
    const initialButton = findElement(
        initial,
        (candidate) => candidate.type === "button",
    );

    initialButton.props.onClick();

    const expanded = RuntimeDiagnosticsDisclosure(baseProps);
    const expandedButton = findElement(
        expanded,
        (candidate) => candidate.type === "button",
    );

    assert.equal(expandedButton.props["aria-expanded"], true);
    assert.equal(
        collectText(expandedButton.props.children),
        "▼ RUNTIME & DIAGNOSTICS EXPANDED",
    );

    const expandedPanel = findElement(
        expanded,
        (candidate) => candidate.props?.id === "runtime-diagnostics-panel",
    );

    assert.ok(expandedPanel);
    assert.equal(expandedPanel.props.hidden, false);

    expandedButton.props.onClick();

    const collapsed = RuntimeDiagnosticsDisclosure(baseProps);
    const collapsedButton = findElement(
        collapsed,
        (candidate) => candidate.type === "button",
    );

    assert.equal(collapsedButton.props["aria-expanded"], false);

    const collapsedPanel = findElement(
        collapsed,
        (candidate) => candidate.props?.id === "runtime-diagnostics-panel",
    );

    assert.equal(collapsedPanel.props.hidden, true);
});

test("Runtime diagnostics disclosure renders the five runtime sections when expanded", async () => {
    globalThis.__disclosureState = false;
    const { default: RuntimeDiagnosticsDisclosure } = await getDisclosure();
    const element = RuntimeDiagnosticsDisclosure(baseProps);
    const text = collectText(element);

    assert.match(text, /RUNTIME & DIAGNOSTICS/);
    assert.match(text, /RUNTIME OVERVIEW STUB/);
    assert.match(text, /DECISION FLOW STUB/);
    assert.match(text, /STAGE INSPECTOR STUB/);
    assert.match(text, /RUNTIME TIMELINE STUB/);
    assert.match(text, /DIAGNOSTICS STUB/);
});

test("Runtime diagnostics disclosure is frontend-only and adds no data communication", async () => {
    const source = await readFile(
        new URL("./RuntimeDiagnosticsDisclosure.jsx", import.meta.url),
        "utf8",
    );

    for (const forbidden of [
        "fetch(",
        "axios",
        "new WebSocket(",
        "WebSocket(",
        "localStorage",
        "sessionStorage",
        "history.pushState",
    ]) {
        assert.equal(source.includes(forbidden), false, forbidden);
    }

    assert.match(source, /aria-expanded/);
    assert.match(source, /aria-controls/);
    assert.match(source, /useState/);
    assert.match(source, /hidden=\{!open\}/);
});
