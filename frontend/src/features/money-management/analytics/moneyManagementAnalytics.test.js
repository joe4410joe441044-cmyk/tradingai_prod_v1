import assert from "node:assert/strict";
import test from "node:test";

import {
  filterMoneyManagementAnalyticsEvents,
  loadMoneyManagementAnalyticsHistory,
  MONEY_MANAGEMENT_ANALYTICS_PERIOD,
} from "./moneyManagementAnalytics.js";

const NOW = Date.parse("2026-07-29T00:00:00Z");

const event = (sequence, timestamp) => ({ sequence, timestamp });

test("7D, 30D, and ALL filter one shared event history without mutation", () => {
  const events = [
    event(1, "2026-06-01T00:00:00Z"),
    event(2, "2026-07-05T00:00:00Z"),
    event(3, "2026-07-23T00:00:00Z"),
    event(4, "2026-07-29T00:00:00Z"),
  ];

  assert.deepEqual(
    filterMoneyManagementAnalyticsEvents(
      events,
      MONEY_MANAGEMENT_ANALYTICS_PERIOD.SEVEN_DAYS,
      NOW,
    ).map(({ sequence }) => sequence),
    [3, 4],
  );
  assert.deepEqual(
    filterMoneyManagementAnalyticsEvents(
      events,
      MONEY_MANAGEMENT_ANALYTICS_PERIOD.THIRTY_DAYS,
      NOW,
    ).map(({ sequence }) => sequence),
    [2, 3, 4],
  );
  assert.deepEqual(
    filterMoneyManagementAnalyticsEvents(
      events,
      MONEY_MANAGEMENT_ANALYTICS_PERIOD.ALL,
      NOW,
    ).map(({ sequence }) => sequence),
    [1, 2, 3, 4],
  );
  assert.equal(events.length, 4);
});

test("bounded periods reject invalid and future timestamps", () => {
  const events = [
    event(1, "invalid"),
    event(2, "2026-07-30T00:00:00Z"),
    event(3, "2026-07-28T00:00:00Z"),
  ];
  const filtered = filterMoneyManagementAnalyticsEvents(
    events,
    MONEY_MANAGEMENT_ANALYTICS_PERIOD.SEVEN_DAYS,
    NOW,
  );
  assert.deepEqual(filtered.map(({ sequence }) => sequence), [3]);
});

test("history loader follows backend pagination and preserves real records", async () => {
  const calls = [];
  const pages = [
    {
      events: [event(3, "2026-07-29T00:00:00Z")],
      hasMore: true,
      nextCursor: "3",
    },
    {
      events: [event(2, "2026-07-28T00:00:00Z")],
      hasMore: false,
      nextCursor: null,
    },
  ];
  const loaded = await loadMoneyManagementAnalyticsHistory({
    client: async (query, options) => {
      calls.push({ query, options });
      return pages[calls.length - 1];
    },
    signal: "signal",
  });

  assert.deepEqual(loaded.map(({ sequence }) => sequence), [3, 2]);
  assert.deepEqual(calls, [
    {
      query: { limit: 500 },
      options: { signal: "signal" },
    },
    {
      query: { limit: 500, before: "3" },
      options: { signal: "signal" },
    },
  ]);
});

test("history loader fails closed on repeated or malformed cursors", async () => {
  let calls = 0;
  await assert.rejects(
    loadMoneyManagementAnalyticsHistory({
      client: async () => {
        calls += 1;
        return {
          events: [],
          hasMore: true,
          nextCursor: "1",
        };
      },
    }),
    /history cursor is invalid/u,
  );
  assert.equal(calls, 2);
});
