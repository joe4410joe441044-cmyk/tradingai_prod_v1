import { applyReplayCommand } from "../../features/market-intelligence/replay/replayEngine.js";
import { MARKET_INTELLIGENCE_ACTIONS } from "./marketIntelligenceActions.js";

const identifier = (selection, field) => {
    if (!selection || typeof selection !== "object" || Array.isArray(selection)) return null;
    const value = selection[field] ?? selection.id;
    return typeof value === "string" && value !== "" ? value : null;
};

const isSelectionReachable = (selection, kind, projection) => {
    if (selection === null) return true;
    const safeProjection = projection && typeof projection === "object" ? projection : {};
    if (kind === "position") {
        const id = identifier(selection, "positionId");
        return id !== null && safeProjection.positionContext?.positionId === id;
    }
    if (kind === "decision") {
        const id = identifier(selection, "decisionId");
        return id !== null && safeProjection.decisionContext?.decisionId === id;
    }
    if (kind === "marker") {
        const id = identifier(selection, "markerId");
        return id !== null && Array.isArray(safeProjection.markerContext?.markers)
            && safeProjection.markerContext.markers.some((marker) => marker?.markerId === id || marker?.id === id);
    }
    const id = identifier(selection, "stationId");
    return id !== null && Array.isArray(safeProjection.stationContext?.stations)
        && safeProjection.stationContext.stations.some((station) => station?.stationId === id);
};

const reconcileSelections = (state, replayEngine) => {
    if (replayEngine.accepted === false) return { ...state, replayEngine };
    const projection = replayEngine.projection;
    return {
        ...state,
        replayEngine,
        selectedPosition: isSelectionReachable(state.selectedPosition, "position", projection)
            ? state.selectedPosition : null,
        selectedDecision: isSelectionReachable(state.selectedDecision, "decision", projection)
            ? state.selectedDecision : null,
        selectedMarker: isSelectionReachable(state.selectedMarker, "marker", projection)
            ? state.selectedMarker : null,
        selectedStation: isSelectionReachable(state.selectedStation, "station", projection)
            ? state.selectedStation : null,
    };
};

export function marketIntelligenceReducer(state, action) {
    switch (action?.type) {
        case MARKET_INTELLIGENCE_ACTIONS.APPLY_REPLAY_COMMAND: {
            const replayEngine = applyReplayCommand(state.replayEngine, action.payload?.command);
            return reconcileSelections(state, replayEngine);
        }
        case MARKET_INTELLIGENCE_ACTIONS.SELECT_POSITION:
            return { ...state, selectedPosition: isSelectionReachable(
                action.payload, "position", state.replayEngine.projection,
            ) ? action.payload : null };
        case MARKET_INTELLIGENCE_ACTIONS.SELECT_DECISION:
            return { ...state, selectedDecision: isSelectionReachable(
                action.payload, "decision", state.replayEngine.projection,
            ) ? action.payload : null };
        case MARKET_INTELLIGENCE_ACTIONS.SELECT_MARKER:
            return { ...state, selectedMarker: isSelectionReachable(
                action.payload, "marker", state.replayEngine.projection,
            ) ? action.payload : null };
        case MARKET_INTELLIGENCE_ACTIONS.SELECT_STATION:
            return { ...state, selectedStation: isSelectionReachable(
                action.payload, "station", state.replayEngine.projection,
            ) ? action.payload : null };
        default:
            return state;
    }
}
