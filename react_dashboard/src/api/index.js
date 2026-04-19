const API_BASE = import.meta.env.VITE_API_BASE;

if (!API_BASE) {
  throw new Error("VITE_API_BASE is not defined");
}

// --------------------------
// safety normalize
// --------------------------
const normalize = (path) =>
  path.startsWith("/") ? path : `/${path}`;

// /api/api 防止
const safePath = (path) =>
  path.replace(/^\/api\/api/, "/api");

// --------------------------
// join
// --------------------------
const join = (path) =>
  `${API_BASE}${safePath(normalize(path))}`;

// --------------------------
// API Layer
// --------------------------
export const API = {
  // Market
  price: () => join("/api/price"),
  balance: () => join("/api/balance"),
  positions: () => join("/api/positions"),
  trades: () => join("/api/trades"),

  // AI
  scores: (symbol = "BTCUSDT") =>
    join(`/api/ai/scores?symbol=${symbol}`),

  // logs
  logs: () => join("/api/logs"),

  // bot
  botStatus: () => join("/api/bot/status"),
  botStart: () => join("/api/bot/start"),
  botStop: () => join("/api/bot/stop"),

  // summary
  summary: () => join("/api/bot/summary"),
};