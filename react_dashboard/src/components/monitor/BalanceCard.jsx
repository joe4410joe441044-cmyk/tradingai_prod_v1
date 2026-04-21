// src/components/monitor/BalanceCard.jsx

export default function BalanceCard({
  balance = 0,
  loading = false,
  error = false,
}) {
  const value = loading ? "Loading..." : Number(balance).toFixed(2);

  return (
    <div
      style={{
        background: "#111",
        borderRadius: "16px",
        padding: "16px",
        boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
        transition: "0.2s",
        cursor: "pointer",
        textAlign: "center",
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
        Balance
      </div>

      {/* VALUE */}
      <div
        style={{
          fontSize: "28px",
          fontWeight: "bold",
          color: "#4ade80", // 緑（資産）
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