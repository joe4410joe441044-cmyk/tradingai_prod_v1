export default function RiskPanel({ risk }) {

  if (!risk) return null;

  return (
    <div>
      <p>Drawdown: {(risk.drawdown * 100).toFixed(2)}%</p>
      <p>Loss Streak: {risk.loss_streak}</p>
      <p>Peak Equity: {risk.peak_equity}</p>

      <p style={{ color: risk.kill_switch ? "red" : "lime" }}>
        Kill Switch: {risk.kill_switch ? "ACTIVE 🔴" : "SAFE 🟢"}
      </p>
    </div>
  );
}