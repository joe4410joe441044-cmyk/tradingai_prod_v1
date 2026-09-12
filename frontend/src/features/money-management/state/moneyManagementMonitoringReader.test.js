import assert from "node:assert/strict";
import test from "node:test";
import { createMonitoringReader } from "./moneyManagementMonitoringReader.js";
import { monitoringFixture, historyFixture, legacyFixture } from "../contracts/moneyManagementMonitoringFixtures.js";
import { loadMoneyManagementAnalyticsHistory, filterMoneyManagementAnalyticsEvents } from "../analytics/moneyManagementAnalytics.js";
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

for (const authority of ["PAPER", "LIVE"]) {
  test(`${authority} history excludes opposite authority and 92% UNKNOWN fixture across pagination and periods`, async () => {
    const calls = [];
    const events = await loadMoneyManagementAnalyticsHistory({ authority, client: async query => {
      calls.push(query);
      return { events: [historyFixture("PAPER", calls.length), historyFixture("LIVE", calls.length), legacyFixture], hasMore: calls.length === 1, nextCursor: "2" };
    } });
    assert.equal(calls.length, 2);
    assert.ok(calls.every(q => q.authority === authority));
    assert.equal(events.length, 2);
    for (const period of ["7D", "30D", "ALL"]) {
      const filtered = filterMoneyManagementAnalyticsEvents(events, period, Date.parse("2026-09-12T12:00:00Z"));
      assert.equal(filtered.length, 2);
      assert.ok(filtered.every(e => e.authority === authority));
      assert.ok(!filtered.some(e => e.metrics.drawdownPercent === "92.088"));
    }
    assert.equal(legacyFixture.metrics.drawdownPercent, "92.088");
  });
  test(`${authority} request errors clear snapshots and history`, async () => {
    let state;
    const reader = createMonitoringReader({ getMonitoring: async () => { throw Error(); }, getHistory: async () => { throw Error(); }, onChange: s => { state = s; } });
    await reader.load(authority);
    assert.equal(state.monitoringState, "ERROR"); assert.equal(state.monitoring, null);
    assert.equal(state.historyState, "ERROR"); assert.deepEqual(state.history, []);
    reader.stop();
  });
}
test("rapid PAPER LIVE PAPER ignores old responses even when abort is ignored", async () => {
  const requests = []; const states = [];
  const reader = createMonitoringReader({
    getMonitoring: authority => { const d = deferred(); requests.push({ ...d, authority }); return d.promise; },
    getHistory: async () => ({ events: [historyFixture("PAPER"), historyFixture("LIVE"), legacyFixture] }),
    onChange: state => states.push(state),
  });
  const first = reader.load("PAPER"); const second = reader.load("LIVE"); const third = reader.load("PAPER");
  assert.equal(states.at(-1).monitoring, null); assert.deepEqual(states.at(-1).history, []);
  requests[2].resolve(monitoringFixture("PAPER")); await third;
  const latest = states.at(-1);
  requests[1].resolve(monitoringFixture("LIVE")); requests[0].resolve(monitoringFixture("PAPER", "STALE"));
  await Promise.all([first, second]);
  assert.equal(states.at(-1), latest);
  assert.equal(latest.authority, "PAPER"); assert.equal(latest.monitoring.freshness, "LAST_KNOWN");
  assert.ok(latest.history.every(e => e.authority === "PAPER")); reader.stop();
});
test("stopped reader publishes no in-flight responses", async () => {
  const d = deferred(); const states = [];
  const reader = createMonitoringReader({ getMonitoring: () => d.promise, getHistory: async () => ({ events: [] }), onChange: s => states.push(s) });
  const pending = reader.load("LIVE"); reader.stop(); const count = states.length;
  d.resolve(monitoringFixture("LIVE")); await pending; assert.equal(states.length, count);
});

