import { useState } from "react";

import Dashboard from "./pages/Dashboard";

// =========================
// APP
// =========================

export default function App() {

  // =========================
  // CONFIG
  // =========================

  const [config, setConfig] = useState({
    symbol: "BTCUSDT",
    risk_percent: 1,
    sl_percent: 1,
    leverage: 10,
    tp_percent: 2,
    mode: "paper",
  });

  // =========================
  // BOT DATA
  // =========================

  const [botData, setBotData] = useState({
    price: 0,
    pnl: 0,
    balance: 1000,
    equity: 1000,
    position: "NONE",
    entryPrice: null,
    botStatus: "STOPPED",
  });

  // =========================
  // START
  // =========================

  const handleStart = async () => {

    const finalConfig = {
      ...config,

      risk_percent: Number(
        config.risk_percent
      ),

      sl_percent: Number(
        config.sl_percent
      ),

      leverage: Number(
        config.leverage
      ),

      tp_percent: Number(
        config.tp_percent
      ),
    };

    console.log(
      "🔥 START REQUEST:",
      finalConfig
    );

    try {

      const response = await fetch(
        "/api/bot/start",
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          body: JSON.stringify(
            finalConfig
          ),
        }
      );

      const data =
        await response.json();

      console.log(
        "🟢 START RESPONSE:",
        data
      );

    } catch (err) {

      console.error(
        "❌ START ERROR:",
        err
      );
    }
  };

  // =========================
  // STOP
  // =========================

  const handleStop = async () => {

    console.log(
      "🛑 STOP REQUEST"
    );

    try {

      const response = await fetch(
        "/api/bot/stop",
        {
          method: "POST",
        }
      );

      const data =
        await response.json();

      console.log(
        "🛑 STOP RESPONSE:",
        data
      );

    } catch (err) {

      console.error(
        "❌ STOP ERROR:",
        err
      );
    }
  };

  // =========================
  // UI
  // =========================

  return (

    <Dashboard
      config={config}
      setConfig={setConfig}

      botData={botData}

      handleStart={handleStart}
      handleStop={handleStop}
    />

  );
}