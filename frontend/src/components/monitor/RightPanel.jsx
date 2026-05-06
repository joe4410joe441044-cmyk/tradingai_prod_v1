import StrategyMonitor from "./StrategyMonitor";

export default function RightPanel({
  status = "UNKNOWN",
  connected = false,
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "16px", // ← 少し広げる（重要）
      }}
    >

      {/* ===== STATUS PANEL ===== */}
      <div
        style={{
          background: "#111",
          borderRadius: "16px",
          padding: "16px",
          boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
          display: "flex",
          flexDirection: "column",
          gap: "10px",
        }}
      >
        {/* STATUS */}
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span>Status</span>
          <span
            style={{
              color: status === "RUNNING" ? "#4ade80" : "#f87171",
              fontWeight: "bold",
            }}
          >
            {status}
          </span>
        </div>

        {/* CONNECTION */}
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span>Connection</span>
          <span
            style={{
              color: connected ? "#4ade80" : "#f87171",
              fontWeight: "bold",
            }}
          >
            {connected ? "ONLINE" : "OFFLINE"}
          </span>
        </div>

        {/* UI HEALTH */}
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span>UI</span>
          <span style={{ color: "#4ade80", fontWeight: "bold" }}>
            OK
          </span>
        </div>
      </div>

      {/* ===== STRATEGY MONITOR（追加） ===== */}
      <StrategyMonitor />

    </div>
  );
}