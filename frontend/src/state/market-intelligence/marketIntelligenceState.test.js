import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import * as React from "react";
import { transformWithOxc } from "vite";

import {
    REPLAY_ENGINE_COMMANDS as C,
    applyReplayCommand,
} from "../../features/market-intelligence/replay/replayEngine.js";
import { XRP_REPLAY_FIXTURE } from "../../features/market-intelligence/replay/replayFixtures.js";
import { REPLAY_STATES as S } from "../../features/market-intelligence/replay/replayStateMachine.js";
import {
    applyReplayCommandAction,
    loadReplayDataset,
    pauseReplay,
    playReplay,
    resetReplay,
    seekReplay,
    selectDecision,
    selectMarker,
    selectPosition,
    selectStation,
    stepReplayForward,
} from "./marketIntelligenceActions.js";
import { createInitialState } from "./initialState.js";
import { marketIntelligenceReducer } from "./marketIntelligenceReducer.js";
import {
    getDataQuality,
    getErrorState,
    getLoadingState,
    getPlaybackState,
    getReplayCursor,
    getSelectedDecision,
    getSelectedMarker,
    getSelectedPosition,
    getSelectedStation,
    selectErrorState,
    selectLoadingState,
    selectPlaybackState,
    selectReplayAccepted,
    selectReplayCurrentEvent,
    selectReplayCursor,
    selectReplayDataset,
    selectReplayDecisionContext,
    selectReplayEngine,
    selectReplayError,
    selectReplayIsAtEnd,
    selectReplayIsAtStart,
    selectReplayMachine,
    selectReplayMachineState,
    selectReplayMarkerContext,
    selectReplayPositionContext,
    selectReplayProgress,
    selectReplayProjection,
    selectReplayRejectionReason,
    selectReplayStationContext,
    selectReplayTimeline,
    selectReplayVisibleEvents,
} from "./marketIntelligenceSelectors.js";

const stateDirectory = dirname(fileURLToPath(import.meta.url));
let providerModulePromise;

const loadProviderModule = async () => {
    const sourceUrl = new URL("./MarketIntelligenceProvider.jsx", import.meta.url);
    const source = await readFile(sourceUrl, "utf8");
    const transformed = await transformWithOxc(source, fileURLToPath(sourceUrl));
    const tempDirectory = await mkdtemp(join(stateDirectory, ".provider-test-"));
    const outputPath = join(tempDirectory, "MarketIntelligenceProvider.mjs");
    const initialStateUrl = pathToFileURL(join(stateDirectory, "initialState.js")).href;
    const actionsUrl = pathToFileURL(join(
        stateDirectory,
        "marketIntelligenceActions.js",
    )).href;
    const reducerUrl = pathToFileURL(join(
        stateDirectory,
        "marketIntelligenceReducer.js",
    )).href;
    const code = transformed.code
        .replace('from "./initialState.js";', `from "${initialStateUrl}";`)
        .replace(
            'from "./marketIntelligenceActions.js";',
            `from "${actionsUrl}";`,
        )
        .replace(
            'from "./marketIntelligenceReducer.js";',
            `from "${reducerUrl}";`,
        );

    try {
        await writeFile(outputPath, code);
        return await import(`${pathToFileURL(outputPath).href}?t=${Date.now()}`);
    } finally {
        await rm(tempDirectory, { force: true, recursive: true });
    }
};

const getProviderModule = () => {
    if (!providerModulePromise) providerModulePromise = loadProviderModule();
    return providerModulePromise;
};

const createProviderRenderer = (Provider, Consumer) => {
    const internals = React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
    let reducerState;
    let activeContext = null;
    let consumerResult;

    const dispatcher = {
        useCallback(callback) {
            return callback;
        },
        useContext() {
            return activeContext;
        },
        useMemo(factory) {
            return factory();
        },
        useReducer(reducer, initialArgument, initializer) {
            if (reducerState === undefined) {
                reducerState = initializer ? initializer(initialArgument) : initialArgument;
            }
            return [reducerState, (action) => {
                reducerState = reducer(reducerState, action);
            }];
        },
    };

    const withDispatcher = (callback) => {
        const previousDispatcher = internals.H;
        internals.H = dispatcher;
        try {
            return callback();
        } finally {
            internals.H = previousDispatcher;
        }
    };

    const render = () => withDispatcher(() => {
        const providerElement = Provider({ children: React.createElement(Consumer) });
        activeContext = providerElement.props.value;
        consumerResult = Consumer();
        activeContext = null;
        return consumerResult;
    });
    render();
    return {
        get result() {
            return consumerResult;
        },
        render,
        withDispatcher,
    };
};

