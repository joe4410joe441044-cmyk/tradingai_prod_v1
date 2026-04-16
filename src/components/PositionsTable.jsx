// src/components/monitor/PositionsTable.jsx

export default function PositionsTable({ positions, loading }) {
  // 螳牙・蛹厄ｼ・PI縺悟｣翫ｌ縺ｦ縺ｦ繧り誠縺ｨ縺輔↑縺・ｼ・
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
            // 繝輔か繝ｼ繝ｫ繝舌ャ繧ｯ謨ｴ蠖｢・・ormatPosition縺檎┌縺上※繧ょ虚縺擾ｼ・
            const f = {
              pair: p?.pair ?? "-",
              side: p?.side ?? "-",
              entry: p?.entry ?? 0,
              current: p?.current ?? 0,
              pnl: p?.pnl ?? 0,
              size: p?.size ?? 0,
            };

            return (
              <tr key={p?.id ?? i}>
                <td style={td}>{f.pair}</td>
                <td style={td}>{f.side}</td>
                <td style={td}>{f.entry}</td>
                <td style={td}>{f.current}</td>

                <td
                  style={{
                    ...td,
                    color: f.pnl >= 0 ? "limegreen" : "red",
                    fontWeight: "bold",
                  }}
                >
                  {isNaN(f.pnl) ? 0 : f.pnl}
                </td>

                <td style={td}>{f.size}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// --------------------
// style螳夂ｾｩ・郁ｦ九ｄ縺吶￥邨ｱ荳・・
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
