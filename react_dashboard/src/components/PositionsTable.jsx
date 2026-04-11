export default function PositionsTable({ positions, loading }) {
  if (loading) return <div>Loading...</div>;

  if (!Array.isArray(positions) || positions.length === 0) {
    return <div>No positions</div>;
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table border="1" style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th>Pair</th>
            <th>Side</th>
            <th>Entry</th>
            <th>Current</th>
            <th>PnL</th>
            <th>Size</th>
          </tr>
        </thead>

        <tbody>
          {positions.map((p, i) => (
            <tr key={i}>
              <td>{p?.pair ?? "-"}</td>
              <td>{p?.side ?? "-"}</td>
              <td>{p?.entry ?? "-"}</td>
              <td>{p?.current ?? "-"}</td>
              <td
                style={{
                  color: (p?.pnl ?? 0) >= 0 ? "lime" : "red",
                  fontWeight: "bold",
                }}
              >
                {p?.pnl ?? 0}
              </td>
              <td>{p?.size ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}