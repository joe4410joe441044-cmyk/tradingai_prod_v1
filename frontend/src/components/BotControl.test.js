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

import * as React from "react";
import {
    transformWithOxc,
} from "vite";

let botControlPromise;

const sourceUrl = new URL("./BotControl.jsx", import.meta.url);
const sourcePath = fileURLToPath(sourceUrl);
const sourceDir = dirname(sourcePath);
const runtimeUrl = pathToFileURL(
    join(sourceDir, "../runtime/governanceRuntime.js")
).href;
const telemetryUrl = pathToFileURL(
    join(sourceDir, "../store/telemetryStore.js")
).href;
const botLifecycleUrl = pathToFileURL(
    join(sourceDir, "../runtime/botLifecycle.js")
).href;
const operationPreparationModelUrl = pathToFileURL(
    join(sourceDir, "./operation/operationPreparationModel.js")
).href;

const transformJsxFile = async (
    inputUrl
) => {
    const inputPath = fileURLToPath(inputUrl);
    const source = await readFile(inputUrl, "utf8");

    return transformWithOxc(
        source,
        inputPath,
    );
};

const loadBotControl = async () => {
    const tempDir = await mkdtemp(
        join(sourceDir, ".bot-control-test-")
    );
    const operationToggleFile = join(
        tempDir,
        "OperationToggle.mjs",
    );
    const operationPreparationFile = join(
        tempDir,
        "OperationPreparation.mjs",
    );
    const moneyManagementHookFile = join(
        tempDir,
        "useMoneyManagement.mjs",
    );
    const apiMockFile = join(
        tempDir,
        "api.mjs",
    );
    const botControlFile = join(
        tempDir,
        "BotControl.mjs",
    );

    try {
        const operationToggle = await transformJsxFile(
            new URL("./common/OperationToggle.jsx", import.meta.url)
        );
        await writeFile(
            operationToggleFile,
            operationToggle.code,
        );

        const operationPreparation = await transformJsxFile(
            new URL("./operation/OperationPreparation.jsx", import.meta.url)
        );
        await writeFile(
            operationPreparationFile,
            operationPreparation.code.replace(
                'from "./operationPreparationModel";',
                `from "${operationPreparationModelUrl}";`,
            ),
        );

        await writeFile(
            moneyManagementHookFile,
            [
                "export function useMoneyManagement() {",
                "  const mm = globalThis.__MM_STATUS__ || {",
                "    lifecycleState: 'RUNNING',",
                "    capitalAuthorityStatus: 'AVAILABLE',",
                "    capitalEligibility: { availableCapital: '10000', riskBudget: '50' },",
                "    executionEntryAllowed: true,",
                "    recommendedAction: 'CONTINUE',",
                "    riskState: 'NORMAL',",
                "  };",
                "  return {",
                "    status: mm,",
                "    configuration: globalThis.__MM_CONFIGURATION__,",
                "    configurationDraft: globalThis.__MM_DRAFT__,",
                "  };",
                "}",
            ].join("\n"),
        );

        await writeFile(
            apiMockFile,
            [
                "export const API = {",
                "  botStart: () => '/api/bot/start',",
                "  botStop: () => '/api/bot/stop',",
                "  loopStart: () => '/api/bot/loop/start',",
                "  loopStop: () => '/api/bot/loop/stop',",
                "};",
            ].join("\n"),
        );

        const botControl = await transformJsxFile(sourceUrl);
        const code = botControl.code
            .replace(
                'from "../store/telemetryStore";',
                `from "${telemetryUrl}";`,
            )
            .replace(
                'from "../runtime/governanceRuntime";',
                `from "${runtimeUrl}";`,
            )
            .replace(
                'from "../api";',
                `from "${pathToFileURL(apiMockFile).href}";`,
            )
            .replace(
                'from "../runtime/botLifecycle";',
                `from "${botLifecycleUrl}";`,
            )
            .replace(
                'from "./common/OperationToggle";',
                `from "${pathToFileURL(operationToggleFile).href}";`,
            )
            .replace(
                'from "../features/money-management/hooks/useMoneyManagement";',
                `from "${pathToFileURL(moneyManagementHookFile).href}";`,
            )
            .replace(
                'from "./operation/OperationPreparation";',
                `from "${pathToFileURL(operationPreparationFile).href}";`,
            )
            .replace(
                'from "./operation/operationPreparationModel";',
                `from "${operationPreparationModelUrl}";`,
            );

        await writeFile(
            botControlFile,
            code,
        );

        const module = await import(
            `${pathToFileURL(botControlFile).href}?t=${Date.now()}`
        );

        return module.default;
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

const getBotControl = () => {
    if (!botControlPromise) {
        botControlPromise = loadBotControl();
    }

    return botControlPromise;
};

const childrenOf = (
    element
) => {
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

const findAll = (
    element,
    predicate,
    matches = [],
) => {
    if (
        element
        && typeof element === "object"
        && predicate(element)
    ) {
        matches.push(element);
    }

    for (const child of childrenOf(element)) {
        findAll(
            child,
            predicate,
            matches,
        );
    }

    return matches;
};

const collectText = (
    value
) => {
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
        return collectText(value.props?.children);
    }

    return "";
};

const normalizeText = (
    value
) => collectText(value).replace(/\s+/g, " ").trim();

const buttonName = (
    button
) => (
    normalizeText(button)
    || button.props?.["aria-label"]
    || ""
);

const buttons = (
    root
) => findAll(
    root,
    (element) => element.type === "button",
);

const findButton = (
    root,
    matcher
) => {
    const predicate = typeof matcher === "string"
        ? (name) => name.includes(matcher)
        : matcher;

    return buttons(root).find(
        (button) => predicate(buttonName(button), button)
    ) || null;
};

const findGroupButton = (
    root,
    groupLabel,
    buttonLabel
) => {
    const group = findAll(
        root,
        (element) => (
            element.props?.role === "group"
            && element.props?.["aria-label"] === groupLabel
        ),
    )[0];

    if (!group) {
        return null;
    }

    return buttons(group).find(
        (button) => buttonName(button) === buttonLabel,
    ) || null;
};

const textIncludes = (
    root,
    text
) => normalizeText(root).includes(text);

const createHookRenderer = (
    Component,
    props
) => {
    const internals =
        React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
    const hookValues = [];
    const hookRefs = [];
    let currentProps = props;
    let root = null;
    let componentElements = [];
    let hookIndex = 0;
    let refIndex = 0;

    const dispatcher = {
        useState(initialValue) {
            const index = hookIndex;
            hookIndex += 1;

            if (hookValues.length <= index) {
                hookValues[index] = typeof initialValue === "function"
                    ? initialValue()
                    : initialValue;
            }

            const setValue = (nextValue) => {
                hookValues[index] = typeof nextValue === "function"
                    ? nextValue(hookValues[index])
                    : nextValue;
            };

            return [
                hookValues[index],
                setValue,
            ];
        },
        useRef(initialValue) {
            const index = refIndex;
            refIndex += 1;

            if (hookRefs.length <= index) {
                hookRefs[index] = {
                    current: initialValue,
                };
            }

            return hookRefs[index];
        },
        useEffect() {
            hookIndex += 1;
        },
    };

    const expand = (
        node
    ) => {
        if (
            node === null
            || node === undefined
            || typeof node === "boolean"
        ) {
            return node;
        }

        if (Array.isArray(node)) {
            return node.map(expand);
        }

        if (
            typeof node === "object"
            && typeof node.type === "function"
        ) {
            componentElements.push(node);

            return expand(node.type(node.props));
        }

        if (typeof node === "object") {
            return {
                ...node,
                props: node.props == null
                    ? node.props
                    : {
                        ...node.props,
                        children: expand(node.props.children),
                    },
            };
        }

        return node;
    };

    const render = (
        nextProps
    ) => {
        if (nextProps) {
            currentProps = {
                ...currentProps,
                ...nextProps,
            };
        }

        hookIndex = 0;
        refIndex = 0;
        componentElements = [];

        const previousDispatcher = internals.H;
        internals.H = dispatcher;

        try {
            root = expand(Component(currentProps));
        } finally {
            internals.H = previousDispatcher;
        }

        return root;
    };

    render();

    return {
        get root() {
            return root;
        },
        get componentElements() {
            return componentElements;
        },
        render,
    };
};

const lastResult = (
    overrides = {}
) => ({
    operationId: "emg_component_test",
    state: "LOCKED",
    result: "SUCCESS",
    startedAt: "2026-07-15T00:00:00.000Z",
    completedAt: "2026-07-15T00:00:05.000Z",
    path: "paper",
    success: true,
    completed: true,
    partial: false,
    retryable: false,
    positionRemaining: false,
    stateUnknown: false,
    cancelResult: {
        status: "NOT_REQUIRED",
        success: true,
        completed: true,
        orders_cancelled: 0,
    },
    flattenResult: {
        status: "NOT_REQUIRED",
        success: true,
        completed: true,
        position_closed: true,
    },
    message: "Emergency completed.",
    ...overrides,
});

const emergencyStatus = (
    state,
    overrides = {}
) => ({
    active: state !== "READY",
    locked: state === "LOCKED" || state === "ACTION_REQUIRED",
    state,
    lastResult: state === "LOCKED"
        ? lastResult()
        : null,
    ...overrides,
});

const defaultProps = (
    overrides = {}
) => {
    const emergency = overrides.emergency || emergencyStatus("READY");

    return {
        config: {
            symbol: "XRPUSDT",
            exchange: "kucoin",
            mode: "paper",
            realOrderAllowed: false,
            allowLive: false,
            tradeMode: "paper",
        },
        executionEnabled: false,
        botRunning: false,
        loopEnabled: false,
        loopState: "STOPPED",
        emergencyLocked: emergency.locked,
        emergencyState: emergency.state,
        emergency,
        pendingOrder: false,
        realOrderAllowed: false,
        onStatusRefresh: async () => undefined,
        setExecutionEnabledState: () => undefined,
        ...overrides,
    };
};

const setMmStatus = (
    overrides = {}
) => {
    globalThis.__MM_STATUS__ = {
        lifecycleState: "RUNNING",
        capitalAuthorityStatus: "AVAILABLE",
        capitalEligibility: { availableCapital: "10000", riskBudget: "50" },
        executionEntryAllowed: true,
        recommendedAction: "CONTINUE",
        riskState: "NORMAL",
        ...overrides,
    };
};

const clearMmStatus = () => {
    delete globalThis.__MM_STATUS__;
};

const setMmConfiguration = (
    overrides = {}
) => {
    globalThis.__MM_CONFIGURATION__ = {
        riskPerTradePercent: "0.50",
        totalExposurePercent: "20.00",
        maximumDrawdownPercent: "5.00",
        maximumLeverage: "5",
        ...overrides,
    };
};

const clearMmConfiguration = () => {
    delete globalThis.__MM_CONFIGURATION__;
};

const clearMmDraft = () => {
    delete globalThis.__MM_DRAFT__;
};

const readyStartProps = (
    overrides = {}
) => {
    const {
        config: configOverrides = {},
        ...restOverrides
    } = overrides;

    return {
        config: {
            symbol: "XRPUSDTM",
            exchange: "kucoin",
            mode: "paper",
            selectionMode: "MANUAL",
            leverage: 5,
            realOrderAllowed: false,
            allowLive: false,
            tradeMode: "paper",
            ...configOverrides,
        },
        position: "FLAT",
        pendingOrder: false,
        runtimeHealth: { governance: { status: "READY" } },
        realOrderAllowed: false,
        ...restOverrides,
    };
};

const renderBotControl = async (
    props = {}
) => {
    const BotControl = await getBotControl();

    return createHookRenderer(
        BotControl,
        defaultProps(props),
    );
};

const jsonResponse = ({
    ok = true,
    status = 200,
    body,
    jsonError = null,
} = {}) => ({
    ok,
    status,
    json: async () => {
        if (jsonError) {
            throw jsonError;
        }

        return body;
    },
});

const deferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((resolvePromise, rejectPromise) => {
        resolve = resolvePromise;
        reject = rejectPromise;
    });

    return {
        promise,
        reject,
        resolve,
    };
};

const installFetchMock = (
    handler
) => {
    const originalFetch = globalThis.fetch;
    const requests = [];

    globalThis.fetch = async (
        url,
        options = {},
    ) => {
        const urlText = String(url);

        if (!urlText.startsWith("/api/")) {
            throw new Error(`Unexpected external request: ${urlText}`);
        }

        requests.push({
            url: urlText,
            options,
        });

        return handler(
            urlText,
            options,
            requests.length - 1,
        );
    };

    return {
        requests,
        restore() {
            globalThis.fetch = originalFetch;
        },
    };
};

const clickAndRender = (
    renderer,
    button
) => {
    const result = button.props.onClick();
    renderer.render();

    return result;
};


test("Return to Normal is permanently rendered with the required state matrix", async () => {
    const cases = [
        ["READY", null],
        ["PROCESSING", true],
        ["LOCKED", false],
        ["ACTION_REQUIRED", false],
        ["FAILED", false],
        ["PARTIAL", false],
        ["STATE_UNKNOWN", false],
    ];

    for (const [state, expectedDisabled] of cases) {
        const emergency = emergencyStatus(state, {
            locked: state !== "READY",
            lastResult: state === "READY" ? null : lastResult({
                state,
                result: state === "LOCKED" ? "SUCCESS" : state,
            }),
        });
        const renderer = await renderBotControl({
            emergency,
            emergencyLocked: emergency.locked,
            emergencyState: state,
        });
        const returnButton = findButton(renderer.root, "通常に戻す");

        if (expectedDisabled === null) {
            assert.equal(returnButton, null, state);
        } else {
            assert.ok(returnButton, state);
            assert.equal(returnButton.props.disabled, expectedDisabled, state);
        }
        assert.equal(findButton(renderer.root, "安全状態を再確認"), null);
        assert.equal(textIncludes(renderer.root, "再確認中..."), false);
    }
});

test("Return to Normal calls unlock once and verifies refreshed safe OFF state", async () => {
    let refreshCount = 0;
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/governance/emergency/unlock");
        return jsonResponse({
            body: {
                success: true,
                unlocked: true,
                emergencyLocked: false,
                emergencyState: "READY",
                loopEnabled: false,
                autoTradeEnabled: false,
                executionEnabled: false,
            },
        });
    });

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("LOCKED"),
            emergencyLocked: true,
            emergencyState: "LOCKED",
            onStatusRefresh: async () => {
                refreshCount += 1;
                return {
                    emergencyLocked: false,
                    emergencyState: "READY",
                    loopEnabled: false,
                    autoTradeEnabled: false,
                    executionEnabled: false,
                };
            },
        });

        await clickAndRender(
            renderer,
            findButton(renderer.root, "通常に戻す"),
        );
        renderer.render();

        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].options.method, "POST");
        assert.equal(refreshCount, 1);
        assert.equal(textIncludes(renderer.root, "解除後の安全状態を確認できません"), false);
        assert.equal(findButton(renderer.root, "安全状態を再確認"), null);
    } finally {
        mock.restore();
    }
});

