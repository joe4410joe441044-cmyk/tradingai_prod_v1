export default function StatusPanel({
  balance = 0,
  equity = 0,
  pnl = 0,
  price = 0,

  currentDD = 0,
  lossStreak = 0,
  killSwitch = false,
  botStatus = "STOPPED",

  // 🔥 追加項目
  position = "NONE",
  entryPrice = null,
  lastSignal = "-",
  lastBlock = "-",
  engineState = "READY",
  connection = "OFFLINE",
}) {

  const format = (num) => {
    if (num === null || num === undefined) return "-";
    return Number(num).toLocaleString(undefined, {
      maximumFractionDigits: 4,
    });
  };

  const statusColor =
    botStatus === "RUNNING" ? "#00ff88" : "#ff4d4f";

  const connectionColor =
    connection === "ONLINE" ? "#00ff88" : "#ff4d4f";

  const engineColor =
    engineState === "READY" ? "#00ff88" : "#ffaa00";

  return (
    <div className="card">
      <h2>🔵 Status</h2>

      {/* 基本情報 */}
      <div>Balance: {format(balance)}</div>
      <div>Equity: {format(equity)}</div>
      <div>PnL: {format(pnl)}</div>
      <div>Price: {format(price)}</div>

      <hr />

      {/* ポジション情報 */}
      <div>Position: {position}</div>
      <div>Entry Price: {format(entryPrice)}</div>

      <hr />

      {/* リスク情報 */}
      <div>Current DD: {format(currentDD)}%</div>
      <div>Loss Streak: {lossStreak ?? "-"}</div>

      <hr />

      {/* 状態系 */}
      <div>Last Signal: {lastSignal}</div>
      <div>Last Block: {lastBlock}</div>

      <div>
        Engine State:{" "}
        <span style={{ color: engineColor }}>
          {engineState}
        </span>
      </div>

      <div>
        Kill Switch:{" "}
        <span style={{ color: killSwitch ? "#ff4d4f" : "#00ff88" }}>
          {killSwitch ? "ON" : "OFF"}
        </span>
      </div>

      <div>
        Bot Status:{" "}
        <span style={{ color: statusColor }}>
          {botStatus}
        </span>
      </div>

      <div>
        Connection:{" "}
        <span style={{ color: connectionColor }}>
          {connection}
        </span>
      </div>
    </div>
  );
}