import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import * as React from "react";
import { transformWithOxc } from "vite";

const directory = dirname(fileURLToPath(import.meta.url));

const loadModule = async () => {
    const sourceUrl = new URL("./DashboardMarketContext.jsx", import.meta.url);
    const transformed = await transformWithOxc(await readFile(sourceUrl, "utf8"), fileURLToPath(sourceUrl));
    const temporary = await mkdtemp(join(directory, ".dashboard-market-context-test-"));
    const output = join(temporary, "DashboardMarketContext.mjs");
    const normalizedModelUrl = pathToFileURL(join(
        directory,
        "../../features/market-intelligence/market/normalizedMarketModel.js",
    )).href;
    const operationModelUrl = pathToFileURL(join(
        directory,
        "../../components/operation/operationPreparationModel.js",
    )).href;
    const code = transformed.code
        .replace(
            'from "../../features/market-intelligence/market/normalizedMarketModel.js";',
            `from "${normalizedModelUrl}";`,
        )
        .replace(
            'from "../../components/operation/operationPreparationModel.js";',
            `from "${operationModelUrl}";`,
        );
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=${Date.now()}`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

// Minimal order-aware React hook dispatcher. useState allocates a fresh slot
// per call (so the provider's multiple useState calls stay independent);
// useMemo/useContext do not consume state slots.
const createDispatcher = () => {
    const states = [];
    let stateIndex = 0;
    const contextRef = { current: null };
    return {
        contextRef,
        beginRender() {
            stateIndex = 0;
        },
        useContext() {
            return contextRef.current;
        },
        useMemo(factory) {
            return factory();
        },
        useState(initializer) {
            const index = stateIndex;
            stateIndex += 1;
            if (states[index] === undefined) {
                states[index] = typeof initializer === "function"
                    ? initializer()
                    : initializer;
            }
            return [
                states[index],
                (next) => {
                    states[index] = typeof next === "function"
                        ? next(states[index])
                        : next;
                },
            ];
        },
    };
};

test("Dashboard Context Provider is the single mutable trade-setting authority exposed by its hook", async () => {
    const {
        DashboardMarketContextProvider,
        INITIAL_DASHBOARD_TRADE_SETTINGS,
        useDashboardMarketContext,
    } = await loadModule();
    const internals = React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
    const dispatcher = createDispatcher();
    const Render = () => {
        const previous = internals.H;
        dispatcher.beginRender();
        internals.H = dispatcher;
        try {
            const provider = DashboardMarketContextProvider({ children: null });
            dispatcher.contextRef.current = provider.props.value;
            return useDashboardMarketContext();
        } finally {
            dispatcher.contextRef.current = null;
            internals.H = previous;
        }
    };
    let value = Render();
    assert.deepEqual(value.tradeSettings, { ...INITIAL_DASHBOARD_TRADE_SETTINGS });
    assert.equal(value.marketContext.contextKey, "KUCOIN:FUTURES:XRPUSDTM");
    value.setTradeSettings((current) => ({ ...current, symbol: "BTCUSDT" }));
    value = Render();
    assert.equal(value.tradeSettings.symbol, "BTCUSDT");
    assert.equal(value.marketContext.contextKey, "KUCOIN:FUTURES:BTCUSDT");
});

test("Dashboard context separates DRAFT from SAVED settings and reports unsaved changes", async () => {
    const {
        DashboardMarketContextProvider,
        useDashboardMarketContext,
    } = await loadModule();
    const internals = React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
    const dispatcher = createDispatcher();
    const Render = () => {
        const previous = internals.H;
        dispatcher.beginRender();
        internals.H = dispatcher;
        try {
            const provider = DashboardMarketContextProvider({ children: null });
            dispatcher.contextRef.current = provider.props.value;
            return useDashboardMarketContext();
        } finally {
            dispatcher.contextRef.current = null;
            internals.H = previous;
        }
    };

    let value = Render();
    // Fresh provider: draft matches saved, no unsaved changes.
    assert.equal(value.settingsDirty, false);
    assert.equal(value.settingsRevision, 0);

    // Editing the draft creates unsaved changes but does NOT touch the saved
    // revision.
    value.setTradeSettings((current) => ({ ...current, mode: "LIVE" }));
    value = Render();
    assert.equal(value.tradeSettings.mode, "LIVE");
    assert.equal(value.settingsDirty, true);
    assert.equal(value.settingsRevision, 0);
    assert.equal(value.savedSettings.mode, "PAPER");

    // SAVE SETTINGS commits the draft to a new saved revision.
    value.commitSavedSettings(value.tradeSettings);
    value = Render();
    assert.equal(value.settingsDirty, false);
    assert.equal(value.settingsRevision, 1);
    assert.equal(value.savedSettings.mode, "LIVE");

    // A further draft edit becomes unsaved again while the saved revision is
    // preserved.
    value.setTradeSettings((current) => ({ ...current, leverage: 75 }));
    value = Render();
    assert.equal(value.settingsDirty, true);
    assert.equal(value.settingsRevision, 1);
    assert.equal(value.savedSettings.leverage, 5);
});

test("Dashboard market hook rejects use outside its Provider", async () => {
    const { useDashboardMarketContext } = await loadModule();
    const internals = React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
    const previous = internals.H;
    internals.H = { useContext: () => null };
    try {
        assert.throws(() => useDashboardMarketContext(), {
            message: "useDashboardMarketContext must be used within DashboardMarketContextProvider.",
        });
    } finally {
        internals.H = previous;
    }
});


test("SAVE SETTINGS durable revision survives provider remount (localStorage)", async () => {
    const {
        DashboardMarketContextProvider,
        DASHBOARD_SAVED_TRADE_SETTINGS_KEY,
        useDashboardMarketContext,
    } = await loadModule();
    const store = new Map();
    globalThis.window = {
        localStorage: {
            getItem: (key) => (store.has(key) ? store.get(key) : null),
            setItem: (key, value) => { store.set(key, String(value)); },
            removeItem: (key) => { store.delete(key); },
        },
    };
    const internals = React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
    const dispatcher = createDispatcher();
    const Render = () => {
        const previous = internals.H;
        dispatcher.beginRender();
        internals.H = dispatcher;
        try {
            const provider = DashboardMarketContextProvider({ children: null });
            dispatcher.contextRef.current = provider.props.value;
            return useDashboardMarketContext();
        } finally {
            dispatcher.contextRef.current = null;
            internals.H = previous;
        }
    };
    let value = Render();
    value.setTradeSettings((current) => ({ ...current, mode: "LIVE", symbol: "C98USDTM" }));
    value = Render();
    value.commitSavedSettings(value.tradeSettings);
    value = Render();
    assert.equal(value.settingsRevision, 1);
    assert.equal(value.savedSettings.mode, "LIVE");
    assert.equal(value.savedSettings.symbol, "C98USDTM");
    assert.ok(store.get(DASHBOARD_SAVED_TRADE_SETTINGS_KEY));

    // Remount with a fresh dispatcher -> must restore durable saved, not INITIAL.
    const dispatcher2 = createDispatcher();
    const Render2 = () => {
        const previous = internals.H;
        dispatcher2.beginRender();
        internals.H = dispatcher2;
        try {
            const provider = DashboardMarketContextProvider({ children: null });
            dispatcher2.contextRef.current = provider.props.value;
            return useDashboardMarketContext();
        } finally {
            dispatcher2.contextRef.current = null;
            internals.H = previous;
        }
    };
    const restored = Render2();
    assert.equal(restored.settingsRevision, 1);
    assert.equal(restored.savedSettings.mode, "LIVE");
    assert.equal(restored.tradeSettings.symbol, "C98USDTM");
    assert.equal(restored.settingsDirty, false);
});
