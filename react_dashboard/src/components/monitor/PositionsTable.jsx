// src/components/monitor/PositionsTable.jsx

export default function PositionsTable({
  positions = [],
  loading = false,
  error = false,
}) {
  return (
    <div
      style={{
        background: "#0b0b0b",
        borderRadius: "10px",
        padding: "10px",
        maxHeight: "300px",
        overflowY: "auto",
        fontSize: "12px",
        fontFamily: "monospace",
      }}
    >
      {/* LOADING */}
      {loading && <div style={{ opacity: 0.6 }}>Loading...</div>}

      {/* ERROR */}
      {error && (
        <div style={{ color: "#f87171" }}>
          Fetch error
        </div>
      )}

      {/* EMPTY */}
      {!loading && positions.length === 0 && (
        <div style={{ opacity: 0.5 }}>
          No positions
        </div>
      )}

      {/* LIST */}
      {!loading &&
        positions.map((p, i) => {
          const pnl = Number(p.pnl ?? 0);
          const color = pnl >= 0 ? "#4ade80" : "#f87171";

          return (
            <div
              key={`${p.symbol}-${p.side}-${i}`}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "4px 0",
                borderBottom: "1px solid rgba(255,255,255,0.05)",
              }}
            >
              <span>
                {p.symbol ?? "?"} | {p.side ?? "?"}
              </span>

              <span style={{ color }}>
                {pnl.toFixed(2)}
              </span>
            </div>
          );
        })}
    </div>
  );
}