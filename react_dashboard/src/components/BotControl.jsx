import React, { useState, useEffect } from "react";

export default function BotControl() {
  const [status, setStatus] = useState({ running: false });
  const [positions, setPositions] = useState([]);
  const [logs, setLogs] = useState([]);

  const API_BASE = "http://34.85.66.137:8000";

  // --------------------------
  // Bot Status
  // --------------------------
  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/bot/status`);
      const data = await res.json();
      setStatus(data);
    } catch (err) {
      console.error("Error fetching bot status:", err);
      setStatus({ running: false });
    }
  };

  // --------------------------
  // Positions & Logs
  // --------------------------
  const fetchSummary = async () => {
    try {
      const res = await fetch(`${API_BASE}/bot/summary`);
      const data = await res.json();

      setPositions(data.positions || []);

      const logList = (data.positions || []).map(
        (p) => `${p.status} ${p.side} @ ${p.entry}`
      );

      setLogs(logList);
    } catch (err) {
      console.error("Error fetching summary:", err);
      setPositions([]);
      setLogs([]);
    }
  };

  // --------------------------
  // Start Bot
  // --------------------------
  const startBot = async () => {
    try {
      await fetch(`${API_BASE}/bot/start`, { method: "POST" });
      await fetchStatus();
      await fetchSummary();
    } catch (err) {
      console.error("Error starting bot:", err);
    }
  };

  // --------------------------
  // Stop Bot
  // --------------------------
  const stopBot = async () => {
    try {
      await fetch(`${API_BASE}/bot/stop`, { method: "POST" });
      await fetchStatus();
      await fetchSummary();
    } catch (err) {
      console.error("Error stopping bot:", err);
    }
  };

  // --------------------------
  useEffect(() => {
    fetchStatus();
    fetchSummary();

    const interval = setInterval(() => {
      fetchStatus();
      fetchSummary();
    }, 1000);

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

      <h4 style={{ marginTop: "20px" }}>Positions</h4>

      {positions.length === 0 ? (
        <p>No positions</p>
      ) : (
        <ul>
          {positions.map((p, i) => (
            <li key={i}>
              {p.status} {p.side} @ {p.entry} | Current: {p.current} | PnL:{" "}
              {p.pnl}
            </li>
          ))}
        </ul>
      )}

      <h4 style={{ marginTop: "20px" }}>Logs</h4>

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