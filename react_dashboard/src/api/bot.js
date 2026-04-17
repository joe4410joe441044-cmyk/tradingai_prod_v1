// src/api/bot.js

const API_BASE = process.env.REACT_APP_API_BASE || "";

export const getAssetSummary = async () => {
  const res = await fetch(`${API_BASE}/api/bot/summary`);

  if (!res.ok) {
    throw new Error("Failed to fetch asset summary");
  }

  return res.json();
};