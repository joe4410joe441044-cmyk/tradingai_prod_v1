import PriceCard from "../monitor/PriceCard";
import BalanceCard from "../monitor/BalanceCard";
import PnLCard from "../monitor/PnLCard";
import PositionsTable from "../monitor/PositionsTable";
import LogsPanel from "../monitor/LogsPanel";

// 共通カード
function Card({ title, children }) {
  return (
    <div
      style={{
        background: "#111",
        borderRadius: "16px",
        padding: "16px",
        boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
      }}
    >
      <div
        style={{
          fontSize: "12px",
          opacity: 0.6,
          marginBottom: "8px",
        }}
      >
        {title}
      </div>

      {children}
    </div>
  );
}

export default function AssetDashboard({
  price,
  balance,
  equity,   // ←追加
  pnl,
  positions,
  logs,
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "16px",
      }}
    >
      {/* TOP ROW */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)", // ←4列に変更
          gap: "16px",
        }}
      >
        <PriceCard price={price ?? 0} />

        <BalanceCard balance={balance ?? 0} />

        {/* 🔥 Equity表示 */}
        <Card title="Equity">
          <div
            style={{
              fontSize: "20px",
              fontWeight: "bold",
            }}
          >
            {equity ?? 0}
          </div>
        </Card>

        <PnLCard pnl={pnl ?? 0} />
      </div>

      {/* POSITIONS */}
      <Card title="Positions">
        <PositionsTable positions={positions ?? []} />
      </Card>

      {/* LOGS */}
      <Card title="Logs">
        <LogsPanel logs={logs ?? []} />
      </Card>
    </div>
  );
}