// src/components/monitor/PnLCard.jsx

export default function PnLCard({
  pnl = 0,
  loading = false,
  error = false,
}) {
  const isPositive = pnl >= 0;

  const value = loading ? "Loading..." : Number(pnl).toFixed(2);

  const color = isPositive ? "#4ade80" : "#f87171";

  return (
    <div
      style={{
        background: "#111",
        borderRadius: "16px",
        padding: "16px",
        boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
        textAlign: "center",
        transition: "0.2s",
        cursor: "pointer",
      }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.transform = "translateY(-4px)")
      }
      onMouseLeave={(e) =>
        (e.currentTarget.style.transform = "translateY(0)")
      }
    >
      {/* TITLE */}
      <div
        style={{
          fontSize: "12px",
          opacity: 0.6,
          marginBottom: "8px",
        }}
      >
        PnL
      </div>

      {/* VALUE */}
      <div
        style={{
          fontSize: "28px",
          fontWeight: "bold",
          color,
        }}
      >
        {value}
      </div>

      {/* ERROR */}
      {error && (
        <div
          style={{
            marginTop: "6px",
            fontSize: "12px",
            color: "#f87171",
          }}
        >
          Fetch error
        </div>
      )}
    </div>
  );
}