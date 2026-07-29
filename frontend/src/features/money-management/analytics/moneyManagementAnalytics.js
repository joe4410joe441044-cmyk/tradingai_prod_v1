const HISTORY_PAGE_LIMIT = 500;
const MAX_HISTORY_PAGES = 10;

export const MONEY_MANAGEMENT_ANALYTICS_PERIOD = Object.freeze({
  SEVEN_DAYS: "7D",
  THIRTY_DAYS: "30D",
  ALL: "ALL",
});

const PERIOD_DAYS = Object.freeze({
  [MONEY_MANAGEMENT_ANALYTICS_PERIOD.SEVEN_DAYS]: 7,
  [MONEY_MANAGEMENT_ANALYTICS_PERIOD.THIRTY_DAYS]: 30,
});

export async function loadMoneyManagementAnalyticsHistory({
  client,
  signal,
} = {}) {
  if (typeof client !== "function") {
    throw new TypeError("history client is required");
  }
  const events = [];
  const cursors = new Set();
  let before = null;

  for (let page = 0; page < MAX_HISTORY_PAGES; page += 1) {
    const response = await client(
      {
        limit: HISTORY_PAGE_LIMIT,
        ...(before === null ? {} : { before }),
      },
      { signal },
    );
    if (!response || !Array.isArray(response.events)) {
      throw new TypeError("history response is invalid");
    }
    events.push(...response.events);
    if (response.hasMore !== true) return events;
    const next = response.nextCursor;
    if (
      typeof next !== "string" ||
      !/^[1-9][0-9]*$/u.test(next) ||
      cursors.has(next)
    ) {
      throw new TypeError("history cursor is invalid");
    }
    cursors.add(next);
    before = next;
  }
  throw new TypeError("history page limit exceeded");
}

export function filterMoneyManagementAnalyticsEvents(
  events,
  period,
  now = Date.now(),
) {
  if (!Array.isArray(events)) {
    throw new TypeError("analytics events must be an array");
  }
  if (!Object.values(MONEY_MANAGEMENT_ANALYTICS_PERIOD).includes(period)) {
    throw new TypeError("analytics period is invalid");
  }
  if (!Number.isFinite(now)) {
    throw new TypeError("analytics clock is invalid");
  }
  if (period === MONEY_MANAGEMENT_ANALYTICS_PERIOD.ALL) {
    return [...events];
  }
  const cutoff = now - PERIOD_DAYS[period] * 24 * 60 * 60 * 1000;
  return events.filter((event) => {
    const timestamp = Date.parse(event?.timestamp);
    return Number.isFinite(timestamp) && timestamp >= cutoff && timestamp <= now;
  });
}
