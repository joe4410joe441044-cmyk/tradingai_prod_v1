import { createInitialReplayEngineState } from "../../features/market-intelligence/replay/replayEngine.js";

export const createInitialState = () => ({
    replayEngine: createInitialReplayEngineState(),
    selectedPosition: null,
    selectedDecision: null,
    selectedMarker: null,
    selectedStation: null,
});
