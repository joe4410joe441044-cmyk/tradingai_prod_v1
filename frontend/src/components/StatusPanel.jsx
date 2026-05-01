export default function StatusPanel({
  balance,
  equity,
  pnl,
  price,
  currentDD,
  lossStreak,
  killSwitch,
  botStatus,
}) {
  return (
    <div className="panel status">
      <h3>🔵 Status</h3>

      <div>Balance: {balance}</div>
      <div>Equity: {equity}</div>
      <div>PnL: {pnl}</div>
      <div>Price: {price}</div>

      <hr />

      <div>Current DD: {currentDD}%</div>
      <div>Loss Streak: {lossStreak}</div>
      <div>Kill Switch: {killSwitch ? "ON" : "OFF"}</div>
      <div>Bot Status: {botStatus}</div>
    </div>
  );
}