test("Return to Normal is single-flight and shows pending state", async () => {
    const response = deferred();
    const mock = installFetchMock(() => response.promise);

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("ACTION_REQUIRED", {
                lastResult: lastResult({
                    state: "ACTION_REQUIRED",
                    result: "FAILED",
                    success: false,
                    completed: false,
                }),
            }),
            emergencyLocked: true,
            emergencyState: "ACTION_REQUIRED",
            onStatusRefresh: async () => ({
                emergencyLocked: false,
                emergencyState: "READY",
                loopEnabled: false,
                autoTradeEnabled: false,
                executionEnabled: false,
            }),
        });
        const first = clickAndRender(
            renderer,
            findButton(renderer.root, "通常に戻す"),
        );
        const pendingButton = findButton(renderer.root, "復帰中...");

        assert.ok(pendingButton);
        assert.equal(pendingButton.props.disabled, true);
        pendingButton.props.onClick();
        assert.equal(mock.requests.length, 1);

        response.resolve(jsonResponse({
            body: {
                success: true,
                unlocked: true,
            },
        }));
        await first;
    } finally {
        mock.restore();
    }
});

test("Unlock failure remains visible and can be retried", async () => {
    let attempt = 0;
    const mock = installFetchMock(() => {
        attempt += 1;
        if (attempt === 1) {
            return jsonResponse({
                ok: false,
                status: 409,
                body: {
                    detail: {
                        reason: "BOT_STOP_FAILED",
                    },
                },
            });
        }

        return jsonResponse({
            body: {
                success: true,
                unlocked: true,
            },
        });
    });
    const lockedStatus = emergencyStatus("LOCKED");

    try {
        const renderer = await renderBotControl({
            emergency: lockedStatus,
            emergencyLocked: true,
            emergencyState: "LOCKED",
            onStatusRefresh: async () => ({
                emergencyLocked: attempt > 1 ? false : true,
                emergencyState: attempt > 1 ? "READY" : "LOCKED",
                loopEnabled: false,
                autoTradeEnabled: false,
                executionEnabled: false,
            }),
        });

        await clickAndRender(
            renderer,
            findButton(renderer.root, "通常に戻す"),
        );
        renderer.render();

        assert.equal(mock.requests.length, 1);
        assert.equal(textIncludes(renderer.root, "緊急状態を解除できません"), true);
        assert.equal(findButton(renderer.root, "通常に戻す").props.disabled, false);

        await clickAndRender(
            renderer,
            findButton(renderer.root, "通常に戻す"),
        );
        renderer.render();

        assert.equal(mock.requests.length, 2);
        assert.equal(textIncludes(renderer.root, "緊急状態を解除できません"), false);
    } finally {
        mock.restore();
    }
});

