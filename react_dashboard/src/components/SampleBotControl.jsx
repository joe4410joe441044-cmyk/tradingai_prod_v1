// src/components/SampleBotControl.jsx
import React, { useState } from "react";

const API_BASE = "http://34.85.66.137:8000";

export default function SampleBotControl() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const checkBotStatus = async () => {
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/bot_status`);

      if (!res.ok) {
        throw new Error("API Error");
      }

      const data = await res.json();

      // 安全に整形（壊れてても落ちない）
      setStatus({
        running: data?.running ?? false,
        raw: data,
      });

    } catch (err) {
      console.error("Bot status error:", err);
      setStatus({ error: "接続失敗 / API未起動" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: "20px", border: "1px solid #ccc", width: "320px" }}>
      <h3>Sample BOT Status</h3>

      <button onClick={checkBotStatus} disabled={loading}>
        {loading ? "確認中..." : "状態確認"}
      </button>

      <div style={{ marginTop: "10px" }}>
        {status ? (
          <pre style={{ background: "#f5f5f5", padding: "10px" }}>
            {JSON.stringify(status, null, 2)}
          </pre>
        ) : (
          <p>ここにBOT状態が表示されます</p>
        )}
      </div>
    </div>
  );
}