// src/components/PositionsTable.jsx

export default function PositionsTable({ positions, loading }) {
  // 安全化（APIが壊れてても落とさない）
  const safePositions = Array.isArray(positions) ? positions : [];

  if (loading) return <div>Loading...</div>;

  if (safePositions.length === 0) {
    return <div>No positions</div>;
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "14px",
        }}
      >
        <thead>
          <tr style={{ background: "#f5f5f5" }}>
            <th style={th}>Pair</th>
            <th style={th}>Side</th>
            <th style={th}>Entry</th>
            <th style={th}>Current</th>
            <th style={th}>PnL</th>
            <th style={th}>Size</th>
          </tr>
        </thead>

        <tbody>
          {safePositions.map((p, i) => {
            const pnl = Number(p?.pnl ?? 0);

            return (
              <tr key={p?.id ?? i}>
                <td style={td}>{p?.pair ?? "-"}</td>
                <td style={td}>{p?.side ?? "-"}</td>
                <td style={td}>{p?.entry ?? "-"}</td>
                <td style={td}>{p?.current ?? "-"}</td>

                <td
                  style={{
                    ...td,
                    color: pnl >= 0 ? "limegreen" : "red",
                    fontWeight: "bold",
                  }}
                >
                  {isNaN(pnl) ? 0 : pnl}
                </td>

                <td style={td}>{p?.size ?? "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// --------------------
// style定義（見やすく統一）
// --------------------
const th = {
  padding: "8px",
  border: "1px solid #ddd",
  textAlign: "left",
};

const td = {
  padding: "8px",
  border: "1px solid #eee",
};