import React, { useState, useEffect } from "react";
import useBotData from "./hooks/useBotData";
import TradeConfigPanel from "./components/control/TradeConfigPanel";
import StatusPanel from "./components/StatusPanel";
import TradeControl from "./components/TradeControl";

// 🔥 ファイル実行確認
console.log("🔥🔥🔥 APP ROOT FILE LOADED 🔥🔥🔥");
document.body.style.background = "#200";

function Card({ title, children }) {
  return (
    <div style={{
      background: "#111",
      borderRadius: "16px",
      padding: "16px",
      boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
      marginBottom: 16
    }}>
      <div style={{ fontSize: "12px", opacity: 0.6, marginBottom: "8px" }}>
        {title}
      </div>
      <div style={{ fontSize: "16px", fontWeight: "bold" }}>
        {children}
      </div>
    </div>
  );
}

function StatusBar({ status }) {
  return (
    <div style={{
      position: "fixed",
      bottom: 0,
      left: 0,
      width: "100%",
      background: "#111",
      color: "#0f0",
      padding: "8px",
      fontSize: "12px",
      borderTop: "1px solid #333"
    }}>
      <div>
        STATUS: {status === "RUNNING" ? "🟢 RUNNING" : "🔴 STOPPED"}
      </div>
    </div>
  );
}

export default function App() {

  const bot = useBotData();

  // 🔥 初期値OFF
  const [config, setConfig] = useState({
    symbol: "BTCUSDT",
    risk_percent: 1,
    sl_percent: 1,
    leverage: 10,
    tp_percent: 2,
    dry_run: false
  });

  const [mode, setMode] = useState("paper");

  useEffect(() => {
    console.log("📊 CONFIG STATE UPDATED:", config);
  }, [config]);

  const handleStart = async () => {

    console.log("🔥 CURRENT CONFIG:", config);

    const finalConfig = {
      symbol: config.symbol,
      risk_percent: Number(config.risk_percent),
      sl_percent: Number(config.sl_percent),
      leverage: Number(config.leverage),
      tp_percent: Number(config.tp_percent),
      mode: mode,

      // 🔥 念のため強制OFF
      dry_run: false
    };

    console.log("🚀 FINAL CONFIG:", finalConfig);

    if (!finalConfig.symbol) {
      alert("❌ SYMBOLなし");
      return;
    }

    if (bot.status === "RUNNING") {
      alert("すでに稼働中");
      return;
    }

    try {
      const res = await fetch("http://127.0.0.1:8001/api/bot/start", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(finalConfig)
      });

      console.log("📡 FETCH RESPONSE:", res);

    } catch (err) {
      console.error("❌ START ERROR:", err);
    }
  };

  const handleStop = async () => {
    console.log("🛑 STOP CLICKED");

    try {
      await fetch("http://127.0.0.1:8001/api/bot/stop", {
        method: "POST"
      });
    } catch (err) {
      console.error("❌ STOP ERROR:", err);
    }
  };

  return (
    <div style={{ padding: 20, color: "#fff", background: "#0b0b0b" }}>

      {/* 設定入力 */}
      <TradeConfigPanel
        onChange={(cfg) => {
          console.log("📥 CONFIG UPDATE FROM PANEL:", cfg);
          setConfig((prev) => ({
            ...prev,
            ...cfg
          }));
        }}
      />

      <Card title="Control">

        <button
          onClick={handleStart}
          disabled={bot.status === "RUNNING"}
        >
          ▶ START
        </button>

        <button onClick={handleStop}>
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

        {/* 🔥 ここが修正ポイント */}
        <TradeControl
          config={{ ...config, mode }}
          onChange={(newConfig) => {
            setConfig((prev) => ({
              ...prev,
              ...newConfig   // ← 上書きではなくマージ
            }));
          }}
        />

        <div style={{ marginTop: 10 }}>
          CONFIG SYMBOL: {config.symbol}
        </div>

        <div style={{ marginTop: 10 }}>
          BOT SYMBOL: {bot.symbol ?? "-"}
        </div>

        {bot.symbol && config.symbol !== bot.symbol && (
          <div style={{ color: "red", fontWeight: "bold", marginTop: 10 }}>
            ⚠️ SYMBOL MISMATCH
          </div>
        )}

      </Card>

      <StatusPanel
        balance={bot.balance}
        equity={bot.equity}
        pnl={bot.pnl}
        price={bot.price}
        botStatus={bot.status}
      />

      <StatusBar status={bot.status} />

    </div>
  );
}