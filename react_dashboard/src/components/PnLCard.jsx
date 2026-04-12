import { useState, useEffect } from "react";

const API_BASE = "http://34.85.66.137:8000";

export default function PnLCard() {
  const [pnl, setPnl] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchPnL = async () => {
    try {
      setLoading(true);

      const res = await fetch(`${API_BASE}/positions`);
      const data = await res.json();

      if (!Array.isArray(data)) {
        setPnl(0);
        return;
      }

      // 🔥 合計PnL計算
      const totalPnL = data.reduce((sum, p) => {
        return sum + (Number(p.pnl) || 0);
      }, 0);

      setPnl(totalPnL);

    } catch (err) {
      console.error("PnL fetch error:", err);
      setPnl("ERROR");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPnL();

    const interval = setInterval(fetchPnL, 10000);
    return () => clearInterval(interval);
  }, []);

  const isPositive = typeof pnl === "number" && pnl >= 0;

  return (
    <div className="card">
      <h3>PnL</h3>

      <h2 style={{ color: isPositive ? "lime" : "red" }}>
        {loading ? "Loading..." : pnl}
      </h2>
    </div>
  );
}