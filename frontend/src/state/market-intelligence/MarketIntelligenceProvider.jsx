/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useReducer } from "react";

import { createInitialState } from "./initialState.js";
import { applyReplayCommandAction } from "./marketIntelligenceActions.js";
import { marketIntelligenceReducer } from "./marketIntelligenceReducer.js";

export const MarketIntelligenceContext = createContext(null);

export function MarketIntelligenceProvider({ children }) {
    const [state, dispatch] = useReducer(
        marketIntelligenceReducer,
        undefined,
        createInitialState,
    );
    const applyReplayCommand = useCallback((command) => {
        dispatch(applyReplayCommandAction(command));
    }, []);
    const contextValue = useMemo(() => ({
        state,
        dispatch,
        replayEngine: state.replayEngine,
        applyReplayCommand,
    }), [applyReplayCommand, state]);

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
