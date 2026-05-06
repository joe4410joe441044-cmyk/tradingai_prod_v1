import Header from "../components/Header";

// =========================
// CONFIG
// =========================
import TradeSettings from "../components/config/TradeSettings";
import ExecutionSettings from "../components/config/ExecutionSettings";
import RiskSettings from "../components/config/RiskSettings";
import EmergencySettings from "../components/config/EmergencySettings";
import PositionSettings from "../components/config/PositionSettings";

// =========================
// MONITOR
// =========================
import StrategyMonitor from "../components/StrategyMonitor";
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
  return (
    <div className="dashboard">

      {/* ========================= */}
      {/* HEADER */}
      {/* ========================= */}
      <Header />

      {/* ========================= */}
      {/* TOP GRID */}
      {/* ========================= */}
      <div className="top-grid">

        {/* ========================= */}
        {/* CONFIG COLUMN */}
        {/* ========================= */}
        <div className="config-column">

          <div className="panel-card">
            <h2>🟢 CONFIG</h2>
          </div>

          <TradeSettings />

          <ExecutionSettings />

          <RiskSettings />

          <EmergencySettings />

          <PositionSettings />

        </div>

        {/* ========================= */}
        {/* MONITOR COLUMN */}
        {/* ========================= */}
        <div className="monitor-column">

          <div className="panel-card">
            <h2>🔵 MONITOR</h2>
          </div>

          <StrategyMonitor />

          <StatusPanel />

          <ResultPanel />

        </div>

      </div>

      {/* ========================= */}
      {/* BOTTOM GRID */}
      {/* ========================= */}
      <div className="bottom-grid">

        {/* ========================= */}
        {/* EXECUTION */}
        {/* ========================= */}
        <div className="panel-card execution-wrapper">

          <h2>🔘 EXECUTION</h2>

          <ExecutionPanel />

        </div>

        {/* ========================= */}
        {/* LOGS */}
        {/* ========================= */}
        <div className="panel-card logs-wrapper">

          <h2>📊 LOGS</h2>

          <div className="logs-grid">

            <SignalLog />

            <TradeLog />

          </div>

        </div>

      </div>

    </div>
  );
}