test("Status mismatch is reported without enabling trading locally", async () => {
    const mock = installFetchMock(() => jsonResponse({
        body: {
            success: true,
            unlocked: true,
        },
    }));

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("LOCKED"),
            emergencyLocked: true,
            emergencyState: "LOCKED",
            onStatusRefresh: async () => ({
                emergencyLocked: false,
                emergencyState: "READY",
                loopEnabled: true,
                autoTradeEnabled: false,
                executionEnabled: false,
            }),
        });

        await clickAndRender(
            renderer,
            findButton(renderer.root, "通常に戻す"),
        );
        renderer.render();

        assert.equal(textIncludes(renderer.root, "解除後の安全状態を確認できません"), true);
        assert.equal(findButton(renderer.root, "通常に戻す").props.disabled, false);
    } finally {
        mock.restore();
    }
});


test("Preparation boundary receives configured values and preserves unknown Emergency authority", async () => {
    const renderer = await renderBotControl({
        emergency: null,
        emergencyLocked: undefined,
        emergencyState: undefined,
        config: { mode: "PAPER", symbol: "XRPUSDTM", displaySymbol: "BTCUSDTM", selectionMode: "AUTO", risk_percent: 1.25, leverage: 5 },
    });
    const preparation = renderer.componentElements.find((element) => (
        element.type?.name === "OperationPreparation"
    ));
    assert.ok(preparation);
    assert.equal(preparation.props.config.displaySymbol, "BTCUSDTM");
    assert.equal(preparation.props.emergencyState, "STATE_UNKNOWN");
    assert.equal(preparation.props.mmRuntime, "RUNNING");
    assert.equal(preparation.props.lifecycleState, "RUNNING");
    assert.equal(preparation.props.capitalAuthorityStatus, "AVAILABLE");
    assert.equal(preparation.props.availableCapital, "10000");
    assert.equal(preparation.props.riskBudget, "50");
    assert.equal(preparation.props.executionEntryAllowed, true);
    assert.equal(preparation.props.recommendedAction, "CONTINUE");
    assert.equal(preparation.props.riskState, "NORMAL");
    assert.equal(textIncludes(renderer.root, "START BOT"), true);
});

