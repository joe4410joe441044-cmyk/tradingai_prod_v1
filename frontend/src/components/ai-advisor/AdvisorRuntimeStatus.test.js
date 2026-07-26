import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));
const loadComponent = async () => {
    const source = new URL("./AdvisorRuntimeStatus.jsx", import.meta.url);
    const transformed = await transformWithOxc(
        await readFile(source, "utf8"),
        fileURLToPath(source),
    );
    const temporary = await mkdtemp(join(directory, ".runtime-status-test-"));
    const output = join(temporary, "AdvisorRuntimeStatus.mjs");
    try {
        await writeFile(output, transformed.code);
        return (await import(`${pathToFileURL(output).href}?test=${Date.now()}`)).default;
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};
const textOf = (node) => {
    if (node == null || typeof node === "boolean") return "";
    if (Array.isArray(node)) return node.map(textOf).join(" ");
    if (typeof node !== "object") return String(node);
    if (typeof node.type === "function") return textOf(node.type(node.props));
    return textOf(node.props?.children);
};
const descendants = (node) => {
    if (node == null || typeof node === "boolean") return [];
    if (Array.isArray(node)) return node.flatMap(descendants);
    if (typeof node !== "object") return [];
    if (typeof node.type === "function") return descendants(node.type(node.props));
    return [node, ...descendants(node.props?.children)];
};
const runtime = (overrides = {}) => ({
    bot: { state: "RUNNING", mode: "PAPER", exchange: "kucoin", symbol: "XRPUSDTM" },
    operation: { loopEnabled: true, loopState: "RUNNING", autoTradeEnabled: false },
    safety: {
        emergencyLocked: false,
        emergencyState: "READY",
        dryRun: true,
        realOrderAllowed: false,
    },
    runtime: {
        capturedAt: "2026-07-25T10:00:00Z",
        sourceUpdatedAt: "2026-07-25T09:59:58Z",
        freshness: "FRESH",
    },
    warnings: [],
    ...overrides,
});

test("runtime status renders loading and initial error with accessible retry", async () => {
    const Component = await loadComponent();
    const loading = textOf(Component({
        data: null,
        loading: true,
        connectionState: "LOADING",
    }));
    const errorNode = Component({
        data: null,
        loading: false,
        connectionState: "DISCONNECTED",
        error: { message: "Safe failure", retryable: true, requestId: "request-1" },
        onRetry: () => {},
    });

    assert.match(loading, /Loading runtime status/);
    assert.match(textOf(errorNode), /Runtime Status Unavailable/);
    assert.match(textOf(errorNode), /Retryable:\s+YES/);
    assert.match(textOf(errorNode), /request-1/);
    const retry = descendants(errorNode).find((node) => node.type === "button");
    assert.equal(retry.props["aria-label"], "Retry runtime status");
});

test("runtime status renders bot, operation, paper safety, and warnings", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({
        data: runtime({ warnings: ["SOURCE_TIMESTAMP_MISSING"] }),
        loading: false,
        connectionState: "CONNECTED",
        lastSuccessfulAt: 1_753_438_800_000,
        onRetry: () => {},
    }));

    for (const expected of [
        "BOT", "RUNNING", "PAPER", "KUCOIN", "XRPUSDTM",
        "OPERATION", "Loop Enabled", "ON", "Auto Trade", "OFF",
        "SAFETY", "Dry Run", "Real Order Allowed",
        "CONNECTION / FRESHNESS", "CONNECTED", "FRESH",
        "Warnings", "SOURCE_TIMESTAMP_MISSING",
    ]) {
        assert.match(text.toUpperCase(), new RegExp(expected.toUpperCase()));
    }
});

test("warning display is capped and does not stringify raw objects", async () => {
    const Component = await loadComponent();
    const text = textOf(Component({
        data: runtime({ warnings: ["ONE", "TWO", "THREE", "FOUR"] }),
        loading: false,
        connectionState: "CONNECTED",
    }));

    assert.match(text, /Warnings/);
    assert.match(text, /ONE/);
    assert.match(text, /THREE/);
    assert.doesNotMatch(text, /FOUR|\[object Object\]/);
});

test("runtime status distinguishes stale, unknown, locked, and degraded last-good", async () => {
    const Component = await loadComponent();
    const stale = textOf(Component({
        data: runtime({
            safety: {
                emergencyLocked: true,
                emergencyState: "LOCKED",
                dryRun: null,
                realOrderAllowed: false,
            },
            runtime: {
                capturedAt: null,
                sourceUpdatedAt: null,
                freshness: "STALE",
            },
        }),
        loading: false,
        connectionState: "DEGRADED",
        error: { message: "Latest refresh failed." },
        lastSuccessfulAt: 1_753_438_800_000,
        onRetry: () => {},
    }));
    const unknown = textOf(Component({
        data: runtime({
            runtime: {
                capturedAt: null,
                sourceUpdatedAt: null,
                freshness: "UNKNOWN",
            },
        }),
        loading: false,
        connectionState: "CONNECTED",
    }));

    assert.match(stale, /Showing last known runtime state/);
    assert.match(stale, /LOCKED/);
    assert.match(stale, /Runtime data is stale/);
    assert.match(unknown, /Runtime update time is unavailable/);
});
