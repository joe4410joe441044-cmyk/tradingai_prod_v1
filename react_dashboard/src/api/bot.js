const API_BASE = "http://34.85.66.137:8000";

// --------------------
// BOT STATUS
// --------------------
export async function getBotStatus() {
  const res = await fetch(`${API_BASE}/bot_status`);
  if (!res.ok) throw new Error("bot_status error");
  return res.json();
}

// --------------------
// BALANCE（新規追加）
// --------------------
export async function getBalance() {
  const res = await fetch(`${API_BASE}/balance`);

  if (!res.ok) {
    throw new Error("balance error");
  }

  const data = await res.json();

  // 安全化
  return data?.balance ?? data ?? 0;
}


// --------------------
// POSITIONS
// --------------------
export async function getPositions() {
  const res = await fetch(`${API_BASE}/positions`);
  if (!res.ok) throw new Error("positions error");
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

// --------------------
// LOGS（text → array変換まで吸収）
// --------------------
export async function getLogs() {
  const res = await fetch(`${API_BASE}/logs`);
  const text = await res.text();
  return text.split("\n").filter(Boolean);
}

// --------------------
// START BOT
// --------------------
export async function startBot() {
  const res = await fetch(`${API_BASE}/start`);
  return res.json().catch(() => ({}));
}

// --------------------
// STOP BOT
// --------------------
export async function stopBot() {
  const res = await fetch(`${API_BASE}/stop`);
  return res.json().catch(() => ({}));
}