test("START BOT uses existing lifecycle authority and prevents duplicate requests", async () => {
    const response = deferred();
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return response.promise;
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps());
        const first = clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        renderer.render();
        const pending = findButton(renderer.root, "STARTING...");
        assert.ok(pending);
        assert.equal(pending.props.disabled, true);
        pending.props.onClick();
        assert.equal(mock.requests.length, 1);
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.mode, "paper");
        assert.equal(payload.leverage, 5);
        response.resolve(jsonResponse({ body: { success: true, status: "started" } }));
        await first;
    } finally { clearMmConfiguration(); mock.restore(); }
});

test("START payload uses the single effective selectionMode source", async () => {
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    setMmConfiguration();
    try {
        const manualRenderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL" },
        }));
        await clickAndRender(manualRenderer, findButton(manualRenderer.root, "START BOT"));
        assert.equal(JSON.parse(mock.requests[0].options.body).selection_mode, "MANUAL");
        assert.equal(JSON.parse(mock.requests[0].options.body).symbol, "XRPUSDTM");

        const autoRenderer = await renderBotControl(readyStartProps({
            config: { 
                selectionMode: "AUTO", 
                displaySymbol: "BTCUSDTM",
                autoMarketState: "READY"  // 确保自动选择状态为READY
            },
        }));
        await clickAndRender(autoRenderer, findButton(autoRenderer.root, "START BOT"));
        assert.equal(JSON.parse(mock.requests[1].options.body).selection_mode, "AUTO");
        assert.equal(JSON.parse(mock.requests[1].options.body).symbol, "BTCUSDTM");
        assert.notEqual(JSON.parse(mock.requests[1].options.body).symbol, "XRPUSDTM");
    } finally { clearMmConfiguration(); mock.restore(); }
});

test("polling rerender keeps AUTO display, runtime symbol, and START payload aligned", async () => {
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", symbol: "XRPUSDTM" },
        }));

        renderer.render(readyStartProps({
            config: {
                selectionMode: "AUTO",
                symbol: "XRPUSDTM",
                displaySymbol: "YGGUSDT",
                autoMarketState: "READY",
                paperBootstrapEligible: true,
            },
        }));

        assert.equal(textIncludes(renderer.root, "AUTO"), true);
        assert.equal(textIncludes(renderer.root, "YGGUSDT"), true);
        const start = findButton(renderer.root, "START BOT");
        assert.equal(start.props.disabled, false);
        await clickAndRender(renderer, start);

        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.selection_mode, "AUTO");
        assert.equal(payload.symbol, "YGGUSDT");
        assert.notEqual(payload.symbol, "XRPUSDTM");
    } finally { clearMmConfiguration(); mock.restore(); }
});

test("START blocks over-limit leverage without clamping the payload", async () => {
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    setMmConfiguration({ maximumLeverage: "5" });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { leverage: 10 },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 0);
    } finally { clearMmConfiguration(); mock.restore(); }
});

test("unsaved MM draft maximum cannot authorize START", async () => {
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    setMmConfiguration({ maximumLeverage: "5" });
    globalThis.__MM_DRAFT__ = { maximumLeverage: "10" };
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { leverage: 10 },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 0);
    } finally {
        clearMmConfiguration();
        clearMmDraft();
        mock.restore();
    }
});

test("START payload risk_percent uses saved MM configuration, ignoring legacy config and MM draft", async () => {
    setMmConfiguration({ riskPerTradePercent: "2.00" });
    globalThis.__MM_DRAFT__ = { riskPerTradePercent: "3.00", totalExposurePercent: "20.00", maximumDrawdownPercent: "5.00" };
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", risk_percent: 2.5 },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.risk_percent, 2);
    } finally {
        mock.restore();
        clearMmConfiguration();
        clearMmDraft();
    }
});

test("START payload risk_percent is 0.50 when saved MM risk is 0.50", async () => {
    setMmConfiguration({ riskPerTradePercent: "0.50" });
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    try {
        const renderer = await renderBotControl(readyStartProps());
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.risk_percent, 0.5);
    } finally {
        mock.restore();
        clearMmConfiguration();
    }
});

test("START payload risk_percent is 0.75 when saved MM risk is 0.75", async () => {
    setMmConfiguration({ riskPerTradePercent: "0.75" });
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    try {
        const renderer = await renderBotControl(readyStartProps());
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.risk_percent, 0.75);
    } finally {
        mock.restore();
        clearMmConfiguration();
    }
});

test("START payload risk_percent uses saved MM risk over unsaved draft", async () => {
    setMmConfiguration({ riskPerTradePercent: "0.50" });
    globalThis.__MM_DRAFT__ = { riskPerTradePercent: "0.75", totalExposurePercent: "20.00", maximumDrawdownPercent: "5.00" };
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    try {
        const renderer = await renderBotControl(readyStartProps());
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.risk_percent, 0.5);
    } finally {
        mock.restore();
        clearMmConfiguration();
        clearMmDraft();
    }
});

test("START payload risk_percent uses saved MM risk over legacy config risk_percent", async () => {
    setMmConfiguration({ riskPerTradePercent: "0.50" });
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", risk_percent: 1 },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.risk_percent, 0.5);
    } finally {
        mock.restore();
        clearMmConfiguration();
    }
});

