import React, { useState } from "react";
import useBotData from "./hooks/useBotData";

import TradeConfigPanel from "./components/control/TradeConfigPanel";
import StatusPanel from "./components/StatusPanel";
import TradeControl from "./components/TradeControl";
import StrategyMonitor from "./components/monitor/StrategyMonitor";

// 🔥 追加
import ResultPanel from "./components/ResultPanel";
import SignalLog from "./components/SignalLog";
import TradeLog from "./components/TradeLog";

console.log("🔥 APP DASHBOARD LOADED");

// =========================
// UIパーツ
// =========================
const Box = ({ title, children }) => (
  <div style={{
    border: "1px solid #333",
    borderRadius: 10,
    padding: 16,
    background: "#111",
    marginBottom: 16
  }}>
    <div style={{ fontSize: 13, opacity: 0.7, marginBottom: 10 }}>
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

  const [mode, setMode] = useState("safe");

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
        headers: { "Content-Type": "application/json" },
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

      {/* HEADER */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        marginBottom: 20,
        fontWeight: "bold"
      }}>
        <div>CONFIG SYMBOL: {config.symbol}</div>
        <div>BOT SYMBOL: {bot.symbol ?? "-"}</div>
        <div>
          STATUS: {bot.status === "RUNNING" ? "🟢 RUNNING" : "🔴 STOPPED"}
        </div>
      </div>

      <h1 style={{ marginBottom: 20 }}>🧠 TradingAI Dashboard</h1>

      {/* MAIN */}
      <div style={{ display: "flex", gap: 20 }}>

        {/* LEFT */}
        <div style={{ flex: 1 }}>

          <Box title="🟢 CONFIG">
            <TradeConfigPanel
              onChange={(cfg) => {
                setConfig((prev) => ({ ...prev, ...cfg }));
              }}
            />
          </Box>

          <Box title="🧠 Strategy">
            <TradeControl
              config={{ ...config, mode }}
              onChange={(newConfig) => {
                setConfig((prev) => ({ ...prev, ...newConfig }));
              }}
            />
          </Box>

        </div>

        {/* RIGHT */}
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

              currentDD={bot.drawdown}
              lossStreak={bot.loss_streak}
              killSwitch={bot.kill_switch}
              botStatus={bot.status}

              position={bot.position}
              entryPrice={bot.entry_price}
              lastSignal={bot.last_signal}
              lastBlock={bot.last_block}
              engineState={bot.engine_state}
              connection={bot.connection}
            />
          </Box>

          {/* 🔥 Result追加 */}
          <Box title="📊 Result">
            <ResultPanel
              price={bot.price}
              balance={bot.balance}
              risk_percent={config.risk_percent}
              sl_percent={config.sl_percent}
              tp_percent={config.tp_percent}
            />
          </Box>

        </div>

      </div>

      {/* EXECUTION */}
      <div style={{ marginTop: 20 }}>

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

          <div style={{ marginTop: 12 }}>
            <div>MODE:</div>

            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              disabled={bot.status === "RUNNING"}
            >
              <option value="safe">🟢 SAFE</option>
              <option value="normal">🟡 NORMAL</option>
              <option value="aggressive">🔴 AGGRESSIVE</option>
            </select>
          </div>

          <div style={{ marginTop: 8 }}>
            CURRENT MODE: {
              mode === "safe" ? "🟢 SAFE" :
              mode === "normal" ? "🟡 NORMAL" :
              "🔴 AGGRESSIVE"
            }
          </div>

          <div style={{ marginTop: 12 }}>
            <button
              onClick={() =>
                setConfig((prev) => ({
                  ...prev,
                  dry_run: !prev.dry_run
                }))
              }
            >
              TOGGLE DRY RUN
            </button>
          </div>

          <div style={{ marginTop: 8 }}>
            DRY RUN: {config.dry_run ? "🟡 ON (PAPER)" : "🔴 OFF (REAL)"}
          </div>

          <div style={{ marginTop: 12 }}>
            STATUS: {
              bot.status === "RUNNING"
                ? "🟢 RUNNING"
                : "🔴 STOPPED"
            }
          </div>

        </Box>

      </div>

      {/* 🔥 Logs追加 */}
      <div style={{ display: "flex", gap: 20, marginTop: 20 }}>

        <div style={{ flex: 1 }}>
          <SignalLog logs={bot.signal_logs || []} />
        </div>

        <div style={{ flex: 1 }}>
          <TradeLog logs={bot.trade_logs || []} />
        </div>

      </div>

      <StatusBar status={bot.status} />

    </div>
  );
}