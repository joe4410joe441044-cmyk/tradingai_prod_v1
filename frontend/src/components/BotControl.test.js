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

test("BotControl shows Retry only for ACTION_REQUIRED", async () => {
    const cases = [
        ["ACTION_REQUIRED", true],
        ["READY", false],
        ["PROCESSING", false],
        ["LOCKED", false],
        [undefined, false],
        ["BROKEN_STATE", false],
    ];

    for (const [state, expectedVisible] of cases) {
        const emergency = state
            ? emergencyStatus(state, {
                lastResult: state === "ACTION_REQUIRED"
                    ? lastResult({
                        result: "PARTIAL",
                        success: false,
                        completed: false,
                        state: "ACTION_REQUIRED",
                        stateUnknown: true,
                    })
                    : state === "LOCKED"
                        ? lastResult()
                        : null,
            })
            : undefined;
        const renderer = await renderBotControl({
            emergency,
            emergencyLocked: emergency?.locked,
            emergencyState: state,
        });
        const retry = findButton(
            renderer.root,
            "安全状態を再確認",
        );

        assert.equal(Boolean(retry), expectedVisible, state || "missing");
    }
});

test("BotControl shows Normal disabled for ACTION_REQUIRED and enabled only when safe", async () => {
    const cases = [
        [
            "LOCKED / SUCCESS / safe",
            emergencyStatus("LOCKED"),
            false,
            true,
            true,
        ],
        [
            "ACTION_REQUIRED",
            emergencyStatus("ACTION_REQUIRED", {
                lastResult: lastResult({
                    result: "PARTIAL",
                    state: "ACTION_REQUIRED",
                    success: false,
                    completed: false,
                }),
            }),
            false,
            true,
            false,
        ],
        [
            "PROCESSING",
            emergencyStatus("PROCESSING"),
            false,
            false,
            false,
        ],
        [
            "READY",
            emergencyStatus("READY"),
            false,
            false,
            false,
        ],
        [
            "LOCKED / PARTIAL",
            emergencyStatus("LOCKED", {
                lastResult: lastResult({
                    result: "PARTIAL",
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "LOCKED / FAILED",
            emergencyStatus("LOCKED", {
                lastResult: lastResult({
                    result: "FAILED",
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "success=false",
            emergencyStatus("LOCKED", {
                lastResult: lastResult({
                    success: false,
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "completed=false",
            emergencyStatus("LOCKED", {
                lastResult: lastResult({
                    completed: false,
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "stateUnknown=true",
            emergencyStatus("LOCKED", {
                lastResult: lastResult({
                    stateUnknown: true,
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "stateUnknown missing",
            emergencyStatus("LOCKED", {
                lastResult: mutatedLastResult((result) => {
                    delete result.stateUnknown;
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "stateUnknown null",
            emergencyStatus("LOCKED", {
                lastResult: lastResult({
                    stateUnknown: null,
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "positionRemaining=true",
            emergencyStatus("LOCKED", {
                lastResult: lastResult({
                    positionRemaining: true,
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "positionRemaining missing",
            emergencyStatus("LOCKED", {
                lastResult: mutatedLastResult((result) => {
                    delete result.positionRemaining;
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "positionRemaining null",
            emergencyStatus("LOCKED", {
                lastResult: lastResult({
                    positionRemaining: null,
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "pendingOrder=true",
            emergencyStatus("LOCKED"),
            true,
            false,
            false,
        ],
        [
            "pendingOrder missing",
            emergencyStatus("LOCKED"),
            undefined,
            false,
            false,
        ],
        [
            "pendingOrder null",
            emergencyStatus("LOCKED"),
            null,
            false,
            false,
        ],
        [
            "pendingOrder non-bool",
            emergencyStatus("LOCKED"),
            {},
            false,
            false,
        ],
        [
            "success missing",
            emergencyStatus("LOCKED", {
                lastResult: mutatedLastResult((result) => {
                    delete result.success;
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "completed missing",
            emergencyStatus("LOCKED", {
                lastResult: mutatedLastResult((result) => {
                    delete result.completed;
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "operationId missing",
            emergencyStatus("LOCKED", {
                lastResult: mutatedLastResult((result) => {
                    delete result.operationId;
                }),
            }),
            false,
            false,
            false,
        ],
        [
            "lastResult missing",
            emergencyStatus("LOCKED", {
                lastResult: null,
            }),
            false,
            false,
            false,
        ],
    ];

    for (
        const [
            name,
            emergency,
            pendingOrder,
            expectedVisible,
            expectedEnabled,
        ] of cases
    ) {
        const renderer = await renderBotControl({
            emergency,
            emergencyLocked: emergency.locked,
            emergencyState: emergency.state,
            pendingOrder,
        });
        const unlock = findButton(
            renderer.root,
            "通常に戻る",
        );

        if (expectedVisible) {
            assert.ok(unlock, name);
            assert.equal(unlock.props.disabled, !expectedEnabled, name);
        } else {
            assert.equal(unlock, null, name);
        }
    }
});

test("Emergency confirm cancel sends no API request", async () => {
    const fetchMock = installFetchMock(() => {
        throw new Error("fetch should not be called");
    });

    try {
        const renderer = await renderBotControl();
        const emergency = findButton(
            renderer.root,
            "EMERGENCY STOP",
        );

        clickAndRender(
            renderer,
            emergency,
        );

        const cancel = findButton(
            renderer.root,
            "CANCEL",
        );

        clickAndRender(
            renderer,
            cancel,
        );

        assert.equal(fetchMock.requests.length, 0);
        assert.equal(
            findButton(renderer.root, "CONFIRM EMERGENCY"),
            null,
        );
    } finally {
        fetchMock.restore();
    }
});

test("Emergency confirm true sends one orchestrate POST without body", async () => {
    const fetchMock = installFetchMock(() => jsonResponse({
        body: emergencyApiResponse(),
    }));
    let refreshCount = 0;

    try {
        const renderer = await renderBotControl({
            onStatusRefresh: async () => {
                refreshCount += 1;
            },
        });
        clickAndRender(
            renderer,
            findButton(renderer.root, "EMERGENCY STOP"),
        );
        await clickAndRender(
            renderer,
            findButton(renderer.root, "CONFIRM EMERGENCY"),
        );
        renderer.render();

        assert.equal(fetchMock.requests.length, 1);
        assert.equal(
            fetchMock.requests[0].url,
            "/api/governance/emergency-orchestrate",
        );
        assert.equal(fetchMock.requests[0].options.method, "POST");
        assert.equal(
            Object.hasOwn(fetchMock.requests[0].options, "body"),
            false,
        );
        assert.equal(refreshCount, 1);
    } finally {
        fetchMock.restore();
    }
});

test("ACTION_REQUIRED shows fixed retry and disabled normal buttons", async () => {
    const fetchMock = installFetchMock(() => {
        throw new Error("fetch should not be called");
    });

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("ACTION_REQUIRED", {
                lastResult: lastResult({
                    result: "PARTIAL",
                    state: "ACTION_REQUIRED",
                    success: false,
                    completed: false,
                    stateUnknown: true,
                }),
            }),
            emergencyLocked: true,
            emergencyState: "ACTION_REQUIRED",
        });

        assert.equal(
            findButton(renderer.root, "安全状態を再確認").props.disabled,
            false,
        );
        assert.equal(
            findButton(renderer.root, "通常に戻る").props.disabled,
            true,
        );
        assert.equal(fetchMock.requests.length, 0);
        assert.equal(
            findButton(renderer.root, "キャンセル"),
            null,
        );
        assert.equal(
            findAll(
                renderer.root,
                (element) => (
                    element.props?.role === "dialog"
                    && element.props?.["aria-labelledby"]
                        === "emergency-retry-title"
                ),
            ).length,
            0,
        );
        assert.equal(
            buttons(renderer.root).filter(
                (button) => buttonName(button) === "再確認"
            ).length,
            0,
        );
    } finally {
        fetchMock.restore();
    }
});

test("Retry first click sends one retry POST and does not call unlock", async () => {
    const fetchMock = installFetchMock(() => jsonResponse({
        body: emergencyApiResponse(),
    }));
    let refreshCount = 0;
    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("ACTION_REQUIRED", {
                lastResult: lastResult({
                    result: "PARTIAL",
                    state: "ACTION_REQUIRED",
                    success: false,
                    completed: false,
                    stateUnknown: true,
                }),
            }),
            emergencyLocked: true,
            emergencyState: "ACTION_REQUIRED",
            onStatusRefresh: async () => {
                refreshCount += 1;
            },
        });

        await clickAndRender(
            renderer,
            findButton(renderer.root, "安全状態を再確認"),
        );

        assert.equal(fetchMock.requests.length, 1);
        assert.equal(
            fetchMock.requests[0].url,
            "/api/governance/emergency/retry",
        );
        assert.equal(fetchMock.requests[0].options.method, "POST");
        assert.notEqual(
            fetchMock.requests[0].url,
            "/api/governance/emergency/unlock",
        );
        assert.notEqual(
            fetchMock.requests[0].url,
            "/api/governance/emergency-orchestrate",
        );
        assert.equal(refreshCount, 1);
        assert.equal(
            textIncludes(
                renderer.root,
                "安全状態を確認できませんでした",
            ),
            false,
        );
    } finally {
        fetchMock.restore();
    }
});

test("Retry SNAPSHOT_STALE success refreshes status and reveals Unlock", async () => {
    const fetchMock = installFetchMock(() => jsonResponse({
        body: emergencyApiResponse(),
    }));
    let refreshCount = 0;
    let renderer;

    try {
        const staleEmergency = emergencyStatus("ACTION_REQUIRED", {
            lastResult: lastResult({
                result: "PARTIAL",
                state: "ACTION_REQUIRED",
                success: false,
                completed: false,
                partial: true,
                stateUnknown: true,
                retryable: true,
                message: "Emergency requires operator action: SNAPSHOT_STALE",
            }),
        });

        renderer = await renderBotControl({
            emergency: staleEmergency,
            emergencyLocked: true,
            emergencyState: "ACTION_REQUIRED",
            pendingOrder: true,
            onStatusRefresh: async () => {
                refreshCount += 1;
                renderer.render({
                    emergency: emergencyStatus("LOCKED"),
                    emergencyLocked: true,
                    emergencyState: "LOCKED",
                    pendingOrder: false,
                });
            },
        });

        assert.ok(textIncludes(renderer.root, "SNAPSHOT_STALE"));
        assert.ok(findButton(renderer.root, "安全状態を再確認"));
        assert.equal(
            findButton(renderer.root, "通常に戻る").props.disabled,
            true,
        );

        await clickAndRender(
            renderer,
            findButton(renderer.root, "安全状態を再確認"),
        );
        renderer.render();

        assert.equal(fetchMock.requests.length, 1);
        assert.equal(
            fetchMock.requests[0].url,
            "/api/governance/emergency/retry",
        );
        assert.equal(refreshCount, 1);
        assert.ok(textIncludes(renderer.root, "STOPPED SAFELY"));
        assert.equal(findButton(renderer.root, "安全状態を再確認"), null);
        assert.equal(
            findButton(renderer.root, "通常に戻る").props.disabled,
            false,
        );
    } finally {
        fetchMock.restore();
    }
});

test("Retry HTTP200 semantic failure shows error and never calls unlock", async () => {
    const fetchMock = installFetchMock(() => jsonResponse({
        body: emergencyApiResponse({
            success: false,
            completed: false,
            partial: true,
            state_unknown: true,
            retryable: true,
            error_code: "STATE_NOT_CONFIRMED",
        }),
    }));
    let refreshCount = 0;

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("ACTION_REQUIRED", {
                lastResult: lastResult({
                    result: "PARTIAL",
                    state: "ACTION_REQUIRED",
                    success: false,
                    completed: false,
                    stateUnknown: true,
                }),
            }),
            emergencyLocked: true,
            emergencyState: "ACTION_REQUIRED",
            onStatusRefresh: async () => {
                refreshCount += 1;
            },
        });

        await clickAndRender(
            renderer,
            findButton(renderer.root, "安全状態を再確認"),
        );
        renderer.render();

        assert.equal(fetchMock.requests.length, 1);
        assert.equal(
            fetchMock.requests[0].url,
            "/api/governance/emergency/retry",
        );
        assert.ok(textIncludes(renderer.root, "STATE_NOT_CONFIRMED"));
        assert.ok(textIncludes(
            renderer.root,
            "安全状態を確認できませんでした。状態を確認して再実行してください。",
        ));
        assert.equal(
            findButton(renderer.root, "安全状態を再確認").props.disabled,
            false,
        );
        assert.equal(
            findButton(renderer.root, "通常に戻る").props.disabled,
            true,
        );
        assert.equal(
            fetchMock.requests.filter(
                ({ url }) => url === "/api/governance/emergency/unlock"
            ).length,
            0,
        );
        assert.equal(refreshCount, 1);
    } finally {
        fetchMock.restore();
    }
});

test("Unlock confirm true sends one unlock POST after safe LOCKED state", async () => {
    const fetchMock = installFetchMock(() => jsonResponse({
        body: {
            success: true,
            unlocked: true,
            emergency_stop: false,
            emergency_state: "READY",
        },
    }));
    let refreshCount = 0;

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("LOCKED"),
            emergencyLocked: true,
            emergencyState: "LOCKED",
            pendingOrder: false,
            onStatusRefresh: async () => {
                refreshCount += 1;
            },
        });

        clickAndRender(
            renderer,
            findButton(renderer.root, "通常に戻る"),
        );
        await clickAndRender(
            renderer,
            findLastButton(renderer.root, "緊急状態を解除"),
        );

        assert.equal(fetchMock.requests.length, 1);
        assert.equal(
            fetchMock.requests[0].url,
            "/api/governance/emergency/unlock",
        );
        assert.equal(fetchMock.requests[0].options.method, "POST");
        assert.equal(refreshCount, 1);
    } finally {
        fetchMock.restore();
    }
});

test("Emergency double confirm keeps one in-flight request and disables controls", async () => {
    const pending = deferred();
    const fetchMock = installFetchMock(() => pending.promise);

    try {
        const renderer = await renderBotControl();
        clickAndRender(
            renderer,
            findButton(renderer.root, "EMERGENCY STOP"),
        );

        const confirm = findButton(
            renderer.root,
            "CONFIRM EMERGENCY",
        );
        const request = clickAndRender(
            renderer,
            confirm,
        );
        clickAndRender(
            renderer,
            confirm,
        );

        const loadingConfirm = findButton(
            renderer.root,
            "CONFIRM EMERGENCY",
        );
        assert.equal(fetchMock.requests.length, 1);
        assert.equal(loadingConfirm.props.disabled, true);

        pending.resolve(jsonResponse({
            body: emergencyApiResponse(),
        }));
        await request;
    } finally {
        fetchMock.restore();
    }
});

test("Retry double click keeps one request and disables controls while loading", async () => {
    const pending = deferred();
    const fetchMock = installFetchMock(() => pending.promise);

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("ACTION_REQUIRED", {
                lastResult: lastResult({
                    result: "PARTIAL",
                    state: "ACTION_REQUIRED",
                    success: false,
                    completed: false,
                    stateUnknown: true,
                }),
            }),
            emergencyLocked: true,
            emergencyState: "ACTION_REQUIRED",
        });

        const retry = findButton(
            renderer.root,
            "安全状態を再確認",
        );
        const request = clickAndRender(
            renderer,
            retry,
        );
        clickAndRender(
            renderer,
            retry,
        );

        assert.equal(fetchMock.requests.length, 1);
        assert.equal(
            findButton(renderer.root, "再確認中...").props.disabled,
            true,
        );
        assert.equal(
            findButton(renderer.root, "通常に戻る").props.disabled,
            true,
        );
        assert.equal(
            findButton(renderer.root, "EMERGENCY STOP").props.disabled,
            true,
        );

        pending.resolve(jsonResponse({
            body: emergencyApiResponse(),
        }));
        await request;
    } finally {
        fetchMock.restore();
    }
});

test("Unlock double confirm keeps one request and disables retry path", async () => {
    const pending = deferred();
    const fetchMock = installFetchMock(() => pending.promise);

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("LOCKED"),
            emergencyLocked: true,
            emergencyState: "LOCKED",
            pendingOrder: false,
        });

        clickAndRender(
            renderer,
            findButton(renderer.root, "通常に戻る"),
        );

        const confirm = findLastButton(
            renderer.root,
            "緊急状態を解除",
        );
        const request = clickAndRender(
            renderer,
            confirm,
        );
        clickAndRender(
            renderer,
            confirm,
        );

        assert.equal(fetchMock.requests.length, 1);
        assert.equal(
            findLastButton(renderer.root, "緊急状態を解除").props.disabled,
            true,
        );
        assert.equal(findButton(renderer.root, "安全状態を再確認"), null);

        pending.resolve(jsonResponse({
            body: {
                success: true,
                unlocked: true,
                emergency_stop: false,
                emergency_state: "READY",
            },
        }));
        await request;
    } finally {
        fetchMock.restore();
    }
});

test("Retry HTTP409 keeps ACTION_REQUIRED and Normal disabled", async () => {
    const fetchMock = installFetchMock(() => jsonResponse({
        ok: false,
        status: 409,
        body: {
            detail: {
                reason: "PROCESSING",
            },
        },
    }));

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("ACTION_REQUIRED", {
                lastResult: lastResult({
                    result: "PARTIAL",
                    state: "ACTION_REQUIRED",
                    success: false,
                    completed: false,
                    stateUnknown: true,
                }),
            }),
            emergencyLocked: true,
            emergencyState: "ACTION_REQUIRED",
        });

        await clickAndRender(
            renderer,
            findButton(renderer.root, "安全状態を再確認"),
        );
        renderer.render();

        assert.ok(textIncludes(renderer.root, "ACTION REQUIRED"));
        assert.equal(
            findButton(renderer.root, "通常に戻る").props.disabled,
            true,
        );
        assert.ok(textIncludes(renderer.root, "PROCESSING"));
        assert.equal(fetchMock.requests.length, 1);
    } finally {
        fetchMock.restore();
    }
});

test("Retry network error keeps ACTION_REQUIRED and allows retry again", async () => {
    const fetchMock = installFetchMock(() => {
        throw new TypeError("failed to fetch");
    });

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("ACTION_REQUIRED", {
                lastResult: lastResult({
                    result: "PARTIAL",
                    state: "ACTION_REQUIRED",
                    success: false,
                    completed: false,
                    stateUnknown: true,
                }),
            }),
            emergencyLocked: true,
            emergencyState: "ACTION_REQUIRED",
        });

        await clickAndRender(
            renderer,
            findButton(renderer.root, "安全状態を再確認"),
        );
        renderer.render();

        assert.ok(textIncludes(renderer.root, "ACTION REQUIRED"));
        assert.ok(textIncludes(renderer.root, "NETWORK_ERROR"));
        assert.equal(
            findButton(renderer.root, "安全状態を再確認").props.disabled,
            false,
        );
        assert.equal(
            findButton(renderer.root, "通常に戻る").props.disabled,
            true,
        );
    } finally {
        fetchMock.restore();
    }
});

test("Emergency network error does not fake LOCKED", async () => {
    const fetchMock = installFetchMock(() => {
        throw new TypeError("failed to fetch");
    });

    try {
        const renderer = await renderBotControl();

        clickAndRender(
            renderer,
            findButton(renderer.root, "EMERGENCY STOP"),
        );
        await clickAndRender(
            renderer,
            findButton(renderer.root, "CONFIRM EMERGENCY"),
        );
        renderer.render();

        assert.ok(textIncludes(renderer.root, "READY"));
        assert.equal(textIncludes(renderer.root, "STOPPED SAFELY"), false);
        assert.ok(textIncludes(renderer.root, "NETWORK_ERROR"));
        assert.equal(
            findButton(renderer.root, "EMERGENCY STOP").props.disabled,
            false,
        );
    } finally {
        fetchMock.restore();
    }
});

test("Unlock network error keeps LOCKED and does not fake READY", async () => {
    const fetchMock = installFetchMock(() => {
        throw new TypeError("failed to fetch");
    });

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("LOCKED"),
            emergencyLocked: true,
            emergencyState: "LOCKED",
            pendingOrder: false,
        });

        clickAndRender(
            renderer,
            findButton(renderer.root, "通常に戻る"),
        );
        await clickAndRender(
            renderer,
            findLastButton(renderer.root, "緊急状態を解除"),
        );
        renderer.render();

        assert.ok(textIncludes(renderer.root, "STOPPED SAFELY"));
        assert.ok(textIncludes(renderer.root, "LOCKED"));
        assert.equal(textIncludes(renderer.root, "UNLOCKED"), false);
        assert.ok(textIncludes(renderer.root, "NETWORK_ERROR"));
        assert.equal(
            findButton(renderer.root, "通常に戻る").props.disabled,
            false,
        );
    } finally {
        fetchMock.restore();
    }
});

test("Operation success refreshes status before backend props drive display", async () => {
    const fetchMock = installFetchMock((url) => {
        if (url.endsWith("/unlock")) {
            return jsonResponse({
                body: {
                    success: true,
                    unlocked: true,
                    emergency_stop: false,
                    emergency_state: "READY",
                },
            });
        }

        return jsonResponse({
            body: emergencyApiResponse(),
        });
    });
    const refreshed = [];

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("LOCKED"),
            emergencyLocked: true,
            emergencyState: "LOCKED",
            pendingOrder: false,
            onStatusRefresh: async () => {
                refreshed.push("unlock");
            },
        });

        clickAndRender(
            renderer,
            findButton(renderer.root, "通常に戻る"),
        );
        await clickAndRender(
            renderer,
            findLastButton(renderer.root, "緊急状態を解除"),
        );
        renderer.render({
            emergency: emergencyStatus("READY"),
            emergencyLocked: false,
            emergencyState: "READY",
        });

        assert.deepEqual(refreshed, ["unlock"]);
        assert.ok(textIncludes(renderer.root, "READY"));
        assert.equal(textIncludes(renderer.root, "STOPPED SAFELY"), false);
    } finally {
        fetchMock.restore();
    }
});

test("Old retry response cannot overwrite newer LOCKED backend props", async () => {
    const pending = deferred();
    const fetchMock = installFetchMock(() => pending.promise);

    try {
        const renderer = await renderBotControl({
            emergency: emergencyStatus("ACTION_REQUIRED", {
                lastResult: lastResult({
                    result: "PARTIAL",
                    state: "ACTION_REQUIRED",
                    success: false,
                    completed: false,
                    stateUnknown: true,
                }),
            }),
            emergencyLocked: true,
            emergencyState: "ACTION_REQUIRED",
        });

        const request = clickAndRender(
            renderer,
            findButton(renderer.root, "安全状態を再確認"),
        );

        renderer.render({
            emergency: emergencyStatus("LOCKED"),
            emergencyLocked: true,
            emergencyState: "LOCKED",
            pendingOrder: false,
        });

        assert.ok(textIncludes(renderer.root, "STOPPED SAFELY"));

        pending.resolve(jsonResponse({
            body: emergencyApiResponse({
                success: false,
                completed: false,
                partial: true,
                state_unknown: true,
                emergency_locked: true,
                position_remaining: null,
                retryable: true,
                error_code: "STATE_UNKNOWN",
            }),
        }));
        await request;
        renderer.render({
            emergency: emergencyStatus("LOCKED"),
            emergencyLocked: true,
            emergencyState: "LOCKED",
            pendingOrder: false,
        });

        assert.ok(textIncludes(renderer.root, "STOPPED SAFELY"));
        assert.equal(textIncludes(renderer.root, "ACTION REQUIRED"), false);
    } finally {
        fetchMock.restore();
    }
});
