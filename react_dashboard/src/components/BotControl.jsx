import React, { useState, useEffect } from "react";

const API_BASE = "http://34.85.66.137:8000";

export default function BotControl() {
  const [status, setStatus] = useState({ running: false });
  const [positions, setPositions] = useState([]);
  const [logs, setLogs] = useState([]);

  // --------------------------
  // BOT STATUS（修正）
  // --------------------------
  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/bot_status`);
      const data = await res.json();
      setStatus(data);
    } catch (err) {
      console.error("Bot status error:", err);
      setStatus({ running: false });
    }
  };

  // --------------------------
  // POSITIONS（修正）
  // --------------------------
  const fetchPositions = async () => {
    try {
      const res = await fetch(`${API_BASE}/positions`);
      const data = await res.json();
      setPositions(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error("Positions error:", err);
      setPositions([]);
    }
  };

  // --------------------------
  // LOGS（修正）
  // --------------------------
  const fetchLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/logs`);
      const text = await res.text();
      setLogs(text.split("\n").filter(Boolean));
    } catch (err) {
      console.error("Logs error:", err);
      setLogs([]);
    }
  };

  // --------------------------
  // START / STOP（VPS仕様）
  // --------------------------
  const startBot = async () => {
    await fetch(`${API_BASE}/start`);
    fetchStatus();
    fetchPositions();
  };

  const stopBot = async () => {
    await fetch(`${API_BASE}/stop`);
    fetchStatus();
    fetchPositions();
  };

  // --------------------------
  useEffect(() => {
    fetchStatus();
    fetchPositions();
    fetchLogs();

    const interval = setInterval(() => {
      fetchStatus();
      fetchPositions();
      fetchLogs();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  // --------------------------
  return (
    <div style={{ marginTop: "20px" }}>
      <h3>Bot Control</h3>

      <p>Status: {status?.running ? "RUNNING" : "STOPPED"}</p>

      <button onClick={startBot}>Start</button>
      <button onClick={stopBot} style={{ marginLeft: "10px" }}>
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
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}