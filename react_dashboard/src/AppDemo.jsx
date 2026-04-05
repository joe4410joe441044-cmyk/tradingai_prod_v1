import { useEffect, useState } from "react";

export default function AppDemo() {
  const [running, setRunning] = useState(false);
  const [positions, setPositions] = useState([]);

  // Bot Status 取得
  const fetchStatus = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/bot/status");
      const data = await res.json();
      setRunning(data.running);
    } catch (err) {
      console.error("Status fetch error:", err);
    }
  };

  // Summary 取得
  const fetchSummary = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/bot/summary");
      const data = await res.json();
      setPositions(data.positions || []);
    } catch (err) {
      console.error("Summary fetch error:", err);
    }
  };

  useEffect(() => {
    fetchStatus();
    fetchSummary();
    const interval = setInterval(() => {
      fetchStatus();
      fetchSummary();
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Start Bot
  const startBot = async () => {
    await fetch("http://127.0.0.1:8000/bot/start", { method: "POST" });
    await fetchStatus();
    await fetchSummary();
  };

  // Stop Bot
  const stopBot = async () => {
    await fetch("http://127.0.0.1:8000/bot/stop", { method: "POST" });
    await fetchStatus();
  };

  return (
    <div style={{ padding: 20, fontFamily: "sans-serif" }}>
      <h1>TradingAI Bot Demo</h1>

      <div>
        <button onClick={startBot} disabled={running}>
          Start
        </button>
        <button onClick={stopBot} disabled={!running} style={{ marginLeft: 10 }}>
          Stop
        </button>
        <span style={{ marginLeft: 20 }}>
          Status: {running ? "RUNNING" : "STOPPED"}
        </span>
      </div>

      <h2>Positions</h2>
      {positions.length === 0 ? (
        <p>No positions</p>
      ) : (
        <table border="1" cellPadding="5" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Entry</th>
              <th>Current</th>
              <th>Volume</th>
              <th>Status</th>
              <th>PnL</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos, idx) => (
              <tr key={idx}>
                <td>{pos.symbol}</td>
                <td>{pos.side}</td>
                <td>{pos.entry}</td>
                <td>{pos.current}</td>
                <td>{pos.volume}</td>
                <td>{pos.status}</td>
                <td>{pos.pnl.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}