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

        await writeFile(
            apiMockFile,
            [
                "export const API = {",
                "  botStart: () => '/api/bot/start',",
                "  botStop: () => '/api/bot/stop',",
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

const findLastButton = (
    root,
    matcher
) => {
    const predicate = typeof matcher === "string"
        ? (name) => name.includes(matcher)
        : matcher;
    const matches = buttons(root).filter(
        (button) => predicate(buttonName(button), button)
    );

    return matches[matches.length - 1] || null;
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

        const previousDispatcher = internals.H;
        internals.H = dispatcher;

        try {
            root = Component(currentProps);
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

const mutatedLastResult = (
    mutation
) => {
    const result = lastResult();
    mutation(result);
    return result;
};

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
        },
        executionEnabled: false,
        botRunning: false,
        loopEnabled: false,
        loopState: "STOPPED",
        emergencyLocked: emergency.locked,
        emergencyState: emergency.state,
        emergency,
        pendingOrder: false,
        onStatusRefresh: async () => undefined,
        setExecutionEnabledState: () => undefined,
        ...overrides,
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

const emergencyApiResponse = (
    overrides = {}
) => ({
    success: true,
    completed: true,
    partial: false,
    state_unknown: false,
    emergency_locked: true,
    auto_trade_disabled: true,
    execution_path: "paper",
    symbol: "XRPUSDT",
    cancel: null,
    flatten: {
        success: true,
        skipped: true,
    },
    position_remaining: false,
    retryable: false,
    error_code: null,
    ...overrides,
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
        ["READY", true],
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

        assert.ok(returnButton, state);
        assert.equal(returnButton.props.disabled, expectedDisabled, state);
        assert.equal(findButton(renderer.root, "安全状態を再確認"), null);
        assert.equal(textIncludes(renderer.root, "再確認中..."), false);
    }
});

test("Emergency confirmation cancel sends no request", async () => {
    const mock = installFetchMock(() => {
        throw new Error("No request expected");
    });

    try {
        const renderer = await renderBotControl();
        await clickAndRender(
            renderer,
            findButton(renderer.root, "EMERGENCY STOP"),
        );
        await clickAndRender(
            renderer,
            findButton(renderer.root, "CANCEL"),
        );

        assert.equal(mock.requests.length, 0);
    } finally {
        mock.restore();
    }
});

test("Emergency confirmation sends one orchestrate request and refreshes", async () => {
    let refreshCount = 0;
    const mock = installFetchMock((url) => {
        assert.equal(url, "/api/governance/emergency-orchestrate");
        return jsonResponse({
            body: emergencyApiResponse(),
        });
    });

    try {
        const renderer = await renderBotControl({
            onStatusRefresh: async () => {
                refreshCount += 1;
            },
        });
        await clickAndRender(
            renderer,
            findButton(renderer.root, "EMERGENCY STOP"),
        );
        await clickAndRender(
            renderer,
            findButton(renderer.root, "CONFIRM EMERGENCY"),
        );
        renderer.render();

        assert.equal(mock.requests.length, 1);
        assert.equal(mock.requests[0].options.method, "POST");
        assert.equal(refreshCount, 1);
    } finally {
        mock.restore();
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
