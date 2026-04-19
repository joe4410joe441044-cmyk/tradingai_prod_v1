// src/components/monitor/BalanceCard.jsx

export default function BalanceCard({
  balance = 0,
  loading = false,
  error = false,
}) {
  return (
    <div style={{ padding: "10px", border: "1px solid #333" }}>

      <h3>Balance</h3>

      {/* VALUE */}
      <h2>
        {loading ? "Loading..." : Number(balance).toFixed(2)}
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