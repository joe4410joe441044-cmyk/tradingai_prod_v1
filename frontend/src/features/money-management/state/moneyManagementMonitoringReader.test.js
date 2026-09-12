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
