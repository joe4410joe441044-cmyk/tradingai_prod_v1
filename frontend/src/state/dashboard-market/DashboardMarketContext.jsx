/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useMemo, useState } from "react";

import { normalizeMarketContext } from "../../features/market-intelligence/market/normalizedMarketModel.js";
import {
    snapshotTradeSettings,
    tradeSettingsDiffer,
} from "../../components/operation/operationPreparationModel.js";

export const INITIAL_DASHBOARD_TRADE_SETTINGS = Object.freeze({
    mode: "PAPER",
    exchange: "KUCOIN",
    marketType: "FUTURES",
    symbol: "XRPUSDTM",
    leverage: 5,
    timeframe: "1m",
    positionSize: 0,
    tp: 1.0,
    sl: 1.0,
    maxDd: 5,
    risk_percent: 1.0,
    trailing: false,
    spreadFilter: true,
    volatilityFilter: true,
    liquidityFilter: true,
    spoofFilter: true,
    momentumFilter: true,
    killSwitch: false,
    autoFlatten: false,
});

/** Durable browser key for operator-approved saved Trade Settings revision. */
export const DASHBOARD_SAVED_TRADE_SETTINGS_KEY =
    "tradingai.dashboard.savedTradeSettings.v1";

const readDurableSavedSettings = () => {
    if (typeof window === "undefined" || !window.localStorage) {
        return null;
    }
    try {
        const raw = window.localStorage.getItem(DASHBOARD_SAVED_TRADE_SETTINGS_KEY);
        if (!raw) {
            return null;
        }
        const parsed = JSON.parse(raw);
        if (
            !parsed
            || typeof parsed !== "object"
            || !parsed.settings
            || typeof parsed.settings !== "object"
            || !Number.isFinite(Number(parsed.revision))
            || Number(parsed.revision) < 0
        ) {
            return null;
        }
        return {
            settings: snapshotTradeSettings({
                ...INITIAL_DASHBOARD_TRADE_SETTINGS,
                ...parsed.settings,
            }),
            revision: Math.floor(Number(parsed.revision)),
        };
    } catch {
        return null;
    }
};

const writeDurableSavedSettings = (next) => {
    if (typeof window === "undefined" || !window.localStorage) {
        return;
    }
    try {
        window.localStorage.setItem(
            DASHBOARD_SAVED_TRADE_SETTINGS_KEY,
            JSON.stringify({
                settings: snapshotTradeSettings(next.settings),
                revision: next.revision,
                savedAt: new Date().toISOString(),
            }),
        );
    } catch {
        // Persistence failure must not break in-memory SAVE semantics.
    }
};

export const DashboardMarketContext = createContext(null);

export function DashboardMarketContextProvider({ children }) {
    const durableSaved = readDurableSavedSettings();
    const initialSaved = durableSaved || {
        settings: snapshotTradeSettings(INITIAL_DASHBOARD_TRADE_SETTINGS),
        revision: 0,
    };
    const [tradeSettings, setTradeSettings] = useState(() => (
        durableSaved
            ? {
                ...INITIAL_DASHBOARD_TRADE_SETTINGS,
                ...durableSaved.settings,
            }
            : {
                ...INITIAL_DASHBOARD_TRADE_SETTINGS,
            }
    ));
    // SAVE SETTINGS authority boundary. The draft (tradeSettings) is what the
    // operator edits; the saved revision is what Final Preparation and START
    // consume. On first load the draft matches durable saved (or INITIAL).
    // Every successful SAVE SETTINGS commits a new monotonic revision and
    // persists it durably so cold reload does not manufacture INITIAL.
    const [savedSettingsState, setSavedSettingsState] = useState(() => initialSaved);
    const commitSavedSettings = useMemo(() => (next) => {
        setSavedSettingsState((previous) => {
            const committed = {
                settings: snapshotTradeSettings(next),
                revision: previous.revision + 1,
            };
            writeDurableSavedSettings(committed);
            return committed;
        });
    }, []);
    const marketContext = useMemo(() => {
        const normalized = normalizeMarketContext({
        exchange: tradeSettings.exchange,
        marketType: tradeSettings.marketType,
        exchangeSymbol: tradeSettings.symbol,
        });
        return {
            exchange: normalized.exchange,
            marketType: normalized.marketType,
            exchangeSymbol: normalized.exchangeSymbol,
            contextKey: normalized.contextKey,
        };
    }, [tradeSettings.exchange, tradeSettings.marketType, tradeSettings.symbol]);
    const savedSettings = savedSettingsState.settings;
    const settingsRevision = savedSettingsState.revision;
    const settingsDirty = tradeSettingsDiffer(
        tradeSettings,
        savedSettings,
    );
    const value = useMemo(() => ({
        marketContext,
        setTradeSettings,
        tradeSettings,
        savedSettings,
        settingsRevision,
        settingsDirty,
        commitSavedSettings,
    }), [
        commitSavedSettings,
        marketContext,
        savedSettings,
        settingsDirty,
        settingsRevision,
        tradeSettings,
    ]);

    return (
        <DashboardMarketContext.Provider value={value}>
            {children}
        </DashboardMarketContext.Provider>
    );
}

export function useDashboardMarketContext() {
    const context = useContext(DashboardMarketContext);
    if (context === null)
        throw new Error("useDashboardMarketContext must be used within DashboardMarketContextProvider.");
    return context;
}

export const useOptionalDashboardMarketContext = () => useContext(DashboardMarketContext);
