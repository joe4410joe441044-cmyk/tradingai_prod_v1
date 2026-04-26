const BASE_URL = "/api";

/**
 * ⚠️ LEGACY API LAYER (休止中)
 * 
 * このファイルは旧互換のため残されていますが、
 * 新規コードでは使用禁止です。
 * 
 * 👉 代替: fetch(API.xxx()) を使用してください
 * 👉 この関数群は将来的に削除されます
 */

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  if (!res.ok) {
    throw new Error(`HTTP error: ${res.status}`);
  }

  return res.json();
}

// --------------------------
// ❌ 休止中API（使用禁止）
// --------------------------

export const getPrice = () => {
  console.warn("[DEPRECATED] getPrice is disabled. Use fetch(API.price())");
  return Promise.reject("Deprecated API");
};

export const getBalance = () => {
  console.warn("[DEPRECATED] getBalance is disabled. Use fetch(API.balance())");
  return Promise.reject("Deprecated API");
};

export const getPositions = () => {
  console.warn("[DEPRECATED] getPositions is disabled. Use fetch(API.positions())");
  return Promise.reject("Deprecated API");
};

export const getLogs = () => {
  console.warn("[DEPRECATED] getLogs is disabled. Use fetch(API.logs())");
  return Promise.reject("Deprecated API");
};

export const getStatus = () => {
  console.warn("[DEPRECATED] getStatus is disabled. Use fetch(API.botStatus())");
  return Promise.reject("Deprecated API");
};

// --------------------------
// Bot Control（注意付き）
– -------------------------

export const startBot = () => {
  console.warn("[DEPRECATED] startBot - consider using fetch(API.botStart())");
  return request("/bot/start", { method: "POST" });
};

export const stopBot = () => {
  console.warn("[DEPRECATED] stopBot - consider using fetch(API.botStop())");
  return request("/bot/stop", { method: "POST" });
};

// --------------------------
// default export（非推奨）
– -------------------------

export default {
  getPrice,
  getBalance,
  getPositions,
  getLogs,
  getStatus,
  startBot,
  stopBot,
};