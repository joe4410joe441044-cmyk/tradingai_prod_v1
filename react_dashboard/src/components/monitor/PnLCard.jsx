// src/components/monitor/PnLCard.jsx

export default function PnLCard({
  pnl = 0,
  loading = false,
  error = false,
}) {

  const isPositive = pnl >= 0;

  return (
    <div style={{ padding: "10px", border: "1px solid #333" }}>

      <h3>PnL</h3>

      {/* VALUE */}
      <h2 style={{ color: isPositive ? "lime" : "red" }}>
        {loading ? "Loading..." : Number(pnl).toFixed(2)}
      </h2>

      {/* ERROR */}
      {error && (
        <p style={{ color: "red" }}>
          Fetch error
        </p>
      )}

    </div>
  );
}