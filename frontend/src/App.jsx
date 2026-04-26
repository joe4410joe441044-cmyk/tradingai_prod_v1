import React, { useState, useMemo, useCallback } from "react";

// ✅ ローカル参照
import useBotData from "./hooks/useBotData";
import useEventWS from "./hooks/useEventWS";

import RiskPanel from "./components/monitor/RiskPanel";
import AssetDashboard from "./components/dashboard/AssetDashboard";
import RightPanel from "./components/monitor/RightPanel";
import BotControl from "./components/control/BotControl";
import AITimeline from "./components/AITimeline";

// =========================
// 共通カード
// =========================
function Card({ title, children, style = {} }) {
  return (
    <div
      style={{
        background: "#111",
        borderRadius: "16px",
        padding: "16px",
        boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
        ...style,
      }}
    >
      <div style={{ fontSize: "12px", opacity: 0.6, marginBottom: "8px" }}>
        {title}
      </div>
      <div style={{ fontSize: "16px", fontWeight: "bold" }}>
        {children}
      </div>
    </div>
  );
}

// =========================
// MAIN APP
// =========================
export default function App() {
  const bot = useBotData();

  const [exchange, setExchange] = useState("bybit");

  // WS
  const handleWS = useCallback((msg) => {
    // console.log("WS EVENT:", msg);
  }, []);

  const events = useEventWS(handleWS);

  // 安全イベント
  const safeEvents = useMemo(() => {
    if (!Array.isArray(events)) return [];
    return events.slice(0, 100);
  }, [events]);

  // Exchange切り替え
  const handleExchangeChange = async (value) => {
    setExchange(value);

    try {
      await fetch("http://127.0.0.1:8000/api/set-exchange", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ exchange: value }),
      });
    } catch (e) {
      console.error("[EXCHANGE SWITCH ERROR]", e);
    }
  };

  // AIイベント抽出
  const aiEvents = useMemo(() => {
    return safeEvents
      .filter((e) =>
        ["ENTRY", "EXIT", "ALERT"].includes(e?.type)
      )
      .map((e) => e.data);
  }, [safeEvents]);

  return (
    <div
      style={{
        padding: 16,
        background: "#0b0b0b",
        minHeight: "100vh",
        color: "#fff",
      }}
    >
      <h2 style={{ marginBottom: 16 }}>TradingAI Dashboard</h2>

      {/* STATUS */}
      <Card title="Status">
        {bot.status} {bot.connection === "ONLINE" ? "🟢" : "🔴"}
      </Card>

      {/* BOT CONTROL */}
      <Card title="Bot Control">
        <BotControl />
      </Card>

      {/* EXCHANGE */}
      <Card title="Trading Exchange">
        <select
          value={exchange}
          onChange={(e) => handleExchangeChange(e.target.value)}
        >
          <option value="bybit">BYBIT</option>
          <option value="binance">BINANCE</option>
          <option value="kucoin">KUCOIN</option>
          <option value="okx">OKX</option>
        </select>
      </Card>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: "16px",
        }}
      >
        {/* LEFT */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <Card title="Dashboard">
            <AssetDashboard
              price={bot.price}
              balance={bot.balance}
              pnl={bot.pnl}
              logs={bot.logs}
              positions={bot.positions}
            />
          </Card>

          <Card title="AI Timeline">
            <AITimeline events={bot.aiEvents || []} />
          </Card>

          <Card title="Raw Events">
            {safeEvents.map((e, i) => (
              <div key={i}>
                {e.type} - {JSON.stringify(e.data)}
              </div>
            ))}
          </Card>
        </div>

        {/* RIGHT */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <Card title="System Info">
            <RightPanel
              status={bot.status}
              connected={bot.connection === "ONLINE"}
            />
          </Card>

          {/* ★ 追加：Riskパネル */}
          <Card title="Risk Control">
            <RiskPanel risk={bot.risk} />
          </Card>
        </div>
      </div>
    </div>
  );
}