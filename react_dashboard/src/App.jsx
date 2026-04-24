import React, { useEffect, useState, useMemo } from "react";

import useBotData from "./hooks/useBotData";
import useEventWS from "./hooks/useEventWS";

import AssetDashboard from "./components/dashboard/AssetDashboard";
import RightPanel from "./components/monitor/RightPanel";
import BotControl from "./components/control/BotControl";

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
      <div
        style={{
          fontSize: "12px",
          opacity: 0.6,
          marginBottom: "8px",
        }}
      >
        {title}
      </div>

      <div
        style={{
          fontSize: "16px",
          fontWeight: "bold",
        }}
      >
        {children}
      </div>
    </div>
  );
}

// =========================
// 取引所セレクタ（追加）
// =========================
function ExchangeSelector({ selected, onChange }) {
  const exchanges = ["bybit", "binance", "kucoin", "okx"];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <select
        value={selected}
        onChange={(e) => onChange(e.target.value)}
        style={{
          padding: "8px",
          borderRadius: "8px",
          background: "#0b0b0b",
          color: "#fff",
          border: "1px solid #333",
        }}
      >
        {exchanges.map((ex) => (
          <option key={ex} value={ex}>
            {ex.toUpperCase()}
          </option>
        ))}
      </select>

      <div style={{ fontSize: "12px", opacity: 0.6 }}>
        Active: {selected.toUpperCase()}
      </div>
    </div>
  );
}

// =========================
// MAIN APP
// =========================
export default function App() {
  const bot = useBotData(2000);

  // =========================
  // 取引所STATE（追加）
  // =========================
  const [exchange, setExchange] = useState("bybit");

  // =========================
  // WS EVENTS（再接続付き）
  // =========================
  const events = useEventWS("ws://localhost:8000/ws/events");

  // =========================
  // RISK STATE（安定化版）
  // =========================
  const [risk, setRisk] = useState(null);

  useEffect(() => {
    let alive = true;

    const fetchRisk = async () => {
      try {
        const res = await fetch("http://localhost:8000/api/risk/status");
        const data = await res.json();

        if (alive) setRisk(data);
      } catch (e) {
        console.error("[RISK FETCH ERROR]", e);
      }
    };

    fetchRisk();
    const interval = setInterval(fetchRisk, 2000);

    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, []);

  // =========================
  // EVENTS MEMO（軽量化）
  // =========================
  const safeEvents = useMemo(() => {
    if (!Array.isArray(events)) return [];
    return events.slice(0, 100);
  }, [events]);

  // =========================
  // 取引所変更ハンドラ（追加）
  // =========================
  const handleExchangeChange = async (value) => {
    setExchange(value);

    try {
      await fetch("http://localhost:8000/api/set-exchange", {
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

      {/* =========================
          STATUS
      ========================= */}
      <div style={{ marginBottom: 16 }}>
        <Card title="Status">
          {bot.status} {bot.connected ? "🟢" : "🔴"}
        </Card>
      </div>

      {/* =========================
          BOT CONTROL
      ========================= */}
      <div style={{ marginBottom: 16 }}>
        <Card title="Bot Control">
          <BotControl onStart={bot.start} onStop={bot.stop} />
        </Card>
      </div>

      {/* =========================
          🔥 取引所セレクタ（追加）
      ========================= */}
      <div style={{ marginBottom: 16 }}>
        <Card title="Trading Exchange">
          <ExchangeSelector
            selected={exchange}
            onChange={handleExchangeChange}
          />
        </Card>
      </div>

      {/* =========================
          MAIN GRID
      ========================= */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: "16px",
        }}
      >
        {/* LEFT SIDE */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "16px",
          }}
        >
          <Card title="Dashboard">
            <AssetDashboard
              price={bot.price}
              balance={bot.balance}
              pnl={bot.pnl}
              logs={bot.logs}
              positions={bot.positions}
            />
          </Card>

          {/* =========================
              LIVE EVENTS
          ========================= */}
          <Card title="Live Events">
            <div
              style={{
                maxHeight: 260,
                overflowY: "auto",
                fontSize: "12px",
                opacity: 0.9,
              }}
            >
              {safeEvents.length === 0 && (
                <div style={{ opacity: 0.5 }}>No events</div>
              )}

              {safeEvents.map((e, i) => (
                <div
                  key={i}
                  style={{
                    padding: "6px 0",
                    borderBottom: "1px solid #222",
                  }}
                >
                  <b style={{ color: "#7dd3fc" }}>
                    {e?.type ?? "UNKNOWN"}
                  </b>{" "}
                  <span style={{ opacity: 0.7 }}>
                    {JSON.stringify(e?.data ?? {})}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* RIGHT SIDE */}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Card title="System Info">
            <RightPanel status={bot.status} connected={bot.connected} />
          </Card>

          {/* =========================
              RISK PANEL
          ========================= */}
          <RiskPanel risk={risk} />
        </div>
      </div>
    </div>
  );
}

// =========================
// RISK PANEL（最適化版）
// =========================
function RiskPanel({ risk }) {
  return (
    <Card title="Risk Engine">
      {!risk ? (
        <div style={{ opacity: 0.5 }}>Loading...</div>
      ) : (
        <div style={{ fontSize: "12px", lineHeight: "1.6" }}>
          <div>Daily PnL: {risk?.daily_pnl ?? 0}</div>
          <div>Positions: {risk?.positions ?? 0}</div>
          <div>Loss Streak: {risk?.consecutive_losses ?? 0}</div>

          <div style={{ marginTop: 8 }}>
            Status:{" "}
            <b
              style={{
                color: risk?.trading_disabled ? "red" : "lime",
              }}
            >
              {risk?.trading_disabled ? "DISABLED" : "ACTIVE"}
            </b>
          </div>
        </div>
      )}
    </Card>
  );
}