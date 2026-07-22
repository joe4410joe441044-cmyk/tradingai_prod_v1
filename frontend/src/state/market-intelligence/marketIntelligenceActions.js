import { REPLAY_ENGINE_COMMANDS } from "../../features/market-intelligence/replay/replayEngine.js";

export const MARKET_INTELLIGENCE_ACTIONS = Object.freeze({
    APPLY_REPLAY_COMMAND: "APPLY_REPLAY_COMMAND",
    SELECT_POSITION: "SELECT_POSITION",
    SELECT_DECISION: "SELECT_DECISION",
    SELECT_MARKER: "SELECT_MARKER",
    SELECT_STATION: "SELECT_STATION",
});

export const applyReplayCommandAction = (command) => ({
    type: MARKET_INTELLIGENCE_ACTIONS.APPLY_REPLAY_COMMAND,
    payload: { command },
});

export const loadReplayDataset = (dataset) => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.LOAD_DATASET,
    payload: { dataset },
});

export const playReplay = () => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.PLAY,
});

export const pauseReplay = () => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.PAUSE,
});

export const stepReplayForward = () => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.STEP_FORWARD,
});

export const stepReplayBackward = () => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.STEP_BACKWARD,
});

export const seekReplay = (timestamp) => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.SEEK,
    payload: { timestamp },
});

export const jumpReplayToStart = () => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.JUMP_TO_START,
});

export const jumpReplayToEnd = () => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.JUMP_TO_END,
});

export const restartReplay = () => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.RESTART,
});

export const resetReplay = () => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.RESET,
});

export const retryReplay = () => applyReplayCommandAction({
    type: REPLAY_ENGINE_COMMANDS.RETRY,
});

export const selectPosition = (position) => ({
    type: MARKET_INTELLIGENCE_ACTIONS.SELECT_POSITION,
    payload: position,
});

export const selectDecision = (decision) => ({
    type: MARKET_INTELLIGENCE_ACTIONS.SELECT_DECISION,
    payload: decision,
});

export const selectMarker = (marker) => ({
    type: MARKET_INTELLIGENCE_ACTIONS.SELECT_MARKER,
    payload: marker,
});

export const selectStation = (station) => ({
    type: MARKET_INTELLIGENCE_ACTIONS.SELECT_STATION,
    payload: station,
});