test("START fails closed when saved MM risk is unavailable", async () => {
    setMmConfiguration({ riskPerTradePercent: undefined });
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    try {
        const renderer = await renderBotControl(readyStartProps());
        const start = findButton(renderer.root, "START BOT");
        assert.ok(start);
        assert.equal(start.props.disabled, true);
        await clickAndRender(renderer, start);
        assert.equal(mock.requests.length, 0);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("START payload max_drawdown_pct uses saved MM maximumDrawdownPercent, ignoring legacy config.maxDd", async () => {
    setMmConfiguration({ maximumDrawdownPercent: "7.00", riskPerTradePercent: "0.50" });
    globalThis.__MM_DRAFT__ = {
        riskPerTradePercent: "0.50",
        totalExposurePercent: "20.00",
        maximumDrawdownPercent: "10.00",
    };
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", maxDd: 3 },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.max_drawdown_pct, 7);
    } finally {
        mock.restore();
        clearMmConfiguration();
        clearMmDraft();
    }
});

test("START payload max_drawdown_pct uses saved MM configuration over unsaved draft", async () => {
    setMmConfiguration({ maximumDrawdownPercent: "5.00", riskPerTradePercent: "0.50" });
    globalThis.__MM_DRAFT__ = {
        riskPerTradePercent: "0.50",
        totalExposurePercent: "20.00",
        maximumDrawdownPercent: "15.00",
    };
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", maxDd: 10 },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.max_drawdown_pct, 5);
    } finally {
        mock.restore();
        clearMmConfiguration();
        clearMmDraft();
    }
});

test("START fails closed when saved MM maximumDrawdownPercent is unavailable", async () => {
    setMmConfiguration({ riskPerTradePercent: "0.50", maximumDrawdownPercent: undefined });
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    try {
        const renderer = await renderBotControl(readyStartProps());
        const start = findButton(renderer.root, "START BOT");
        assert.ok(start);
        assert.equal(start.props.disabled, true);
        await clickAndRender(renderer, start);
        assert.equal(mock.requests.length, 0);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("START fails closed when saved MM maximumDrawdownPercent is NaN", async () => {
    setMmConfiguration({ riskPerTradePercent: "0.50", maximumDrawdownPercent: "not-a-number" });
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    try {
        const renderer = await renderBotControl(readyStartProps());
        const start = findButton(renderer.root, "START BOT");
        await clickAndRender(renderer, start);
        assert.equal(mock.requests.length, 0);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("START payload risk_percent, leverage, selection_mode contracts preserved alongside max_drawdown_pct authority", async () => {
    setMmConfiguration({
        riskPerTradePercent: "0.50",
        maximumDrawdownPercent: "7.00",
        maximumLeverage: "5",
    });
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started" } });
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", maxDd: 3, leverage: 5 },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.risk_percent, 0.5);
        assert.equal(payload.max_drawdown_pct, 7);
        assert.equal(payload.leverage, 5);
        assert.equal(payload.selection_mode, "MANUAL");
    } finally {
        mock.restore();
        clearMmConfiguration();
    }
});

test("START does not fallback to default 5 when saved MM max drawdown is unavailable", async () => {
    setMmConfiguration({ riskPerTradePercent: "0.50", maximumDrawdownPercent: undefined });
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL" },
        }));
        const start = findButton(renderer.root, "START BOT");
        assert.equal(start.props.disabled, true);
        await clickAndRender(renderer, start);
        assert.equal(mock.requests.length, 0);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("running BOT presents STOP BOT and uses existing stop authority", async () => {
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/stop");
        return jsonResponse({ body: { success: true, status: "stopped" } });
    });
    try {
        const renderer = await renderBotControl({ botRunning: true, loopEnabled: true });
        await clickAndRender(renderer, findButton(renderer.root, "STOP BOT"));
        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].options.method, "POST");
    } finally { mock.restore(); }
});


test("BotControl delegates preparation UI and preserves the sole Start Bot action", async () => {
    const renderer = await renderBotControl({
        config: { mode: "PAPER", symbol: "XRPUSDTM", selectionMode: "MANUAL", risk_percent: 1, leverage: 5 },
    });
    const preparation = renderer.componentElements.filter((element) => (
        element.type?.name === "OperationPreparation"
    ));
    assert.equal(preparation.length, 1);
    assert.equal(findAll(renderer.root, (element) => collectText(element) === "START BOT").length, 1);
});

test("stopped BOT exposes no active Loop or Auto Trade mutation control", async () => {
    const renderer = await renderBotControl({ botRunning: false, loopEnabled: false, executionEnabled: false });
    const runtimeLoopGroup = findGroupButton(renderer.root, "Runtime loop", "ON");
    const runtimeAutoTradeGroup = findGroupButton(renderer.root, "Runtime auto trade", "ON");
    assert.equal(runtimeLoopGroup, null);
    assert.equal(runtimeAutoTradeGroup, null);
    assert.equal(textIncludes(renderer.root, "RUNTIME LOOP（実行中ループ）"), false);
    assert.equal(textIncludes(renderer.root, "RUNTIME AUTO TRADE（実行中自動取引）"), false);
    assert.equal(textIncludes(renderer.root, "EMERGENCY STOP"), true);
});

test("running BOT exposes Loop and Auto Trade controls in AUTOMATION section", async () => {
    const renderer = await renderBotControl({ botRunning: true, loopEnabled: true, executionEnabled: false });
    // Preparation-only settings remain; runtime controls appear only while running
    assert.equal(textIncludes(renderer.root, "LOOP ON START"), true);
    assert.equal(textIncludes(renderer.root, "AUTO TRADE ON START"), true);
    assert.equal(textIncludes(renderer.root, "RUNTIME LOOP（実行中ループ）"), true);
    assert.equal(textIncludes(renderer.root, "RUNTIME AUTO TRADE（実行中自動取引）"), true);
    assert.equal(textIncludes(renderer.root, "EMERGENCY STOP"), true);
});

test("running BOT Runtime Loop control reaches the existing loop handler", async () => {
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/loop/start");
        return jsonResponse({ body: { status: "started" } });
    });

    try {
        const renderer = await renderBotControl({
            botRunning: true,
            loopEnabled: false,
            loopState: "STOPPED",
        });
        const onButton = findGroupButton(renderer.root, "Runtime loop", "ON");
        assert.ok(onButton);
        assert.equal(onButton.props.disabled, false);

        clickAndRender(renderer, onButton);
        await new Promise((resolve) => setTimeout(resolve, 0));

        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].url, "/api/bot/loop/start");
        assert.equal(mock.requests[0].options.method, "POST");
    } finally {
        mock.restore();
    }
});

