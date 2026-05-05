import React, { useState, useEffect } from "react";
import useBotData from "./hooks/useBotData";
import TradeConfigPanel from "./components/control/TradeConfigPanel";
import StatusPanel from "./components/StatusPanel";
import TradeControl from "./components/TradeControl";
import StrategyMonitor from "./components/monitor/StrategyMonitor";

// 🔥 確認
console.log("🔥 APP DASHBOARD LOADED");

// =========================
// UIパーツ
// =========================
const Box = ({ title, children }) => (
  <div style={{
    border: "1px solid #333",
    borderRadius: 10,
    padding: 12,
    background: "#111",
    marginBottom: 16
  }}>
    <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 8 }}>
      {title}
    </div>
    {children}
  </div>
);

const StatusBar = ({ status }) => (
  <div style={{
    position: "fixed",
    bottom: 0,
    left: 0,
    width: "100%",
    background: "#111",
    padding: 8,
    fontSize: 12,
    borderTop: "1px solid #333"
  }}>
    STATUS: {status === "RUNNING" ? "🟢 RUNNING" : "🔴 STOPPED"}
  </div>
);

// =========================
// APP
// =========================
export default function App() {

  const bot = useBotData();

  const [config, setConfig] = useState({
    symbol: "BTCUSDT",
    risk_percent: 1,
    sl_percent: 1,
    leverage: 10,
    tp_percent: 2,
    dry_run: false
  });

  const [mode, setMode] = useState("paper");

  // =========================
  // START
  // =========================
  const handleStart = async () => {

    const finalConfig = {
      ...config,
      mode,
      risk_percent: Number(config.risk_percent),
      sl_percent: Number(config.sl_percent),
      leverage: Number(config.leverage),
      tp_percent: Number(config.tp_percent)
    };

    try {
      await fetch("/api/bot/start", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(finalConfig)
      });
    } catch (err) {
      console.error("❌ START ERROR:", err);
    }
  };

  // =========================
  // STOP
  // =========================
  const handleStop = async () => {
    try {
      await fetch("/api/bot/stop", { method: "POST" });
    } catch (err) {
      console.error("❌ STOP ERROR:", err);
    }
  };

  // =========================
  // UI
  // =========================
  return (
    <div style={{ padding: 20, background: "#000", color: "#fff" }}>

      <h1 style={{ marginBottom: 20 }}>🧠 TradingAI Dashboard</h1>

      {/* MAIN */}
      <div style={{ display: "flex", gap: 20 }}>

        {/* LEFT（CONFIG） */}
        <div style={{ flex: 1 }}>

          <Box title="🟢 CONFIG">

            <TradeConfigPanel
              onChange={(cfg) => {
                setConfig((prev) => ({ ...prev, ...cfg }));
              }}
            />

          </Box>

        </div>

        {/* RIGHT（MONITOR） */}
        <div style={{ flex: 1 }}>

          <Box title="🔵 Strategy Monitor">
            <StrategyMonitor />
          </Box>

          <Box title="Status">
            <StatusPanel
              balance={bot.balance}
              equity={bot.equity}
              pnl={bot.pnl}
              price={bot.price}
              botStatus={bot.status}
            />
          </Box>

        </div>

      </div>

      {/* BOTTOM */}
      <div style={{ display: "flex", gap: 20, marginTop: 20 }}>

        {/* EXECUTION */}
        <div style={{ flex: 1 }}>

          <Box title="🔘 Execution">

            <button
              onClick={handleStart}
              disabled={bot.status === "RUNNING"}
            >
              ▶ START
            </button>

            <button
              onClick={handleStop}
              style={{ marginLeft: 10 }}
            >
              ■ STOP
            </button>

            <div style={{ marginTop: 10 }}>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value)}
                disabled={bot.status === "RUNNING"}
              >
                <option value="paper">🟡 PAPER</option>
                <option value="live">🔴 LIVE</option>
              </select>
            </div>

            <div style={{ marginTop: 10 }}>
              MODE: {mode === "paper" ? "🟡 PAPER" : "🔴 LIVE"}
            </div>

            <TradeControl
              config={{ ...config, mode }}
              onChange={(newConfig) => {
                setConfig((prev) => ({ ...prev, ...newConfig }));
              }}
            />

            <div style={{ marginTop: 10 }}>
              CONFIG SYMBOL: {config.symbol}
            </div>

            <div>
              BOT SYMBOL: {bot.symbol ?? "-"}
            </div>

          </Box>

        </div>

      </div>

      <StatusBar status={bot.status} />

    </div>
  );
}