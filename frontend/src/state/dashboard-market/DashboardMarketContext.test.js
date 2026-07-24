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
    const code = transformed.code.replace(
        'from "../../features/market-intelligence/market/normalizedMarketModel.js";',
        `from "${normalizedModelUrl}";`,
    );
    try {
        await writeFile(output, code);
        return await import(`${pathToFileURL(output).href}?test=${Date.now()}`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
};

test("Dashboard Context Provider is the single mutable trade-setting authority exposed by its hook", async () => {
    const {
        DashboardMarketContextProvider,
        INITIAL_DASHBOARD_TRADE_SETTINGS,
        useDashboardMarketContext,
    } = await loadModule();
    const internals = React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
    let state;
    let activeContext;
    const dispatcher = {
        useContext() {
            return activeContext;
        },
        useMemo(factory) {
            return factory();
        },
        useState(initializer) {
            if (state === undefined) state = typeof initializer === "function" ? initializer() : initializer;
            return [state, (next) => {
                state = typeof next === "function" ? next(state) : next;
            }];
        },
    };
    const Render = () => {
        const previous = internals.H;
        internals.H = dispatcher;
        try {
            const provider = DashboardMarketContextProvider({ children: null });
            activeContext = provider.props.value;
            return useDashboardMarketContext();
        } finally {
            activeContext = null;
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
