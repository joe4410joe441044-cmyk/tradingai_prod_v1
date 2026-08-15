import assert from "node:assert/strict";
import test from "node:test";

globalThis.window = {
    location: {
        protocol: "http:",
        host: "localhost",
    },
};

const {
    createAdvisorRuntimePoller,
    initialAdvisorRuntimeState,
} = await import("./useAdvisorRuntime.js");

const flush = () => new Promise((resolve) => queueMicrotask(resolve));
const stateHarness = () => {
    let state = { ...initialAdvisorRuntimeState };
    return {
        get: () => state,
        set: (next) => {
            state = typeof next === "function" ? next(state) : next;
        },
    };
};

test("poller fetches immediately and schedules a five second retry", async () => {
    const state = stateHarness();
    const timers = [];
    const poller = createAdvisorRuntimePoller({
        request: async () => ({ data: { id: 1 }, receivedAt: 10 }),
        onState: state.set,
        setTimer: (callback, delay) => {
            timers.push({ callback, delay });
            return timers.length;
        },
        clearTimer: () => {},
    });

    await poller.start();

    assert.equal(state.get().connectionState, "CONNECTED");
    assert.equal(timers[0].delay, 5000);
});

test("poller prevents overlap and aborts the in-flight request on stop", async () => {
    const state = stateHarness();
    let requestSignal;
    let resolveRequest;
    const request = (signal) => {
        requestSignal = signal;
        return new Promise((resolve) => { resolveRequest = resolve; });
    };
    const poller = createAdvisorRuntimePoller({
        request,
        onState: state.set,
        setTimer: () => 1,
        clearTimer: () => {},
    });

    const first = poller.start();
    assert.equal(await poller.retry(), false);
    poller.stop();
    assert.equal(requestSignal.aborted, true);
    resolveRequest({ data: { id: 1 }, receivedAt: 10 });
    await first;
});

test("intentional AbortError does not create a visible error", async () => {
    const state = stateHarness();
    const poller = createAdvisorRuntimePoller({
        request: async () => {
            throw new DOMException("aborted", "AbortError");
        },
        onState: state.set,
        setTimer: () => 1,
        clearTimer: () => {},
    });

    await poller.start();

    assert.equal(state.get().error, null);
    assert.equal(state.get().connectionState, "LOADING");
    poller.stop();
});

test("poller.reset invalidates last-good runtime state", async () => {
    const state = stateHarness();
    const timers = [];
    let attempt = 0;
    const poller = createAdvisorRuntimePoller({
        request: async () => {
            attempt += 1;
            return { data: { id: attempt }, receivedAt: attempt * 100 };
        },
        onState: state.set,
        setTimer: (callback) => {
            timers.push(callback);
            return timers.length;
        },
        clearTimer: () => {},
    });

    await poller.start();
    assert.equal(state.get().connectionState, "CONNECTED");
    assert.deepEqual(state.get().data, { id: 1 });

    poller.reset();
    assert.equal(state.get().connectionState, "DISCONNECTED");
    assert.equal(state.get().data, null);
    assert.equal(state.get().error, null);
    assert.equal(state.get().lastSuccessfulAt, null);
    poller.stop();
});

test("poller reset aborts an in-flight request", async () => {
    const state = stateHarness();
    let requestSignal;
    const request = (signal) => {
        requestSignal = signal;
        return new Promise((resolve) => resolve({ data: { id: 1 }, receivedAt: 10 }));
    };
    const poller = createAdvisorRuntimePoller({
        request,
        onState: state.set,
        setTimer: () => 1,
        clearTimer: () => {},
    });

    const first = poller.start();
    assert.equal(requestSignal.aborted, false);
    poller.reset();
    assert.equal(requestSignal.aborted, true);
    assert.equal(state.get().connectionState, "DISCONNECTED");
    await first;
});

test("poller retries after error and preserves last-good data when degraded", async () => {
    const state = stateHarness();
    const timers = [];
    let attempt = 0;
    const poller = createAdvisorRuntimePoller({
        request: async () => {
            attempt += 1;
            if (attempt === 2) throw Object.assign(new Error("offline"), {
                retryable: true,
            });
            return { data: { id: attempt }, receivedAt: attempt * 100 };
        },
        onState: state.set,
        setTimer: (callback) => {
            timers.push(callback);
            return timers.length;
        },
        clearTimer: () => {},
    });

    await poller.start();
    await timers.shift()();
    await flush();

    assert.deepEqual(state.get().data, { id: 1 });
    assert.equal(state.get().connectionState, "DEGRADED");
    assert.equal(state.get().lastSuccessfulAt, 100);

    await poller.retry();
    assert.deepEqual(state.get().data, { id: 3 });
    assert.equal(state.get().connectionState, "CONNECTED");
    poller.stop();
});
