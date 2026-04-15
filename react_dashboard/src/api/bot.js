const API_BASE = "http://35.194.104.74:8000";

// --------------------
// BOT STATUS
// --------------------
export async function getBotStatus() {
  const res = await fetch(`${API_BASE}/bot_status`);
  if (!res.ok) throw new Error("bot_status error");
  return res.json();
}

// --------------------
// BALANCE�E�新規追加�E�E
// --------------------
export async function getBalance() {
  const res = await fetch(`${API_BASE}/balance`);

  if (!res.ok) {
    throw new Error("balance error");
  }

  const data = await res.json();

  // 安�E匁E
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
// LOGS�E�Eext ↁEarray変換まで吸収！E
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
