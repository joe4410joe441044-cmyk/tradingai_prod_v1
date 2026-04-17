const API_BASE = process.env.REACT_APP_API_BASE || "";

export const API = {
  // --------------------------
  // Market Data
  // --------------------------
  price: () => `${API_BASE}/api/price`,
  balance: () => `${API_BASE}/api/balance`,
  positions: () => `${API_BASE}/api/positions`,
  trades: () => `${API_BASE}/api/trades`,

  // --------------------------
  // AI / Analysis
  // --------------------------
  scores: (symbol = "BTCUSDT") =>
    `${API_BASE}/api/ai/scores?symbol=${symbol}`,

  // --------------------------
  // System Logs
  // --------------------------
  logs: () => `${API_BASE}/api/logs`,

  // --------------------------
  // Bot Control繝ｻ蛹ｻ・・ｸｺ阮吮ｲ鬩･蟠趣ｽｦ繝ｻ・ｼ繝ｻ
  // --------------------------
  botStatus: () => `${API_BASE}/api/bot/status`,
  botStart: () => `${API_BASE}/api/bot/start`,
  botStop: () => `${API_BASE}/api/bot/stop`,
};
