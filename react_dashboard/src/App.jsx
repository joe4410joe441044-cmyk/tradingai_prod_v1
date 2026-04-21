import useBotData from "./hooks/useBotData";

import AssetDashboard from "./components/dashboard/AssetDashboard";
import RightPanel from "./components/monitor/RightPanel";
import BotControl from "./components/control/BotControl";

// 共通カード
function Card({ title, children, style = {} }) {
  return (
    <div style={{
      background: "#111",
      borderRadius: "16px",
      padding: "16px",
      boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
      ...style
    }}>
      <div style={{
        fontSize: "12px",
        opacity: 0.6,
        marginBottom: "8px"
      }}>
        {title}
      </div>

      <div style={{
        fontSize: "16px",
        fontWeight: "bold"
      }}>
        {children}
      </div>
    </div>
  );
}

export default function App() {
  const bot = useBotData(2000);

  return (
    <div style={{
      padding: 16,
      background: "#0b0b0b",
      minHeight: "100vh",
      color: "#fff"
    }}>
      <h2 style={{ marginBottom: 16 }}>TradingAI Dashboard</h2>

      {/* ステータス */}
      <div style={{ marginBottom: 16 }}>
        <Card title="Status">
          {bot.status} {bot.connected ? "🟢" : "🔴"}
        </Card>
      </div>

      {/* 🔥 ここに追加 */}
      <div style={{ marginBottom: 16 }}>
        <Card title="Bot Control">
          <BotControl
            onStart={bot.start}
            onStop={bot.stop}
          />
        </Card>
      </div>

      {/* メイングリッド */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "2fr 1fr",
        gap: "16px"
      }}>
        
        {/* 左メイン */}
        <div style={{
          display: "flex",
          flexDirection: "column",
          gap: "16px"
        }}>
          <Card title="Dashboard">
            <AssetDashboard
              price={bot.price}
              balance={bot.balance}
              pnl={bot.pnl}
              logs={bot.logs}
              positions={bot.positions}
            />
          </Card>
        </div>

        {/* 右サイド */}
        <div>
          <Card title="System Info">
            <RightPanel
              status={bot.status}
              connected={bot.connected}
            />
          </Card>
        </div>

      </div>
    </div>
  );
}