test("running BOT Runtime Loop stop reaches the existing loop handler", async () => {
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/loop/stop");
        return jsonResponse({ body: { status: "stopped" } });
    });

    try {
        const renderer = await renderBotControl({
            botRunning: true,
            loopEnabled: true,
            loopState: "RUNNING",
        });
        const offButton = findGroupButton(renderer.root, "Runtime loop", "OFF");
        assert.ok(offButton);
        assert.equal(offButton.props.disabled, false);

        clickAndRender(renderer, offButton);
        await new Promise((resolve) => setTimeout(resolve, 0));

        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].url, "/api/bot/loop/stop");
        assert.equal(mock.requests[0].options.method, "POST");
    } finally {
        mock.restore();
    }
});

test("running BOT Runtime Auto Trade reaches the existing Governance handler", async () => {
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/governance/execution");
        return jsonResponse({ body: { success: true, execution_enabled: true } });
    });

    try {
        const renderer = await renderBotControl({
            botRunning: true,
            loopEnabled: true,
            executionEnabled: false,
        });
        const onButton = findGroupButton(renderer.root, "Runtime auto trade", "ON");
        assert.ok(onButton);
        assert.equal(onButton.props.disabled, false);

        clickAndRender(renderer, onButton);
        await new Promise((resolve) => setTimeout(resolve, 0));

        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].url, "/api/governance/execution");
        assert.equal(mock.requests[0].options.method, "POST");
        assert.equal(JSON.parse(mock.requests[0].options.body).enabled, true);
    } finally {
        mock.restore();
    }
});

test("START BOT is enabled when MM, Emergency, and remaining readiness are READY", async () => {
    setMmStatus({ executionEntryAllowed: true });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps());
        const start = findButton(renderer.root, "START BOT");
        assert.ok(start);
        assert.equal(start.props.disabled, false);
    } finally {
        clearMmStatus();
        clearMmConfiguration();
    }
});

test("START BOT is disabled when MM is WAITING", async () => {
    setMmStatus({
        executionEntryAllowed: false,
        recommendedAction: "HOLD_NEW_ENTRIES",
        riskState: "CAUTION",
    });
    try {
        const renderer = await renderBotControl(readyStartProps());
        assert.equal(findButton(renderer.root, "START BOT").props.disabled, true);
    } finally {
        clearMmStatus();
    }
});

test("START BOT is disabled when MM is UNKNOWN", async () => {
    setMmStatus({ executionEntryAllowed: undefined });
    try {
        const renderer = await renderBotControl(readyStartProps());
        assert.equal(findButton(renderer.root, "START BOT").props.disabled, true);
    } finally {
        clearMmStatus();
    }
});

test("PAPER START is enabled while runtime-only MM authority waits and entry stays waiting", async () => {
    setMmStatus({
        executionEntryAllowed: false,
        recommendedAction: "UNKNOWN",
        riskState: "UNKNOWN",
        blockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps());
        assert.equal(findButton(renderer.root, "START BOT").props.disabled, false);
        assert.equal(textIncludes(renderer.root, "START READINESS READY"), true);
        assert.equal(textIncludes(renderer.root, "ENTRY READINESS WAITING"), true);
    } finally {
        clearMmStatus();
        clearMmConfiguration();
    }
});

test("PAPER runtime-only MM wait starts Bot without starting automation", async () => {
    setMmStatus({
        executionEntryAllowed: false,
        recommendedAction: "UNKNOWN",
        riskState: "UNKNOWN",
        blockReasons: ["TRADING_RUNTIME_METRICS_UNAVAILABLE"],
    });
    setMmConfiguration();
    const mock = installFetchMock((url) => {
        if (url === "/api/bot/start") {
            return jsonResponse({ body: { status: "started" } });
        }
        throw new Error(`Unexpected request: ${url}`);
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", loopOnStart: true, autoTradeOnStart: true },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.deepEqual(mock.requests.map((request) => request.url), ["/api/bot/start"]);
    } finally {
        mock.restore();
        clearMmStatus();
        clearMmConfiguration();
    }
});

test("START BOT is disabled when Emergency is BLOCKED", async () => {
    const renderer = await renderBotControl(readyStartProps({
        emergency: emergencyStatus("LOCKED"),
        emergencyLocked: true,
        emergencyState: "LOCKED",
    }));
    assert.equal(findButton(renderer.root, "START BOT").props.disabled, true);
});

test("START BOT is disabled while a start request is pending", async () => {
    const response = deferred();
    const mock = installFetchMock(() => response.promise);
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps());
        clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        renderer.render();
        const pending = findButton(renderer.root, "STARTING...");
        assert.ok(pending);
        assert.equal(pending.props.disabled, true);
        response.resolve(jsonResponse({ body: { status: "started" } }));
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("START handler reaches START action when startReady is READY", async () => {
    const response = deferred();
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return response.promise;
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps());
        const first = clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].url, "/api/bot/start");
        response.resolve(jsonResponse({ body: { status: "started" } }));
        await first;
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("START handler is blocked when readiness is WAITING", async () => {
    setMmStatus({
        executionEntryAllowed: false,
        recommendedAction: "HOLD_NEW_ENTRIES",
        riskState: "CAUTION",
    });
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    try {
        const renderer = await renderBotControl(readyStartProps());
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 0);
    } finally {
        clearMmStatus();
        mock.restore();
    }
});

test("START handler is blocked when MM is UNKNOWN", async () => {
    setMmStatus({ executionEntryAllowed: undefined });
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    try {
        const renderer = await renderBotControl(readyStartProps());
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 0);
    } finally {
        clearMmStatus();
        mock.restore();
    }
});

test("START handler is blocked when Emergency blocks operations", async () => {
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            emergency: emergencyStatus("LOCKED"),
            emergencyLocked: true,
            emergencyState: "LOCKED",
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 0);
    } finally {
        mock.restore();
    }
});

