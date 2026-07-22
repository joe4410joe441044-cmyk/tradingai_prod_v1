import { applyReplayCommand } from "../../features/market-intelligence/replay/replayEngine.js";
import { MARKET_INTELLIGENCE_ACTIONS } from "./marketIntelligenceActions.js";

export function marketIntelligenceReducer(state, action) {
    switch (action?.type) {
        case MARKET_INTELLIGENCE_ACTIONS.APPLY_REPLAY_COMMAND:
            return {
                ...state,
                replayEngine: applyReplayCommand(
                    state.replayEngine,
                    action.payload?.command,
                ),
            };
        case MARKET_INTELLIGENCE_ACTIONS.SELECT_POSITION:
            return { ...state, selectedPosition: action.payload };
        case MARKET_INTELLIGENCE_ACTIONS.SELECT_DECISION:
            return { ...state, selectedDecision: action.payload };
        case MARKET_INTELLIGENCE_ACTIONS.SELECT_MARKER:
            return { ...state, selectedMarker: action.payload };
        case MARKET_INTELLIGENCE_ACTIONS.SELECT_STATION:
            return { ...state, selectedStation: action.payload };
        default:
            return state;
    }
}
