// ==========================
// API BASE
// ==========================
const API_BASE =
  (import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");

// --------------------------
// safe join
// --------------------------
const join = (path) => {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${cleanPath}`;
};

// ==========================
// API Layer（🔥 /api は付けない）
// ==========================
export const API = {
  // Market Data
  price: () => join("/price"),
  balance: () => join("/balance"),
  positions: () => join("/positions"),

  // AI
  scores: (symbol = "BTCUSDT") =>
    join(`/ai/scores?symbol=${encodeURIComponent(symbol)}`),

  // Logs
  logs: () => join("/logs"),

  // Bot Control
  botStatus: () => join("/bot/status"),
  botStart: () => join("/bot/start"),
  botStop: () => join("/bot/stop"),

  // Summary
  summary: () => join("/bot/summary"),

  // PnL
  pnl: () => join("/pnl"),
};

// ==========================
// WebSocket BASE（🔥完全安定版）
// ==========================
const WS_BASE =
  import.meta.env.VITE_WS_BASE ||
  (
    location.hostname === "localhost" || location.hostname === "127.0.0.1"
      // ローカル開発
      ? "ws://127.0.0.1:8000"
      // 本番（HTTP / HTTPS 両対応）
      : (location.protocol === "https:"
          ? `wss://${location.host}`
          : `ws://${location.host}:8000`)
  );

// ==========================
// WebSocket Layer
// ==========================
export const WS = {
  price: `${WS_BASE}/ws/price`,
};