const reduce = (state, action) => marketIntelligenceReducer(state, action);

test("initial state owns one fresh replay engine and no duplicate replay fields", () => {
    const first = createInitialState();
    const second = createInitialState();
    assert.equal(first.replayEngine.machine.state, S.IDLE);
    assert.equal(first.replayEngine.dataset, null);
    assert.equal(first.replayEngine.replayCursor, null);
    assert.equal(first.replayEngine.projection.currentEvent, null);
    for (const duplicate of [
        "replayCursor", "playbackState", "loadingState", "errorState",
        "replayDataset", "replayProjection", "replayMachine", "dataQuality",
    ]) {
        assert.equal(Object.hasOwn(first, duplicate), false);
    }
    assert.notEqual(first, second);
    assert.notEqual(first.replayEngine, second.replayEngine);
});

test("command action creators converge on APPLY_REPLAY_COMMAND", () => {
    for (const action of [
        loadReplayDataset(XRP_REPLAY_FIXTURE),
        playReplay(),
        pauseReplay(),
        stepReplayForward(),
        seekReplay(XRP_REPLAY_FIXTURE.startedAt),
        resetReplay(),
    ]) {
        assert.equal(action.type, "APPLY_REPLAY_COMMAND");
        assert.equal(typeof action.payload.command.type, "string");
    }
});

test("reducer command results match direct replay engine application", () => {
    let state = createInitialState();
    const commands = [
        { type: C.LOAD_DATASET, payload: { dataset: XRP_REPLAY_FIXTURE } },
        { type: C.PLAY },
        { type: C.PAUSE },
        { type: C.STEP_FORWARD },
        { type: C.SEEK, payload: { timestamp: "2026-07-20T12:00:45.000Z" } },
        { type: C.RESET },
    ];
    for (const command of commands) {
        const expected = applyReplayCommand(state.replayEngine, command);
        state = reduce(state, applyReplayCommandAction(command));
        assert.deepEqual(state.replayEngine, expected);
    }
});

test("reducer stores rejected engine results without changing replay contents", () => {
    const loaded = reduce(createInitialState(), loadReplayDataset(XRP_REPLAY_FIXTURE));
    const replayBefore = loaded.replayEngine;
    for (const action of [applyReplayCommandAction(null), {
        type: "APPLY_REPLAY_COMMAND",
    }]) {
        const next = reduce(loaded, action);
        assert.equal(next.replayEngine.accepted, false);
        assert.equal(typeof next.replayEngine.rejectionReason, "string");
        assert.equal(next.replayEngine.dataset, replayBefore.dataset);
        assert.equal(next.replayEngine.replayCursor, replayBefore.replayCursor);
    }
    const playing = reduce(loaded, playReplay());
    const rejected = reduce(playing, playReplay());
    assert.equal(rejected.replayEngine.accepted, false);
    assert.equal(rejected.replayEngine.machine.transitionCount,
        playing.replayEngine.machine.transitionCount);
});

test("all replay selectors derive from replayEngine", () => {
    const state = reduce(createInitialState(), loadReplayDataset(XRP_REPLAY_FIXTURE));
    const engine = state.replayEngine;
    assert.equal(selectReplayEngine(state), engine);
    assert.equal(selectReplayDataset(state), engine.dataset);
    assert.equal(selectReplayCursor(state), engine.replayCursor);
    assert.equal(selectReplayMachine(state), engine.machine);
    assert.equal(selectReplayMachineState(state), engine.machine.state);
    assert.equal(selectReplayProjection(state), engine.projection);
    assert.equal(selectReplayCurrentEvent(state), engine.projection.currentEvent);
    assert.equal(selectReplayVisibleEvents(state), engine.projection.visibleEvents);
    assert.equal(selectReplayPositionContext(state), engine.projection.positionContext);
    assert.equal(selectReplayDecisionContext(state), engine.projection.decisionContext);
    assert.equal(selectReplayMarkerContext(state), engine.projection.markerContext);
    assert.equal(selectReplayStationContext(state), engine.projection.stationContext);
    assert.equal(selectReplayTimeline(state), engine.projection.timeline);
    assert.equal(selectReplayProgress(state), engine.projection.progress);
    assert.equal(selectReplayIsAtStart(state), engine.projection.isAtStart);
    assert.equal(selectReplayIsAtEnd(state), engine.projection.isAtEnd);
    assert.equal(selectReplayAccepted(state), engine.accepted);
    assert.equal(selectReplayRejectionReason(state), engine.rejectionReason);
    assert.equal(selectReplayError(state), null);
});

