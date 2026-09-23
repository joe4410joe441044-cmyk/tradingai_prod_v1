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

export const DashboardMarketContext = createContext(null);

export function DashboardMarketContextProvider({ children }) {
    const [tradeSettings, setTradeSettings] = useState(() => ({
        ...INITIAL_DASHBOARD_TRADE_SETTINGS,
    }));
    // SAVE SETTINGS authority boundary. The draft (tradeSettings) is what the
    // operator edits; the saved revision is what Final Preparation and START
    // consume. On first load the draft is treated as already-saved (defaults)
    // so there is no phantom unsaved state. Every successful SAVE SETTINGS
    // commits a new monotonic revision; a failed LIVE save never increments it.
    const [savedSettingsState, setSavedSettingsState] = useState(() => ({
        settings: snapshotTradeSettings(INITIAL_DASHBOARD_TRADE_SETTINGS),
        revision: 0,
    }));
    const commitSavedSettings = useMemo(() => (next) => {
        setSavedSettingsState((previous) => ({
            settings: snapshotTradeSettings(next),
            revision: previous.revision + 1,
        }));
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
