import assert from "node:assert/strict";
import test from "node:test";

import {
    AI_ADVISOR_PATH,
    SUPERVISOR_PATH,
    navigateAiHelp,
    setAiHelpScrollTarget,
    consumeAiHelpScrollTarget,
    focusAiHelpTarget,
} from "./aiHelpRouting.js";

const SCROLL_TARGET_KEY = "tradingai:ai-help-scroll-target";

const installDom = (pathname) => {
    const storage = new Map();
    const events = [];
    const focusCalls = [];
    const scrollCalls = [];
    const pushCalls = [];
    const requestedIds = [];
    const node = {
        scrollIntoView: (opts) => scrollCalls.push(opts),
        focus: (opts) => focusCalls.push(opts),
    };
    const windowMock = {
        location: { pathname },
        sessionStorage: {
            getItem: (key) => (storage.has(key) ? storage.get(key) : null),
            setItem: (key, value) => storage.set(key, String(value)),
            removeItem: (key) => storage.delete(key),
        },
        history: {
            pushState: (_state, _title, path) => {
                pushCalls.push(path);
                windowMock.location.pathname = path;
            },
        },
        dispatchEvent: (event) => events.push(event.type),
    };
    const documentMock = {
        getElementById: (id) => {
            requestedIds.push(id);
            return id ? node : null;
        },
    };
    const previous = {
        window: globalThis.window,
        document: globalThis.document,
        PopStateEvent: globalThis.PopStateEvent,
        requestAnimationFrame: globalThis.requestAnimationFrame,
    };
    globalThis.window = windowMock;
    globalThis.document = documentMock;
    globalThis.PopStateEvent = class {
        constructor(type) {
            this.type = type;
        }
    };
    globalThis.requestAnimationFrame = (callback) => callback();

    return {
        window: windowMock,
        storage,
        events,
        focusCalls,
        scrollCalls,
        pushCalls,
        requestedIds,
        restore() {
            if (previous.window === undefined) {
                delete globalThis.window;
            } else {
                globalThis.window = previous.window;
            }
            if (previous.document === undefined) {
                delete globalThis.document;
            } else {
                globalThis.document = previous.document;
            }
            if (previous.PopStateEvent === undefined) {
                delete globalThis.PopStateEvent;
            } else {
                globalThis.PopStateEvent = previous.PopStateEvent;
            }
            if (previous.requestAnimationFrame === undefined) {
                delete globalThis.requestAnimationFrame;
            } else {
                globalThis.requestAnimationFrame = previous.requestAnimationFrame;
            }
        },
    };
};

test("Advisor -> Master navigates to Supervisor and stores the Master focus target", () => {
    const env = installDom("/ai-advisor");
    let closed = 0;
    navigateAiHelp("master", { onClose: () => { closed += 1; } });
    assert.equal(closed, 1, "drawer must close after selection");
    assert.deepEqual(env.pushCalls, [SUPERVISOR_PATH]);
    assert.deepEqual(env.events, ["popstate"]);
    assert.equal(env.storage.get(SCROLL_TARGET_KEY), "master-supervisor-heading");
    assert.equal(env.window.location.pathname, SUPERVISOR_PATH);
    env.restore();
});

test("Advisor -> MM navigates to Supervisor and stores the MM focus target", () => {
    const env = installDom("/ai-advisor");
    let closed = 0;
    navigateAiHelp("mm", { onClose: () => { closed += 1; } });
    assert.equal(closed, 1);
    assert.deepEqual(env.pushCalls, [SUPERVISOR_PATH]);
    assert.equal(env.storage.get(SCROLL_TARGET_KEY), "mm-supervisor-heading");
    env.restore();
});

test("Advisor -> Advisor stays on the same page and focuses the Prompt Input", () => {
    const env = installDom("/ai-advisor");
    let closed = 0;
    navigateAiHelp("advisor", { onClose: () => { closed += 1; } });
    assert.equal(closed, 1);
    assert.deepEqual(env.pushCalls, []);
    assert.deepEqual(env.events, []);
    assert.equal(env.storage.has(SCROLL_TARGET_KEY), false);
    assert.ok(env.requestedIds.includes("advisor-prompt"));
    assert.deepEqual(env.scrollCalls, [{ block: "start" }]);
    assert.deepEqual(env.focusCalls, [{ preventScroll: true }]);
    env.restore();
});

test("Supervisor -> Master stays on the same page and focuses Master Supervisor", () => {
    const env = installDom("/supervisor");
    let closed = 0;
    navigateAiHelp("master", { onClose: () => { closed += 1; } });
    assert.equal(closed, 1);
    assert.deepEqual(env.pushCalls, []);
    assert.ok(env.requestedIds.includes("master-supervisor-heading"));
    env.restore();
});

test("Supervisor -> MM stays on the same page and focuses MM Supervisor", () => {
    const env = installDom("/supervisor");
    let closed = 0;
    navigateAiHelp("mm", { onClose: () => { closed += 1; } });
    assert.equal(closed, 1);
    assert.deepEqual(env.pushCalls, []);
    assert.ok(env.requestedIds.includes("mm-supervisor-heading"));
    env.restore();
});

test("Supervisor -> Advisor navigates to AI Advisor and stores the Prompt Input target", () => {
    const env = installDom("/supervisor");
    let closed = 0;
    navigateAiHelp("advisor", { onClose: () => { closed += 1; } });
    assert.equal(closed, 1);
    assert.deepEqual(env.pushCalls, [AI_ADVISOR_PATH]);
    assert.equal(env.storage.get(SCROLL_TARGET_KEY), "advisor-prompt");
    env.restore();
});

test("consumeAiHelpScrollTarget returns and clears the stored intent", () => {
    const env = installDom("/supervisor");
    setAiHelpScrollTarget("mm-supervisor-heading");
    assert.equal(env.storage.get(SCROLL_TARGET_KEY), "mm-supervisor-heading");
    assert.equal(consumeAiHelpScrollTarget(), "mm-supervisor-heading");
    assert.equal(env.storage.has(SCROLL_TARGET_KEY), false);
    assert.equal(consumeAiHelpScrollTarget(), null);
    env.restore();
});

test("focusAiHelpTarget scrolls and focuses the requested target", () => {
    const env = installDom("/supervisor");
    focusAiHelpTarget("master-supervisor-heading");
    assert.deepEqual(env.scrollCalls, [{ block: "start" }]);
    assert.deepEqual(env.focusCalls, [{ preventScroll: true }]);
    env.restore();
});

test("unknown target is a no-op and does not close the drawer or navigate", () => {
    const env = installDom("/supervisor");
    let closed = 0;
    navigateAiHelp("bogus", { onClose: () => { closed += 1; } });
    assert.equal(closed, 0);
    assert.deepEqual(env.pushCalls, []);
    assert.deepEqual(env.events, []);
    env.restore();
});

test("navigation never submits a prompt or issues a provider request", () => {
    const env = installDom("/ai-advisor");
    let fetchCalls = 0;
    const previousFetch = globalThis.fetch;
    globalThis.fetch = () => {
        fetchCalls += 1;
        throw new Error("navigation must not issue a provider request");
    };
    try {
        navigateAiHelp("master", { onClose: () => {} });
        assert.equal(fetchCalls, 0);
        assert.equal(env.storage.has(SCROLL_TARGET_KEY), true);
    } finally {
        if (previousFetch === undefined) {
            delete globalThis.fetch;
        } else {
            globalThis.fetch = previousFetch;
        }
        env.restore();
    }
});
