import React, { useState } from "react";
import { API } from "../api";

export default function SampleBotControl() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const checkBotStatus = async () => {
    setLoading(true);

    try {
      const res = await fetch(API.botStatus());

      if (!res.ok) {
        throw new Error("API Error");
      }

      const data = await res.json();

      setStatus({
        running: data?.running ?? false,
        raw: data,
      });

    } catch (err) {
      console.error("Bot status error:", err);

      setStatus({
        error: "API接続エラー",
      });

    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: "20px", border: "1px solid #ccc", width: "320px" }}>
      <h3>Sample BOT Status</h3>

      <button onClick={checkBotStatus} disabled={loading}>
        {loading ? "Loading..." : "Check Status"}
      </button>

      <div style={{ marginTop: "10px" }}>
        {status ? (
          <pre style={{ background: "#f5f5f5", padding: "10px" }}>
            {JSON.stringify(status, null, 2)}
          </pre>
        ) : (
          <p>Click button to check bot status</p>
        )}
      </div>
    </div>
  );
}