test("STOP handler remains available when startReady is false", async () => {
    setMmStatus({
        executionEntryAllowed: false,
        recommendedAction: "HOLD_NEW_ENTRIES",
        riskState: "CAUTION",
    });
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/stop");
        return jsonResponse({ body: { success: true, status: "stopped" } });
    });
    try {
        const renderer = await renderBotControl({
            botRunning: true,
            loopEnabled: true,
        });
        const stop = findButton(renderer.root, "STOP BOT");
        assert.ok(stop);
        assert.equal(stop.props.disabled, false);
        await clickAndRender(renderer, stop);
        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].url, "/api/bot/stop");
    } finally {
        clearMmStatus();
        mock.restore();
    }
});

test("L1: Loop on Start OFF triggers no Loop activation after START success", async () => {
    const mock = installFetchMock((url) => {
        if (url === "/api/bot/start") return jsonResponse({ body: { status: "started" } });
        throw new Error(`Unexpected request: ${url}`);
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL" },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].url, "/api/bot/start");
        assert.equal(mock.requests.filter((request) => request.url === "/api/bot/loop/start").length, 0);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("L2: Loop on Start ON invokes the existing Loop authority exactly once after START success", async () => {
    const mock = installFetchMock((url) => {
        if (url === "/api/bot/start") return jsonResponse({ body: { status: "started", loopState: "RUNNING" } });
        if (url === "/api/bot/loop/start") return jsonResponse({ body: { status: "started" } });
        throw new Error(`Unexpected request: ${url}`);
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", loopOnStart: true },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests[0].url, "/api/bot/start");
        const loopRequests = mock.requests.filter((request) => request.url === "/api/bot/loop/start");
        assert.equal(loopRequests.length, 0);
        assert.equal(JSON.parse(mock.requests[0].options.body).loop_on_start, true);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("L3: Loop on Start ON does not activate Loop when START fails", async () => {
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ ok: false, status: 400, body: { reason: "START_REJECTED" } });
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", loopOnStart: true },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        renderer.render();
        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests.filter((request) => request.url === "/api/bot/loop/start").length, 0);
        assert.equal(textIncludes(renderer.root, "START failed"), true);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("L4: Loop on Start activation failure surfaces a truthful error without fake enabled state", async () => {
    const mock = installFetchMock((url) => {
        if (url === "/api/bot/start") return jsonResponse({ ok: false, status: 400, body: { reason: "LOOP_BLOCKED_BY_EMERGENCY_LOCK" } });
        throw new Error(`Unexpected request: ${url}`);
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", loopOnStart: true },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        renderer.render();
        assert.equal(textIncludes(renderer.root, "START failed"), true);
        assert.equal(mock.requests.filter((request) => request.url === "/api/bot/loop/start").length, 0);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("AT1: Auto Trade on Start OFF triggers no Auto Trade activation after START success", async () => {
    const mock = installFetchMock((url) => {
        if (url === "/api/bot/start") return jsonResponse({ body: { status: "started" } });
        throw new Error(`Unexpected request: ${url}`);
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL" },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.filter((request) => request.url === "/api/governance/execution").length, 0);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("AT2: Auto Trade on Start ON invokes the existing Governance authority exactly once after START success", async () => {
    const mock = installFetchMock((url) => {
        if (url === "/api/bot/start") return jsonResponse({ body: { status: "started", loopState: "RUNNING", autoTradeEnabled: true } });
        throw new Error(`Unexpected request: ${url}`);
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", loopOnStart: true, autoTradeOnStart: true },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        const autoTradeRequests = mock.requests.filter((request) => request.url === "/api/governance/execution");
        assert.equal(autoTradeRequests.length, 0);
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.loop_on_start, true);
        assert.equal(payload.auto_trade_on_start, true);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("AT3: Auto Trade on Start ON does not activate when START fails", async () => {
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ ok: false, status: 400, body: { reason: "START_REJECTED" } });
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", autoTradeOnStart: true },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.filter((request) => request.url === "/api/governance/execution").length, 0);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("AT4: Auto Trade on Start activation failure surfaces a truthful error without fake enabled state", async () => {
    const mock = installFetchMock((url) => {
        if (url === "/api/bot/start") return jsonResponse({ ok: false, status: 400, body: { reason: "AUTO_TRADE_REQUIRES_LOOP_ON" } });
        throw new Error(`Unexpected request: ${url}`);
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", autoTradeOnStart: true },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        renderer.render();
        assert.equal(textIncludes(renderer.root, "START failed"), true);
        assert.equal(mock.requests.filter((request) => request.url === "/api/governance/execution").length, 0);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("AT5: Auto Trade on Start cannot bypass the MM readiness gate", async () => {
    setMmStatus({
        executionEntryAllowed: false,
        recommendedAction: "HOLD_NEW_ENTRIES",
        riskState: "CAUTION",
    });
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", autoTradeOnStart: true },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 0);
    } finally {
        clearMmStatus();
        mock.restore();
    }
});

test("Sequencing: START succeeds, then Loop, then Auto Trade in deterministic order", async () => {
    const mock = installFetchMock((url) => {
        if (url === "/api/bot/start") return jsonResponse({ body: { status: "started", loopState: "RUNNING", autoTradeEnabled: true } });
        throw new Error(`Unexpected request: ${url}`);
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { 
                selectionMode: "AUTO", 
                displaySymbol: "BTCUSDTM", 
                loopOnStart: true, 
                autoTradeOnStart: true,
                autoMarketState: "READY"  // 确保自动选择状态为READY
            },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].url, "/api/bot/start");
        assert.equal(JSON.parse(mock.requests[0].options.body).selection_mode, "AUTO");
        assert.equal(JSON.parse(mock.requests[0].options.body).loop_on_start, true);
        assert.equal(JSON.parse(mock.requests[0].options.body).auto_trade_on_start, true);
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("START lifecycle stays single-flight while automation is applied", async () => {
    const response = deferred();
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return response.promise;
    });
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { selectionMode: "MANUAL", loopOnStart: true, autoTradeOnStart: true },
        }));
        const first = clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        renderer.render();
        const pending = findButton(renderer.root, "STARTING...");
        assert.ok(pending);
        assert.equal(pending.props.disabled, true);
        pending.props.onClick();
        assert.equal(mock.requests.length, 1);
        response.resolve(jsonResponse({ body: { status: "started" } }));
        await first;
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});

test("BotControl reuses shared readiness without re-implementing MM readiness", async () => {
    const source = await readFile(sourceUrl, "utf8");
    assert.doesNotMatch(source, /deriveMmReadiness|deriveReviewReadiness/);
    assert.match(source, /deriveOperationReadiness/);
    assert.match(source, /startReady/);
    assert.match(source, /leverage: startSettings\.requestedLeverage/);
    assert.doesNotMatch(source, /leverage: config\?\.leverage|leverage: .*\?\? 5/);
});

test("LIVE authority denied keeps trigger enabled and disables modal confirm", async () => {
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: {
                mode: "live",
                dryRun: false,
                allowLive: false,
                tradeMode: "paper",
            },
        }));
        const start = findButton(renderer.root, "START BOT");
        assert.ok(start);
        assert.equal(start.props.disabled, false);
        await clickAndRender(renderer, start);
        assert.equal(textIncludes(renderer.root, "START READINESS: BLOCKED"), true);
        assert.equal(textIncludes(renderer.root, "LIVE AUTHORITY: BLOCKED"), true);
        assert.equal(findButton(renderer.root, "LIVEを開始").props.disabled, true);
    } finally {
        clearMmConfiguration();
    }
});

test("LIVE authority unknown keeps trigger enabled and fails closed in modal", async () => {
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: {
                mode: "live",
                dryRun: false,
                allowLive: undefined,
                tradeMode: undefined,
            },
        }));
        const start = findButton(renderer.root, "START BOT");
        assert.ok(start);
        assert.equal(start.props.disabled, false);
        await clickAndRender(renderer, start);
        assert.equal(findButton(renderer.root, "LIVEを開始").props.disabled, true);
    } finally {
        clearMmConfiguration();
    }
});

test("LIVE WAITING keeps trigger enabled and disables modal confirm", async () => {
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: {
                mode: "live",
                dryRun: false,
                allowLive: true,
                tradeMode: "live",
                selectionMode: "AUTO",
                autoMarketState: "READY",
                displaySymbol: null,
                leverage: 5,
            },
        }));
        const start = findButton(renderer.root, "START BOT");
        assert.equal(start.props.disabled, false);
        await clickAndRender(renderer, start);
        assert.equal(textIncludes(renderer.root, "START READINESS: WAITING"), true);
        assert.equal(textIncludes(renderer.root, "MARKET SELECTION: WAITING"), true);
        assert.equal(findButton(renderer.root, "LIVEを開始").props.disabled, true);
    } finally {
        clearMmConfiguration();
    }
});

test("DASH4A: LIVE explicitly authorized enables START BOT", async () => {
    setMmConfiguration();
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: {
                mode: "live",
                dryRun: false,
                allowLive: true,
                tradeMode: "live",
            },
        }));
        const start = findButton(renderer.root, "START BOT");
        assert.ok(start);
        assert.equal(start.props.disabled, false);
        await clickAndRender(renderer, start);
        assert.equal(findButton(renderer.root, "LIVEを開始").props.disabled, false);
    } finally {
        clearMmConfiguration();
    }
});


