import assert from "node:assert/strict";
import test from "node:test";

import {
  createMoneyManagementPollingController,
} from "./moneyManagementPolling.js";

class Scheduler {
  constructor() {
    this.now = 0;
    this.nextId = 1;
    this.tasks = new Map();
  }

  setTimer = (callback, delay) => {
    const id = this.nextId++;
    this.tasks.set(id, { callback, at: this.now + delay, delay });
    return id;
  };

  clearTimer = (id) => {
    this.tasks.delete(id);
  };

  advance(ms) {
    const target = this.now + ms;
    while (true) {
      const next = [...this.tasks.entries()]
        .filter(([, task]) => task.at <= target)
        .sort((left, right) => left[1].at - right[1].at)[0];
      if (!next) break;
      const [id, task] = next;
      this.tasks.delete(id);
      this.now = task.at;
      task.callback();
    }
    this.now = target;
  }

  delays() {
    return [...this.tasks.values()].map((task) => task.delay).sort();
  }
}

class FakeDocument {
  constructor() {
    this.visibilityState = "visible";
    this.listeners = new Set();
  }

  addEventListener(_name, listener) {
    this.listeners.add(listener);
  }

  removeEventListener(_name, listener) {
    this.listeners.delete(listener);
  }

  setVisibility(value) {
    this.visibilityState = value;
    for (const listener of this.listeners) listener();
  }
}

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => {
    setTimeout(resolve, 0);
  });
};

test("polling runs immediately, repeats, and stops cleanly", async () => {
  const scheduler = new Scheduler();
  let calls = 0;
  const states = [];
  const controller = createMoneyManagementPollingController({
    fetchStatus: async () => ++calls,
    onPollingState: (state) => states.push(state),
    pollingIntervalMs: 1000,
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
    now: () => scheduler.now,
  });
  controller.start();
  await flush();
  assert.equal(calls, 1);
  scheduler.advance(1000);
  await flush();
  assert.equal(calls, 2);
  assert.equal(controller.stop(), true);
  scheduler.advance(10000);
  await flush();
  assert.equal(calls, 2);
  assert.deepEqual(states, ["RUNNING", "STOPPED"]);
});

test("overlap is prevented and superseded old response is discarded", async () => {
  const pending = [];
  const successes = [];
  const controller = createMoneyManagementPollingController({
    fetchStatus: ({ requestId }) =>
      new Promise((resolve) => pending.push({ requestId, resolve })),
    onSuccess: ({ result }) => successes.push(result),
    pollingIntervalMs: 1000,
  });
  controller.start();
  await flush();
  const shared = controller.refresh();
  assert.equal(pending.length, 1);
  assert.equal(controller.getSnapshot().requestInFlight, true);
  void shared;
  controller.refresh({ supersede: true });
  await flush();
  assert.equal(pending.length, 2);
  pending[1].resolve("new");
  await flush();
  pending[0].resolve("old");
  await flush();
  assert.deepEqual(successes, ["new"]);
  controller.stop();
});

test("unmount stop aborts an in-flight request", async () => {
  let aborted = false;
  const controller = createMoneyManagementPollingController({
    fetchStatus: ({ signal }) =>
      new Promise((resolve) => {
        signal.addEventListener("abort", () => {
          aborted = true;
          resolve(null);
        });
      }),
    pollingIntervalMs: 1000,
  });
  controller.start();
  await flush();
  controller.stop();
  await flush();
  assert.equal(aborted, true);
  assert.equal(controller.getSnapshot().pollingState, "STOPPED");
});

test("hidden visibility suspends polling and resumes with refresh", async () => {
  const documentRef = new FakeDocument();
  let calls = 0;
  const states = [];
  const stale = [];
  const controller = createMoneyManagementPollingController({
    fetchStatus: async () => ++calls,
    onPollingState: (value) => states.push(value),
    onStale: (value) => stale.push(value),
    pollingIntervalMs: 1000,
    documentRef,
  });
  controller.start();
  await flush();
  assert.equal(calls, 1);
  documentRef.setVisibility("hidden");
  assert.equal(controller.getSnapshot().pollingState, "SUSPENDED");
  documentRef.setVisibility("visible");
  await flush();
  assert.equal(calls, 2);
  assert.ok(states.includes("SUSPENDED"));
  assert.ok(stale.includes(true));
  controller.stop();
});

test("failures use bounded exponential backoff and mark stale", async () => {
  const scheduler = new Scheduler();
  const errors = [];
  const stale = [];
  const controller = createMoneyManagementPollingController({
    fetchStatus: async () => {
      throw new Error("offline");
    },
    onError: (value) => errors.push(value.consecutiveFailures),
    onStale: (value) => stale.push(value),
    pollingIntervalMs: 1000,
    maximumBackoffMs: 3000,
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
  });
  controller.start();
  await flush();
  assert.deepEqual(errors, [1]);
  assert.deepEqual(scheduler.delays(), [1000]);
  scheduler.advance(1000);
  await flush();
  assert.deepEqual(errors, [1, 2]);
  assert.deepEqual(scheduler.delays(), [2000]);
  scheduler.advance(2000);
  await flush();
  assert.deepEqual(errors, [1, 2, 3]);
  assert.deepEqual(scheduler.delays(), [3000]);
  assert.ok(stale.every(Boolean));
  controller.stop();
});