for (const authority of ["PAPER", "LIVE"]) {
  for (const first of ["monitoring", "history"]) {
    test(`${authority} refresh preserves READY history with ${first} first and complete pagination`, async () => {
      const states = [];
      let pending = false;
      const monitoring = deferred(), history = deferred(), lastPage = deferred();
      const reader = createMonitoringReader({
        getMonitoring: () => pending ? monitoring.promise : Promise.resolve(monitoringFixture(authority, "STALE")),
        getHistory: query => pending ? (query.before ? lastPage.promise : history.promise) : Promise.resolve({ events: [historyFixture(authority)] }),
        onChange: state => states.push(state),
      });
      const initial = reader.load(authority);
      assert.equal(states.at(-1).historyState, "LOADING");
      await initial;
      const previous = states.at(-1);
      pending = true;
      const refresh = reader.load(authority);
      assert.equal(states.at(-1), previous);
      const finishMonitoring = () => monitoring.resolve(monitoringFixture(authority));
      const finishHistory = () => history.resolve({ events: [historyFixture(authority, 2), legacyFixture], hasMore: true, nextCursor: "2" });
      (first === "monitoring" ? finishMonitoring : finishHistory)();
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(states.at(-1).history, previous.history);
      assert.equal(states.at(-1).historyState, "READY");
      if (first === "history") assert.equal(states.at(-1).monitoring.freshness, "STALE");
      if (first === "monitoring") {
        finishHistory();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(states.at(-1).history, previous.history);
      }
      lastPage.resolve({ events: [historyFixture(authority, 3)], hasMore: false });
      await new Promise(resolve => setImmediate(resolve));
      if (first === "history") {
        assert.deepEqual(states.at(-1).history.map(e => e.sequence), [2, 3]);
        assert.equal(states.at(-1).monitoring.freshness, "STALE");
        finishMonitoring();
      }
      await refresh;
      assert.deepEqual(states.at(-1).history.map(e => e.sequence), [2, 3]);
      assert.ok(states.slice(states.indexOf(previous)).every(s => s.historyState === "READY" && s.history.length));
      reader.stop();
    });
  }
  test(`${authority} transition clears old graph immediately and transition errors cannot leak`, async () => {
    let state, fail = false;
    const reader = createMonitoringReader({
      getMonitoring: async a => { if (fail) throw Error(); return monitoringFixture(a); },
      getHistory: async () => { if (fail) throw Error(); return { events: [historyFixture(authority)] }; },
      onChange: s => { state = s; },
    });
    await reader.load(authority);
    fail = true;
    const next = reader.load(authority === "PAPER" ? "LIVE" : "PAPER");
    assert.equal(state.monitoring, null); assert.deepEqual(state.history, []);
    assert.equal(state.historyState, "LOADING");
    await next;
    assert.equal(state.historyState, "ERROR"); assert.equal(state.monitoringState, "ERROR");
  });
  test(`${authority} explicit empty, unavailable and refresh failure retain truthful semantics`, async () => {
    let state, phase = "valid";
    const reader = createMonitoringReader({
      getMonitoring: async () => { if (phase === "error") throw Error(); return monitoringFixture(authority, phase === "empty" ? "UNAVAILABLE" : "LAST_KNOWN"); },
      getHistory: async () => { if (phase === "error") throw Error(); return { events: phase === "empty" ? [] : [historyFixture(authority)] }; },
      onChange: s => { state = s; },
    });
    await reader.load(authority);
    phase = "empty"; await reader.load(authority);
    assert.equal(state.historyState, "READY"); assert.deepEqual(state.history, []);
    assert.equal(state.monitoringState, "UNAVAILABLE"); assert.equal(state.monitoring.snapshot, null);
    phase = "valid"; await reader.load(authority);
    phase = "error"; const failure = reader.load(authority);
    assert.equal(state.historyState, "READY"); assert.equal(state.monitoringState, "LAST_KNOWN");
    await failure;
    assert.equal(state.historyState, "ERROR"); assert.deepEqual(state.history, []);
    assert.equal(state.monitoringState, "ERROR"); assert.equal(state.monitoring, null);
  });
}
test("superseded same-authority refresh and stop cannot publish late data or clear READY state", async () => {
  let state, pending = false;
  const requests = [];
  const reader = createMonitoringReader({
    getMonitoring: async () => monitoringFixture("PAPER"),
    getHistory: () => { if (!pending) return Promise.resolve({ events: [historyFixture("PAPER")] }); const d = deferred(); requests.push(d); return d.promise; },
    onChange: s => { state = s; },
  });
  await reader.load("PAPER"); pending = true;
  const old = reader.load("PAPER"), newer = reader.load("PAPER");
  assert.equal(state.historyState, "READY");
  requests[1].resolve({ events: [historyFixture("PAPER", 3)] }); await newer;
  const latest = state;
  requests[0].resolve({ events: [] }); await old; assert.equal(state, latest);
  const stopped = reader.load("PAPER"); reader.stop(); const stoppedState = state;
  requests[2].resolve({ events: [] }); await stopped; assert.equal(state, stoppedState);
});
test("invalid View and invalid refreshed accounting source never become retained data", async () => {
  let state, invalid = false;
  const reader = createMonitoringReader({
    getMonitoring: async () => {
      const value = monitoringFixture("PAPER");
      if (invalid) value.snapshot.accountingAuthoritySource = "REAL_LIVE_ACCOUNT_EQUITY";
      return value;
    },
    getHistory: async () => ({ events: [legacyFixture, historyFixture("LIVE"), { ...historyFixture("PAPER"), accountingAuthoritySource: invalid ? "UNKNOWN" : "PAPER_RUNTIME_EQUITY" }] }),
    onChange: s => { state = s; },
  });
  await reader.load("PAPER"); const previous = state;
  await assert.rejects(reader.load("UNKNOWN"), /Invalid monitoring View/);
  assert.equal(state, previous);
  invalid = true; await reader.load("PAPER");
  assert.equal(state.monitoringState, "ERROR"); assert.equal(state.monitoring, null);
  assert.equal(state.historyState, "READY"); assert.deepEqual(state.history, []);
});
