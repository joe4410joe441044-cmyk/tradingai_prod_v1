export default function StrategyMonitor() {
  return (
    <div className="bg-gray-900 p-4 rounded-2xl">
      <h2 className="text-lg mb-3">📊 Strategy Monitor</h2>

      <div className="text-sm space-y-1">
        <div>σ Volatility: 0.021</div>
        <div>Δ Imbalance: 0.58</div>
        <div>Γ Acceleration: 0.003</div>
        <div>Edge: -0.0003</div>
        <div>Regime: HIGH VOL</div>
        <div>Signal: BUY</div>
      </div>
    </div>
  );
}