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

  loopStart: () =>
    join("/bot/loop/start"),

  loopStop: () =>
    join("/bot/loop/stop"),

  paperAccountCapital: () =>
    join("/bot/paper-account/capital"),

  // ==========================
  // SUMMARY
  // ==========================

  summary: () =>
    join("/bot/summary"),

  // ==========================
  // MONEY MANAGEMENT
  // ==========================

  moneyManagementStatus: () =>
    join("/money-management/status"),

  moneyManagementConfiguration: () =>
    join("/money-management/configuration"),

  moneyManagementRecovery: () =>
    join("/money-management/recovery"),

  moneyManagementPositionSizePreview: () =>
    join("/money-management/position-size/preview"),

  moneyManagementSimulation: () =>
    join("/money-management/simulation"),

  moneyManagementHistory: () =>
    join("/money-management/history"),

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

  (typeof window !== "undefined"
    ? `${
    window.location.protocol ===
    "https:"
      ? "wss"
      : "ws"
  }://${window.location.host}`
    : "ws://localhost");

// ==========================
// WEBSOCKET LAYER
// ==========================

export const WS = {

  price:
    `${WS_BASE}/ws/price`,

};
