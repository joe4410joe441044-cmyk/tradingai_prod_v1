import React from "react";

export default function StatusBar({ status, logs }) {
  return (
    <div style={{
      position: "fixed",
      bottom: 0,
      left: 0,
      width: "100%",
      background: "#111",
      color: "#0f0",
      padding: "8px",
      fontSize: "12px",
      borderTop: "1px solid #333"
    }}>
      <div>
        STATUS: {status === "RUNNING" ? "🟢 RUNNING" : "🔴 STOPPED"}
      </div>

      <div style={{ marginTop: "4px", maxHeight: "60px", overflowY: "auto" }}>
        {logs.slice(-5).map((log, i) => (
          <div key={i}>{log}</div>
        ))}
      </div>
    </div>
  );
}