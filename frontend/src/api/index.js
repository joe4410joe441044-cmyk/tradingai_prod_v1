// ==========================
// API BASE
// ==========================

const API_ENV = import.meta.env || {};

const API_BASE =
  (
    API_ENV.VITE_API_BASE ||
    "/api"
  ).replace(/\/$/, "");

// --------------------------
// SAFE JOIN
// --------------------------

const join = (path) => {

  const cleanPath =
    path.startsWith("/")
      ? path
      : `/${path}`;

  return `${API_BASE}${cleanPath}`;

};

// ==========================
// API LAYER
// ==========================

export const API = {

  // ==========================
  // MARKET DATA
  // ==========================

  price: () =>
    join("/price"),

  balance: () =>
    join("/balance"),

  positions: () =>
    join("/positions"),

  // ==========================
  // AI
  // ==========================

  scores: (
    symbol = "BTCUSDT"
  ) =>

    join(
      `/ai/scores?symbol=${encodeURIComponent(
        symbol
      )}`
    ),

  aiAdvisorRuntime: () =>
    join("/ai-advisor/conversation/runtime"),

  // ==========================
  // LOGS
  // ==========================

  logs: () =>
    join("/logs"),

  // ==========================
  // BOT CONTROL
  // ==========================

  botStatus: () =>
    join("/bot/status"),

  botStart: () =>
    join("/bot/start"),

  botStop: () =>
    join("/bot/stop"),

  // ==========================
  // SUMMARY
  // ==========================

  summary: () =>
    join("/bot/summary"),

  // ==========================
  // PNL
  // ==========================

  pnl: () =>
    join("/pnl"),

};

// ==========================
// WEBSOCKET BASE
// ==========================

const WS_BASE =

  API_ENV.VITE_WS_BASE ||

  `${
    window.location.protocol ===
    "https:"
      ? "wss"
      : "ws"
  }://${window.location.host}`;

// ==========================
// WEBSOCKET LAYER
// ==========================

export const WS = {

  price:
    `${WS_BASE}/ws/price`,

};
