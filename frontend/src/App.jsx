import React, { useState, useMemo } from "react";
import useBotData from "./hooks/useBotData";
import TradeConfigPanel from "./components/control/TradeConfigPanel";
import RiskPanel from "./components/RiskPanel";
import StatusPanel from "./components/StatusPanel";

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

function StatusBar({ status, logs }) {
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

      <div style={{ marginTop: 4, maxHeight: 60, overflowY: "auto" }}>
        {logs.slice(-5).map((log, i) => (
          <div key={i}>{log}</div>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const bot = useBotData();

  const [config, setConfig] = useState(null);
  const [logs, setLogs] = useState([]);

  const result = useMemo(() => {
    if (!config || !bot.balance || !bot.price) {
      return {
        positionSize: "-",
        qty: "-",
        riskAmount: "-",
        ddAfter: "-"
      };
    }

    const riskAmount = (bot.balance * (config.riskPercent || 0)) / 100;
    const positionSize = riskAmount * (config.leverage || 1);

    const qty = positionSize / bot.price;
    const ddAfter = (riskAmount / bot.balance) * 100;

    return {
      positionSize: positionSize.toFixed(2),
      qty: qty.toFixed(4),
      riskAmount: riskAmount.toFixed(2),
      ddAfter: ddAfter.toFixed(2)
    };

  }, [config, bot.balance, bot.price]);

  // =========================
  // 🔥 修正済み START
  // =========================
  const handleStart = async () => {
    try {
      if (!config) {
        alert("設定が未入力");
        setLogs(prev => [...prev, "⚠ 設定が未入力"]);
        return;
      }

      const payload = {
        symbol: config.symbol,
        risk_percent: config.riskPercent,
        sl_percent: config.slPercent,
        leverage: config.leverage
      };

      console.log("🚀 START PAYLOAD:", payload);

      setLogs(prev => [...prev, "▶ START送信"]);

      const res = await fetch("http://127.0.0.1:8001/api/bot/start", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      const json = await res.json();
      console.log("START RESULT:", json);

      setLogs(prev => [...prev, "🟢 Bot Started"]);

    } catch (e) {
      console.error("START ERROR", e);
      setLogs(prev => [...prev, "❌ START ERROR"]);
    }
  };

  const handleStop = async () => {
    try {
      await fetch("http://127.0.0.1:8001/api/bot/stop", {
        method: "POST"
      });

      setLogs(prev => [...prev, "🔴 Bot Stopped"]);

    } catch (e) {
      console.error("STOP ERROR", e);
      setLogs(prev => [...prev, "❌ STOP ERROR"]);
    }
  };

  return (
    <div style={{
      padding: 20,
      paddingBottom: 100,
      background: "#0b0b0b",
      minHeight: "100vh",
      color: "#fff",
      fontFamily: "Arial"
    }}>
      <h2 style={{ marginBottom: 20 }}>TradingAI</h2>

      <TradeConfigPanel onChange={setConfig} />

      <Card title="Risk Settings">
        <RiskPanel
          onChange={(riskConfig) => {
            setConfig(prev => ({
              ...prev,
              ...riskConfig
            }));
          }}
          result={result}
        />
      </Card>

      <Card title="Control">
        <button onClick={handleStart} disabled={!config} style={{ marginRight: 10 }}>
          ▶ START
        </button>

        <button onClick={handleStop}>
          ■ STOP
        </button>
      </Card>

      <StatusPanel
        balance={bot.balance}
        equity={bot.equity}
        pnl={bot.pnl}
        price={bot.price}
        currentDD={bot.risk?.current_dd}
        lossStreak={bot.risk?.current_loss_streak}
        killSwitch={bot.risk?.kill_switch}
        botStatus={bot.status}
      />

      <Card title="Log">
        {logs.slice(-10).map((log, i) => (
          <div key={i}>{log}</div>
        ))}
      </Card>

      <StatusBar status={bot.status} logs={logs} />
    </div>
  );
}