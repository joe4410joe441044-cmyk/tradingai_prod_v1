import { useState, useEffect } from "react";
import { API } from "../../api/index"; // ← 修正ポイント

export default function BotControl() {
  const [status, setStatus] = useState({ running: false });
  const [positions, setPositions] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  // --------------------------
  // データ取得（統合）
  // --------------------------
  const fetchAll = async () => {
    try {
      setLoading(true);

      const [sRes, pRes, lRes] = await Promise.all([
        fetch(API.botStatus()),
        fetch(API.positions()),
        fetch(API.logs()),
      ]);

      const [s, p, l] = await Promise.all([
        sRes.ok ? sRes.json() : null,
        pRes.ok ? pRes.json() : null,
        lRes.ok ? lRes.json() : null,
      ]);

      setStatus(s ?? { running: false });

      // 安全化（FastAPI想定：配列 or {logs: []} 両対応）
      setPositions(Array.isArray(p) ? p : p?.positions ?? []);

      setLogs(Array.isArray(l) ? l : l?.logs ?? []);

    } catch (err) {
      console.error("BotControl fetch error:", err);

      setStatus({ running: false });
      setPositions([]);
      setLogs([]);
    } finally {
      setLoading(false);
    }
  };

  // --------------------------
  // Bot Start
  // --------------------------
  const handleStart = async () => {
    try {
      const res = await fetch(API.botStart(), { method: "POST" });

      if (!res.ok) throw new Error("Failed to start bot");

      fetchAll();
    } catch (err) {
      console.error("Start error:", err);
    }
  };

  // --------------------------
  // Bot Stop
  // --------------------------
  const handleStop = async () => {
    try {
      const res = await fetch(API.botStop(), { method: "POST" });

      if (!res.ok) throw new Error("Failed to stop bot");

      fetchAll();
    } catch (err) {
      console.error("Stop error:", err);
    }
  };

  // --------------------------
  // 初期ロード + ポーリング
  // --------------------------
  useEffect(() => {
    fetchAll();

    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, []);

  // --------------------------
  // UI
  // --------------------------
  return (
    <div style={{ marginTop: "20px" }}>
      <h3>Bot Control</h3>

      <p>
        Status:{" "}
        {loading
          ? "Loading..."
          : status?.running
          ? "RUNNING"
          : "STOPPED"}
      </p>

      <button onClick={handleStart}>Start</button>
      <button onClick={handleStop} style={{ marginLeft: "10px" }}>
        Stop
      </button>

      <h4>Positions</h4>
      {positions.length === 0 ? (
        <p>No positions</p>
      ) : (
        <ul>
          {positions.map((p, i) => (
            <li key={i}>
              {p.side} @ {p.entry_price} | PnL: {p.pnl}
            </li>
          ))}
        </ul>
      )}

      <h4>Logs</h4>
      {logs.length === 0 ? (
        <p>No logs</p>
      ) : (
        <ul>
          {logs.map((l, i) => (
            <li key={i}>
              {typeof l === "string" ? l : JSON.stringify(l)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}