import PriceCard from "../monitor/PriceCard";
import BalanceCard from "../monitor/BalanceCard";
import PnLCard from "../monitor/PnLCard";
import PositionsTable from "../monitor/PositionsTable";
import LogsPanel from "../monitor/LogsPanel";

export default function AssetDashboard({
  price,
  balance,
  pnl,
  positions,
  logs,
}) {
  return (
    <div className="asset-dashboard">

      {/* TOP ROW */}
      <div className="top-row">
        <PriceCard price={price ?? 0} />
        <BalanceCard balance={balance ?? 0} />
        <PnLCard pnl={pnl ?? 0} />
      </div>

      {/* POSITIONS */}
      <div className="section">
        <PositionsTable positions={positions ?? []} />
      </div>

      {/* LOGS */}
      <div className="section">
        <LogsPanel logs={logs ?? []} />
      </div>

    </div>
  );
}