export default function BotControl({ onStart, onStop }) {
  return (
    <div
      style={{
        background: "#111",
        borderRadius: "16px",
        padding: "16px",
        boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
    >
      {/* BUTTONS */}
      <div style={{ display: "flex", gap: "10px" }}>
        <button
          onClick={onStart}
          style={{
            flex: 1,
            padding: "10px",
            borderRadius: "10px",
            border: "none",
            background: "#16a34a",
            color: "#fff",
            fontWeight: "bold",
            cursor: "pointer",
            transition: "0.2s",
          }}
          onMouseEnter={(e) =>
            (e.currentTarget.style.opacity = "0.8")
          }
          onMouseLeave={(e) =>
            (e.currentTarget.style.opacity = "1")
          }
        >
          ▶ Start
        </button>

        <button
          onClick={onStop}
          style={{
            flex: 1,
            padding: "10px",
            borderRadius: "10px",
            border: "none",
            background: "#dc2626",
            color: "#fff",
            fontWeight: "bold",
            cursor: "pointer",
            transition: "0.2s",
          }}
          onMouseEnter={(e) =>
            (e.currentTarget.style.opacity = "0.8")
          }
          onMouseLeave={(e) =>
            (e.currentTarget.style.opacity = "1")
          }
        >
          ■ Stop
        </button>
      </div>
    </div>
  );
}