test("all trade/execution controls send distinct nondefault values through the single START payload", async () => {
    setMmConfiguration({ riskPerTradePercent: "0.75", maximumDrawdownPercent: "7.00" });
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({ body: { status: "started", loopState: "RUNNING", autoTradeEnabled: true } });
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: {
                selectionMode: "MANUAL", symbol: "ETHUSDTM", exchange: "KUCOIN",
                leverage: 4, positionSize: 75, sl: 1.5, tp: 3,
                timeframe: "15m", trailing: true, loopOnStart: true,
                autoTradeOnStart: true,
            },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(mock.requests.length, 1);
        assert.deepEqual(JSON.parse(mock.requests[0].options.body), {
            symbol: "ETHUSDTM", selection_mode: "MANUAL", exchange: "kucoin",
            risk_percent: 0.75, position_size: 75, max_drawdown_pct: 7,
            sl_percent: 1.5, leverage: 4, timeframe: "15m", tp_percent: 3,
            trailing_stop: true, dry_run: true, mode: "paper",
            loop_on_start: true, auto_trade_on_start: true,
        });
    } finally {
        clearMmConfiguration();
        mock.restore();
    }
});


test("LIVE DISARMED confirm sends one START and forces Loop/Auto OFF", async () => {
    setMmStatus({ executionEntryAllowed: false });
    setMmConfiguration();
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/bot/start");
        return jsonResponse({
            body: {
                status: "started",
                loopState: "STOPPED",
                autoTradeEnabled: false,
            },
        });
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: {
                mode: "live",
                allowLive: true,
                tradeMode: "live",
                loopOnStart: false,
                autoTradeOnStart: false,
            },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        assert.equal(textIncludes(renderer.root, "LIVE runtimeをDISARMEDで開始します。"), true);
        assert.equal(textIncludes(renderer.root, "Real Order Authority: DISABLED"), true);
        assert.equal(textIncludes(renderer.root, "Loop / Auto Trade: OFF / OFF"), true);
        const confirm = findButton(renderer.root, "LIVEを開始");
        assert.equal(confirm.props.disabled, false);
        await clickAndRender(renderer, confirm);
        assert.equal(mock.requests.length, 1);
        const payload = JSON.parse(mock.requests[0].options.body);
        assert.equal(payload.mode, "live");
        assert.equal(payload.dry_run, false);
        assert.equal(payload.loop_on_start, false);
        assert.equal(payload.auto_trade_on_start, false);
    } finally {
        clearMmStatus();
        clearMmConfiguration();
        mock.restore();
    }
});

test("LIVE DISARMED modal cancel sends no START", async () => {
    setMmStatus({ executionEntryAllowed: false });
    setMmConfiguration();
    const mock = installFetchMock(() => {
        throw new Error("START must not be sent");
    });
    try {
        const renderer = await renderBotControl(readyStartProps({
            config: { mode: "live", allowLive: true, tradeMode: "live" },
        }));
        await clickAndRender(renderer, findButton(renderer.root, "START BOT"));
        await clickAndRender(renderer, findButton(renderer.root, "キャンセル"));
        assert.equal(mock.requests.length, 0);
    } finally {
        clearMmStatus();
        clearMmConfiguration();
        mock.restore();
    }
});
