import assert from "node:assert/strict";
import test from "node:test";
import { initialViewAuthority, normalizeMonitoringResponse, requireViewAuthority, requireHistoryAuthority, realizedPnlLabel } from "./moneyManagementMonitoringContracts.js";
import { monitoringFixture } from "./moneyManagementMonitoringFixtures.js";
import { getMoneyManagementMonitoring, getMoneyManagementHistory } from "../api/moneyManagementApi.js";
import { createMonitoringViewModel } from "../view/moneyManagementMonitoringViewModel.js";

for (const mode of ["PAPER", "LIVE", "STOPPED", undefined, "bad"]) {
  test(`initial runtime ${mode} selects deterministic View`, () => assert.equal(initialViewAuthority(mode), mode === "LIVE" ? "LIVE" : "PAPER"));
}
test("invalid monitoring and history authorities fail closed", () => {
  for (const value of [null, undefined, "UNKNOWN", "ALL", "live", "bad"]) assert.throws(() => requireViewAuthority(value));
  for (const value of ["ALL", "PAPER", "LIVE", "UNKNOWN"]) assert.equal(requireHistoryAuthority(value), value);
  assert.throws(() => requireHistoryAuthority("bad"));
});
for (const authority of ["PAPER", "LIVE"]) {
  for (const freshness of ["LAST_KNOWN", "STALE", "UNAVAILABLE"]) {
    test(`${authority} ${freshness} contract and summary retain truthful availability`, () => {
      const monitoring = normalizeMonitoringResponse(monitoringFixture(authority, freshness), authority);
      const vm = createMonitoringViewModel({ authority, monitoring, monitoringState: freshness });
      assert.equal(vm.state, freshness);
      assert.equal(vm.capital[0].value.unavailable, freshness === "UNAVAILABLE");
      assert.equal(vm.performance[0].label, realizedPnlLabel(authority));
      assert.equal(vm.performance[0].value.text, freshness === "UNAVAILABLE" ? "—" : authority === "LIVE" ? "22.50" : "11.25");
      assert.doesNotMatch(JSON.stringify(vm), /ENTRY ALLOWED|Cumulative|CURRENT/);
    });
  }
  test(`${authority} rejects cross-authority, mislabeled PnL and CURRENT responses`, () => {
    for (const modify of [r => {r.dataAuthority = "UNKNOWN";}, r => {r.snapshot.authority = "UNKNOWN";}, r => {r.snapshot.accountingAuthoritySource = "invalid";}, r => {r.snapshot.realizedPnlSemantics = "UNSPECIFIED";}, r => {r.semantics = "CURRENT";}, r => {r.freshness = "CURRENT";}, r => {r.asOf = "invalid";}, r => {r.snapshot.riskState = {};}, r => {r.snapshot.metrics.openPositionState = {};}]) {
      const raw = monitoringFixture(authority); modify(raw);
      assert.throws(() => normalizeMonitoringResponse(raw, authority));
    }
  });
  test(`${authority} API uses only GET with explicit authority`, async () => {
    const calls = [];
    const fetchImpl = async (url, options) => { calls.push({ url, method: options.method }); return { ok: true, text: async () => "{}" }; };
    await getMoneyManagementMonitoring(authority, { fetchImpl });
    await getMoneyManagementHistory({ authority }, { fetchImpl });
    assert.deepEqual(calls, [
      { url: `/api/money-management/monitoring?viewAuthority=${authority}`, method: "GET" },
      { url: `/api/money-management/history?authority=${authority}`, method: "GET" },
    ]);
  });
}
