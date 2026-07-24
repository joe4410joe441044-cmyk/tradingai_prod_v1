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
    const liveMarketModel = useMemo(() => {
        const context = dashboardMarket?.marketContext;
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
    }, [dashboardMarket?.marketContext, runtimeTelemetry.market, runtimeTelemetry.runtime]);
    const activeMarket = useMemo(() => resolveMarketContext({
        dashboardContext: dashboardMarket?.marketContext,
        replayEngine: state.replayEngine,
        replayModel: replayMarketModel,
    }), [dashboardMarket?.marketContext, replayMarketModel, state.replayEngine]);
    const normalizedMarketModel = isReplayMarketContextActive(state.replayEngine)
        ? replayMarketModel : liveMarketModel;
    const contextValue = useMemo(() => ({
        state,
        dispatch,
        replayEngine: state.replayEngine,
        applyReplayCommand,
        marketContext: activeMarket.context,
        marketContextMode: activeMarket.mode,
        normalizedMarketModel,
    }), [activeMarket, applyReplayCommand, normalizedMarketModel, state]);

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
