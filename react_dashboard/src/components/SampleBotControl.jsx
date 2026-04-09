// src/components/SampleBotControl.jsx
import React, { useState } from "react";

const API_BASE = "http://YOUR_VPS_IP:8000"; // ← ここを VPS の IP に変更

export default function SampleBotControl() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const checkBotStatus = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/bot/status`);
      const data = await res.json();
      setStatus(data);
    } catch (err) {
      setStatus({ error: "接続失敗" });
    }
    setLoading(false);
  };

  return (
    <div style={{ padding: "20px", border: "1px solid #ccc", width: "300px" }}>
      <h3>Sample BOT Status</h3>
      <button onClick={checkBotStatus} disabled={loading}>
        {loading ? "確認中..." : "状態確認"}
      </button>
      <pre style={{ marginTop: "10px", background: "#f5f5f5", padding: "10px" }}>
        {status ? JSON.stringify(status, null, 2) : "ここにBOT状態が表示されます"}
      </pre>
    </div>
  );
}