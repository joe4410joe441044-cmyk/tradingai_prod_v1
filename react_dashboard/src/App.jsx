import useBotData from "./hooks/useBotData";

import AssetDashboard from "./components/dashboard/AssetDashboard";
import RightPanel from "./components/monitor/RightPanel";
import BotControl from "./components/control/BotControl";

export default function App() {
  const bot = useBotData(2000);

  return (
    <div style={{ padding: 12 }}>
      <h2>TradingAI Dashboard</h2>

      {/* GLOBAL STATUS（唯一の表示） */}
      <div style={{ marginBottom: 10 }}>
        Status: {bot.status} {bot.connected ? "🟢" : "🔴"}
      </div>

      {/* MAIN DASHBOARD（表示専用） */}
      <AssetDashboard
        price={bot.price}
        balance={bot.balance}
        pnl={bot.pnl}
        logs={bot.logs}
        positions={bot.positions}
      />

      {/* CONTROL（操作専用） */}
      <BotControl
        onStart={bot.start}
        onStop={bot.stop}
      />

      {/* SIDE PANEL（補助表示） */}
      <RightPanel />
    </div>
  );
}