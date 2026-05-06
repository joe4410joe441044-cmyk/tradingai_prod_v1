import Header from "../components/Header";
import TradeSettings from "../components/TradeSettings";
import StrategyMonitor from "../components/StrategyMonitor";
import StrategyControl from "../components/StrategyControl";
import StatusPanel from "../components/StatusPanel";
import ExecutionPanel from "../components/ExecutionPanel";
import LogPanel from "../components/LogPanel";

import "../styles/dashboard.css";

export default function Dashboard() {
  return (
    <div className="container">
      <Header />

      <div className="grid">
        <TradeSettings />
        <StrategyMonitor />

        <StrategyControl />
        <StatusPanel />
      </div>

      <ExecutionPanel />
      <LogPanel />
    </div>
  );
}