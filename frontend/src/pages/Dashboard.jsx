import { useEffect, useState } from "react";
import Header from "../components/header";

// =========================
// CONFIG
// =========================
import TradeSettings from "../components/TradeSettings";
import ExecutionSettings from "../components/config/ExecutionSettings";
import RiskSettings from "../components/config/RiskSettings";
import EmergencySettings from "../components/config/EmergencySettings";
import PositionSettings from "../components/config/PositionSettings";
import AdvancedSettings from "../components/config/AdvancedSettings";

// =========================
// MONITOR
// =========================
import StrategyMonitor from "../components/monitor/StrategyMonitor";
import StatusPanel from "../components/StatusPanel";
import ResultPanel from "../components/ResultPanel";

// =========================
// EXECUTION
// =========================
import ExecutionPanel from "../components/ExecutionPanel";

// =========================
// LOGS
// =========================
import SignalLog from "../components/SignalLog";
import TradeLog from "../components/TradeLog";

// =========================
// CSS
// =========================
import "../styles/dashboard.css";

export default function Dashboard() {

  // =========================
  // LIVE STATE
  // =========================

  const [balance, setBalance] = useState(1000);

  const [equity, setEquity] = useState(1000);

  const [pnl, setPnl] = useState(0);

  const [price, setPrice] = useState(95000);

  const [position, setPosition] = useState("NONE");

  const [entryPrice, setEntryPrice] = useState(null);

  const [botStatus, setBotStatus] = useState("STOPPED");

  const [connection, setConnection] = useState("OFFLINE");

  // =========================
  // WEBSOCKET
  // =========================

  useEffect(() => {

    const ws = new WebSocket(
      "ws://localhost:8001/ws"
    );

    // =========================
    // OPEN
    // =========================

    ws.onopen = () => {

      console.log("✅ WS CONNECTED");

      setConnection("ONLINE");

    };

    // =========================
    // MESSAGE
    // =========================

    ws.onmessage = (event) => {

      console.log(
        "📩 WS MESSAGE:",
        event.data
      );

      try {

        const data = JSON.parse(
          event.data
        );

        // =========================
        // LIVE DATA UPDATE
        // =========================

        if (data.price !== undefined) {
          setPrice(data.price);
        }

        if (data.pnl !== undefined) {
          setPnl(data.pnl);
        }

        if (data.balance !== undefined) {
          setBalance(data.balance);
        }

        if (data.equity !== undefined) {
          setEquity(data.equity);
        }

        if (data.position !== undefined) {
          setPosition(data.position);
        }

        if (data.entryPrice !== undefined) {
          setEntryPrice(data.entryPrice);
        }

        if (data.botStatus !== undefined) {
          setBotStatus(data.botStatus);
        }

      } catch (err) {

        console.log(
          "❌ JSON PARSE ERROR:",
          err
        );

      }

    };

    // =========================
    // ERROR
    // =========================

    ws.onerror = (error) => {

      console.log(
        "❌ WS ERROR:",
        error
      );

    };

    // =========================
    // CLOSE
    // =========================

    ws.onclose = () => {

      console.log("🔌 WS CLOSED");

      setConnection("OFFLINE");

    };

    // =========================
    // CLEANUP
    // =========================

    return () => {

      ws.close();

    };

  }, []);

  return (
    <div className="dashboard">

      {/* ========================= */}
      {/* HEADER */}
      {/* ========================= */}
      <Header />

      {/* ========================= */}
      {/* 3 COLUMN LAYOUT */}
      {/* ========================= */}
      <div className="dashboard-content">

        {/* ========================= */}
        {/* LEFT COLUMN */}
        {/* ========================= */}
        <div className="left-column">

          {/* STATUS */}
          <div className="panel-card">

            <h2>🔵 STATUS</h2>

            <StatusPanel
              balance={balance}
              equity={equity}
              pnl={pnl}
              price={price}
              position={position}
              entryPrice={entryPrice}
              botStatus={botStatus}
              connection={connection}
            />

          </div>

          {/* STRATEGY MONITOR */}
          <div className="panel-card">

            <h2>📊 STRATEGY MONITOR</h2>

            <StrategyMonitor />

          </div>

          {/* RESULT */}
          <div className="panel-card">

            <h2>📈 RESULT</h2>

            <ResultPanel
              price={price}
              balance={balance}
            />

          </div>

        </div>

        {/* ========================= */}
        {/* CENTER COLUMN */}
        {/* ========================= */}
        <div className="center-column">

          {/* EXECUTION */}
          <div className="panel-card execution-wrapper">

            <h2>🔘 EXECUTION</h2>

            <ExecutionPanel />

          </div>

          {/* LOGS */}
          <div className="panel-card logs-wrapper">

            <h2>📊 LOGS</h2>

            <div className="logs-grid">

              <div className="panel-section">

                <h3>📊 Signal Log</h3>

                <SignalLog />

              </div>

              <div className="panel-section">

                <h3>📜 Trade Log</h3>

                <TradeLog />

              </div>

            </div>

          </div>

          {/* POSITION SETTINGS */}
          <div className="panel-card">

            <h2>📦 POSITION SETTINGS</h2>

            <PositionSettings />

          </div>

        </div>

        {/* ========================= */}
        {/* RIGHT COLUMN */}
        {/* ========================= */}
        <div className="right-column">

          {/* TRADE SETTINGS */}
          <div className="panel-card">

            <h2>🟢 TRADE SETTINGS</h2>

            <TradeSettings />

          </div>

          {/* EXECUTION SETTINGS */}
          <div className="panel-card">

            <h2>⚙️ EXECUTION SETTINGS</h2>

            <ExecutionSettings />

          </div>

          {/* RISK SETTINGS */}
          <div className="panel-card">

            <h2>🛡 RISK SETTINGS</h2>

            <RiskSettings />

          </div>

          {/* EMERGENCY SETTINGS */}
          <div className="panel-card">

            <h2>🚨 EMERGENCY SETTINGS</h2>

            <EmergencySettings />

          </div>

          {/* ADVANCED */}
          <div className="panel-card">

            <h2>📦 ADVANCED</h2>

            <AdvancedSettings />

          </div>

        </div>

      </div>

    </div>
  );
}