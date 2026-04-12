// src/components/BotControl.jsx

import { useState, useEffect } from "react";

// API層（新設）
import {
  getBotStatus,
  getPositions,
  getLogs,
  startBot,
  stopBot
} from "../api/bot";

export default function BotControl() {
  const [status, setStatus] = useState({ running: false });
  const [positions, setPositions] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  // --------------------------
  // 全データ取得統合
  // --------------------------
  const fetchAll = async () => {
    try {
      setLoading(true);

      const [s, p, l] = await Promise.all([
        getBotStatus(),
        getPositions(),
        getLogs()
      ]);

      setStatus(s);
      setPositions(p);
      setLogs(l);
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
  useEffect(() => {
    fetchAll();

    const interval = setInterval(() => {
      fetchAll();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

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

      <button onClick={startBot}>Start</button>
      <button onClick={stopBot} style={{ marginLeft: "10px" }}>
        Stop
      </button>

      {/* ---------------------- */}
      {/* POSITIONS */}
      {/* ---------------------- */}
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

      {/* ---------------------- */}
      {/* LOGS */}
      {/* ---------------------- */}
      <h4>Logs</h4>

      {logs.length === 0 ? (
        <p>No logs</p>
      ) : (
        <ul>
          {logs.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}