test("compatibility selectors derive values without duplicate state", () => {
    let state = reduce(createInitialState(), loadReplayDataset(XRP_REPLAY_FIXTURE));
    assert.equal(getReplayCursor(state), state.replayEngine.replayCursor);
    assert.equal(getPlaybackState(state), S.REPLAY_READY);
    assert.equal(selectPlaybackState(state), S.REPLAY_READY);
    assert.equal(getLoadingState(state), false);
    assert.equal(selectLoadingState(state), false);
    assert.equal(getErrorState(state), null);
    assert.equal(selectErrorState(state), null);
    assert.equal(getDataQuality(state), state.replayEngine.projection.dataQuality);
    state = reduce(reduce(createInitialState(), applyReplayCommandAction({
        type: C.LOAD_FAILURE,
        payload: { code: "FAIL", message: "Failed." },
    })), applyReplayCommandAction({ type: C.RETRY }));
    assert.equal(getLoadingState(state), true);
});

test("selection actions remain independent from replay commands and reset", () => {
    const selections = {
        position: { id: "position-1" },
        decision: { id: "decision-1" },
        marker: { id: "marker-1" },
        station: { id: "station-1" },
    };
    let state = createInitialState();
    state = reduce(state, selectPosition(selections.position));
    state = reduce(state, selectDecision(selections.decision));
    state = reduce(state, selectMarker(selections.marker));
    state = reduce(state, selectStation(selections.station));
    const selectionState = state;
    state = reduce(state, loadReplayDataset(XRP_REPLAY_FIXTURE));
    state = reduce(state, resetReplay());
    assert.equal(getSelectedPosition(state), selections.position);
    assert.equal(getSelectedDecision(state), selections.decision);
    assert.equal(getSelectedMarker(state), selections.marker);
    assert.equal(getSelectedStation(state), selections.station);
    assert.equal(state.selectedPosition, selectionState.selectedPosition);
});

test("reducer does not mutate state, engine, action, or selection objects", () => {
    const selection = { id: "position-1", nested: { stable: true } };
    let state = reduce(createInitialState(), selectPosition(selection));
    state = reduce(state, loadReplayDataset(structuredClone(XRP_REPLAY_FIXTURE)));
    const stateBefore = structuredClone(state);
    const action = seekReplay("2026-07-20T12:00:45.000Z");
    const actionBefore = structuredClone(action);
    reduce(state, action);
    assert.deepEqual(state, stateBefore);
    assert.deepEqual(action, actionBefore);
    assert.deepEqual(selection, { id: "position-1", nested: { stable: true } });
});

test("unknown and null actions preserve the provider state reference", () => {
    const state = createInitialState();
    assert.equal(reduce(state, { type: "UNKNOWN_ACTION" }), state);
    assert.equal(reduce(state, null), state);
});

test("Provider exposes replay engine and command application and updates context", async () => {
    const { MarketIntelligenceProvider, useMarketIntelligence } = await getProviderModule();
    const Consumer = () => useMarketIntelligence();
    const renderer = createProviderRenderer(MarketIntelligenceProvider, Consumer);
    assert.equal(renderer.result.replayEngine.machine.state, S.IDLE);
    assert.equal(renderer.result.replayEngine.dataset, null);
    assert.equal(typeof renderer.result.dispatch, "function");
    assert.equal(typeof renderer.result.applyReplayCommand, "function");
    renderer.result.applyReplayCommand({
        type: C.LOAD_DATASET,
        payload: { dataset: XRP_REPLAY_FIXTURE },
    });
    renderer.render();
    assert.equal(renderer.result.replayEngine.machine.state, S.REPLAY_READY);
    assert.equal(renderer.result.state.replayEngine, renderer.result.replayEngine);
});

test("useMarketIntelligence rejects consumers outside the Provider", async () => {
    const { useMarketIntelligence } = await getProviderModule();
    const renderer = createProviderRenderer(
        ({ children }) => React.createElement(React.Fragment, null, children),
        () => null,
    );
    assert.throws(
        () => renderer.withDispatcher(() => useMarketIntelligence()),
        { message: "useMarketIntelligence must be used within MarketIntelligenceProvider." },
    );
});
