/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useReducer } from "react";

import { createInitialState } from "./initialState.js";
import { applyReplayCommandAction } from "./marketIntelligenceActions.js";
import { marketIntelligenceReducer } from "./marketIntelligenceReducer.js";
import { normalizeReplayMarketModel } from "../../features/market-intelligence/market/replayMarketAdapter.js";
import { normalizeLiveMarketModel } from "../../features/market-intelligence/market/liveMarketAdapter.js";
import {
    createDashboardContextMarketModel,
    isReplayMarketContextActive,
    resolveMarketContext,
    runtimeMarketMatchesContext,
} from "../../features/market-intelligence/market/marketContextSelection.js";
import { useRuntimeMarketTelemetry } from "../../hooks/useRuntimeMarketTelemetry.js";
import { projectAutoMarketViewState } from "../../features/market-intelligence/market/autoMarketViewState.js";
import { useOptionalDashboardMarketContext } from "../dashboard-market/DashboardMarketContext.jsx";

export const MarketIntelligenceContext = createContext(null);

export function MarketIntelligenceProvider({ children }) {
    const dashboardMarket = useOptionalDashboardMarketContext();
    const runtimeTelemetry = useRuntimeMarketTelemetry();
    const [state, dispatch] = useReducer(
        marketIntelligenceReducer,
        undefined,
        createInitialState,
    );
    const applyReplayCommand = useCallback((command) => {
        dispatch(applyReplayCommandAction(command));
    }, []);
    const replayMarketModel = useMemo(() => normalizeReplayMarketModel({
        replayEngine: state.replayEngine,
    }), [state.replayEngine]);
    const liveAuthorityContext = useMemo(() => {
        const botStatus = runtimeTelemetry.runtime?.botStatus;
        const activeSymbol = botStatus?.activeSymbol;
        if (!activeSymbol) return dashboardMarket?.marketContext;
        const exchange = String(
            botStatus.exchange ?? runtimeTelemetry.market.exchange ?? "",
        ).toUpperCase();
        const marketType = String(
            runtimeTelemetry.market.marketType ?? "FUTURES",
        ).toUpperCase();
        const exchangeSymbol = String(
            botStatus.orderbookSymbol ?? activeSymbol,
        ).toUpperCase();
        return {
            exchange,
            marketType,
            exchangeSymbol,
            normalizedSymbol: String(activeSymbol).toUpperCase(),
            displaySymbol: String(activeSymbol).toUpperCase(),
            contextKey: exchange && marketType && exchangeSymbol
                ? `${exchange}:${marketType}:${exchangeSymbol}` : null,
        };
    }, [dashboardMarket?.marketContext, runtimeTelemetry.market, runtimeTelemetry.runtime]);
    const liveMarketModel = useMemo(() => {
        const context = liveAuthorityContext;
        if (!runtimeMarketMatchesContext(runtimeTelemetry.market, context))
            return createDashboardContextMarketModel(context);
        return normalizeLiveMarketModel({
            context,
            market: {
                ...runtimeTelemetry.market,
                timestamp: runtimeTelemetry.market.timestamp ?? runtimeTelemetry.market.lastUpdate,
            },
            runtime: runtimeTelemetry.runtime,
            connection: {
                connected: runtimeTelemetry.runtime.websocketConnected,
                connectionId: runtimeTelemetry.runtime.connectionId,
            },
            receivedAt: runtimeTelemetry.market.lastUpdate,
        });
    }, [liveAuthorityContext, runtimeTelemetry.market, runtimeTelemetry.runtime]);
    const activeMarket = useMemo(() => resolveMarketContext({
        dashboardContext: liveAuthorityContext,
        replayEngine: state.replayEngine,
        replayModel: replayMarketModel,
    }), [liveAuthorityContext, replayMarketModel, state.replayEngine]);
    const normalizedMarketModel = isReplayMarketContextActive(state.replayEngine)
        ? replayMarketModel : liveMarketModel;
    const autoMarketSelectionStatus = (
        runtimeTelemetry.runtime?.botStatus?.autoMarketSelection ?? null
    );
    const marketViewDisplayState = projectAutoMarketViewState({
        contextMode: activeMarket.mode,
        marketModel: normalizedMarketModel,
        selectionStatus: autoMarketSelectionStatus,
    });
    const contextValue = useMemo(() => ({
        state,
        dispatch,
        replayEngine: state.replayEngine,
        applyReplayCommand,
        marketContext: activeMarket.context,
        marketContextMode: activeMarket.mode,
        normalizedMarketModel,
        autoMarketSelectionStatus,
        marketViewDisplayState,
    }), [activeMarket, applyReplayCommand, autoMarketSelectionStatus, marketViewDisplayState, normalizedMarketModel, state]);

    return (
        <MarketIntelligenceContext.Provider value={contextValue}>
            {children}
        </MarketIntelligenceContext.Provider>
    );
}

export function useMarketIntelligence() {
    const context = useContext(MarketIntelligenceContext);

    if (context === null) {
        throw new Error(
            "useMarketIntelligence must be used within MarketIntelligenceProvider.",
        );
    }

    return context;
}
