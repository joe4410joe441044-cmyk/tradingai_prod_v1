import { REPLAY_STATES } from "../../features/market-intelligence/replay/replayStateMachine.js";

export const selectReplayEngine = (state) => state.replayEngine;
export const selectReplayDataset = (state) => selectReplayEngine(state).dataset;
export const selectReplayCursor = (state) => selectReplayEngine(state).replayCursor;
export const selectReplayMachine = (state) => selectReplayEngine(state).machine;
export const selectReplayMachineState = (state) => selectReplayMachine(state).state;
export const selectReplayProjection = (state) => selectReplayEngine(state).projection;
export const selectReplayCurrentEvent = (state) => selectReplayProjection(state).currentEvent;
export const selectReplayVisibleEvents = (state) => selectReplayProjection(state).visibleEvents;
export const selectReplayPositionContext = (state) => (
    selectReplayProjection(state).positionContext
);
export const selectReplayDecisionContext = (state) => (
    selectReplayProjection(state).decisionContext
);
export const selectReplayMarkerContext = (state) => (
    selectReplayProjection(state).markerContext
);
export const selectReplayStationContext = (state) => (
    selectReplayProjection(state).stationContext
);
export const selectReplayTimeline = (state) => selectReplayProjection(state).timeline;
export const selectReplayProgress = (state) => selectReplayProjection(state).progress;
export const selectReplayIsAtStart = (state) => selectReplayProjection(state).isAtStart;
export const selectReplayIsAtEnd = (state) => selectReplayProjection(state).isAtEnd;
export const selectReplayAccepted = (state) => selectReplayEngine(state).accepted;
export const selectReplayRejectionReason = (state) => (
    selectReplayEngine(state).rejectionReason
);
export const selectReplayError = (state) => (
    selectReplayEngine(state).engineError ?? selectReplayMachine(state).error
);

export const getSelectedPosition = (state) => state.selectedPosition;
export const getSelectedDecision = (state) => state.selectedDecision;
export const getSelectedMarker = (state) => state.selectedMarker;
export const getSelectedStation = (state) => state.selectedStation;

export const selectPlaybackState = selectReplayMachineState;
export const selectLoadingState = (state) => (
    selectReplayMachineState(state) === REPLAY_STATES.REPLAY_LOADING
);
export const selectErrorState = selectReplayError;
export const getReplayCursor = selectReplayCursor;
export const getPlaybackState = selectPlaybackState;
export const getLoadingState = selectLoadingState;
export const getErrorState = selectErrorState;
export const getDataQuality = (state) => selectReplayProjection(state).dataQuality;
