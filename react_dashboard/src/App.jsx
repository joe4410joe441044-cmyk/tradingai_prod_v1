import { useEffect, useState } from "react";

import BalanceCard from "./components/BalanceCard";
import PnLCard from "./components/PnLCard";

const API_BASE = "http://35.194.104.74:8000";

export default function App() {
  const [status, setStatus] = useState("loading");
  const [price, setPrice] = useState(0);

  useEffect(() => {
    fetch(`${API_BASE}/api/bot/status`)
      .then(res => res.json())
      .then(data => setStatus(data?.status ?? "error"))
      .catch(() => setStatus("error"));

    fetch(`${API_BASE}/api/price`)
      .then(res => res.json())
      .then(data => setPrice(data?.price ?? 0))
      .catch(() => setPrice(0));
  }, []);

  const startBot = () => {
    fetch(`${API_BASE}/api/bot/start`, { method: "POST" })
      .then(() => setStatus("STARTING"))
      .catch(() => setStatus("error"));
  };

  const stopBot = () => {
    fetch(`${API_BASE}/api/bot/stop`, { method: "POST" })
      .then(() => setStatus("STOPPING"))
      .catch(() => setStatus("error"));
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1>TradingAI Dashboard</h1>

      {/* 🧠 基本情報 */}
      <p>Status: {status}</p>
      <p>Price: {price}</p>

      {/* 🚀 カード群（ここが重要） */}
      <div style={{ display: "grid", gap: "20px", marginTop: "20px" }}>
        <BalanceCard />
        <PnLCard />
      </div>

      {/* 操作ボタン */}
      <div style={{ marginTop: "20px" }}>
        <button onClick={startBot}>Start Bot</button>
        <button onClick={stopBot}>Stop Bot</button>
      </div>
    </div>
  );
}