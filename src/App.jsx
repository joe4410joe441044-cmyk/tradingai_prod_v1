import { useEffect, useState } from "react";

import BalanceCard from "./components/BalanceCard";
import PnLCard from "./components/PnLCard";
import { API } from "./api";

export default function App() {
  const [status, setStatus] = useState("loading");
  const [price, setPrice] = useState(0);

  // --------------------------
  // 初期データ取得（統一API）
  // --------------------------
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statusRes, priceRes] = await Promise.all([
          fetch(API.botStatus()),
          fetch(API.price()),
        ]);

        const statusData = statusRes.ok ? await statusRes.json() : null;
        const priceData = priceRes.ok ? await priceRes.json() : null;

        setStatus(statusData?.status ?? "error");
        setPrice(priceData?.price ?? 0);

      } catch (err) {
        console.error(err);
        setStatus("error");
        setPrice(0);
      }
    };

    fetchData();
  }, []);

  // --------------------------
  // BOT START
  // --------------------------
  const startBot = async () => {
    try {
      const res = await fetch(API.botStart(), { method: "POST" });

      if (!res.ok) throw new Error("Start failed");

      setStatus("STARTING");
    } catch (err) {
      console.error(err);
      setStatus("error");
    }
  };

  // --------------------------
  // BOT STOP
  // --------------------------
  const stopBot = async () => {
    try {
      const res = await fetch(API.botStop(), { method: "POST" });

      if (!res.ok) throw new Error("Stop failed");

      setStatus("STOPPING");
    } catch (err) {
      console.error(err);
      setStatus("error");
    }
  };

  // --------------------------
  return (
    <div style={{ padding: "20px" }}>
      <h1>TradingAI Dashboard</h1>

      {/* 基本情報 */}
      <p>Status: {status}</p>
      <p>Price: {price}</p>

      {/* カード群 */}
      <div style={{ display: "grid", gap: "20px", marginTop: "20px" }}>
        <BalanceCard />
        <PnLCard />
      </div>

      {/* ボタン */}
      <div style={{ marginTop: "20px" }}>
        <button onClick={startBot}>Start Bot</button>
        <button onClick={stopBot}>Stop Bot</button>
      </div>
    </div>
  );
}