import { useState } from "react";

export default function RiskPanel({ risk, refresh }) {

  const [dd, setDd] = useState(risk?.dd_limit || 10);
  const [streak, setStreak] = useState(risk?.loss_limit || 3);

  if (!risk) return null;

  const isKill = risk.kill_switch;

  const updateRisk = async () => {
    await fetch("/api/risk/update", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({
        max_drawdown_pct: Number(dd),
        max_loss_streak: Number(streak)
      })
    });

    refresh && refresh();
  };

  const resetRisk = async () => {
    await fetch("/api/risk/reset", { method: "POST" });

    refresh && refresh();
  };

  return (
    <div style={{
      padding: 12,
      border: "1px solid #333",
      borderRadius: 6,
      background: "#111"
    }}>
      <h3>Risk Manager</h3>

      <div>
        Max DD:
        <input
          value={dd}
          onChange={(e) => setDd(e.target.value)}
          style={{ marginLeft: 8 }}
        />
      </div>

      <div>
        Loss Streak:
        <input
          value={streak}
          onChange={(e) => setStreak(e.target.value)}
          style={{ marginLeft: 8 }}
        />
      </div>

      {/* 🔴 ここが追加部分 */}
      <div style={{ marginTop: 10 }}>
        <button onClick={updateRisk}>Update</button>
        <button onClick={resetRisk} style={{ marginLeft: 8 }}>
          Reset
        </button>
      </div>

      <p style={{
        color: isKill ? "red" : "lime",
        fontWeight: "bold"
      }}>
        Kill Switch: {isKill ? "ACTIVE 🔴" : "SAFE 🟢"}
      </p>

      {isKill && (
        <p style={{ color: "orange" }}>
          Reason: {risk.reason || "UNKNOWN"}
        </p>
      )}
    </div>
  );
}