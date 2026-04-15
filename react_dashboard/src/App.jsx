import { useEffect, useState } from "react";

const API_BASE = "http://35.194.104.74:8000";

export default function App() {
  const [status, setStatus] = useState("loading");
  const [price, setPrice] = useState(0);

  useEffect(() => {
    fetch(`${API_BASE}/bot/status`)
      .then(res => res.json())
      .then(data => setStatus(data.status))
      .catch(() => setStatus("error"));

    fetch(`${API_BASE}/price`)
      .then(res => res.json())
      .then(data => setPrice(data.price))
      .catch(() => setPrice(0));
  }, []);

  return (
    <div style={{ padding: "20px" }}>
      <h1>TradingAI Dashboard</h1>

      <p>Status: {status}</p>
      <p>Price: {price}</p>

      <button onClick={() => fetch(`${API_BASE}/bot/start`, { method: "POST" })}>
        Start Bot
      </button>

      <button onClick={() => fetch(`${API_BASE}/bot/stop`, { method: "POST" })}>
        Stop Bot
      </button>
    </div>
  );
}