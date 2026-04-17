import { useState, useEffect } from "react";

const API_BASE = "http://35.194.104.74:8000";

export default function PnLCard() {
  const [pnl, setPnl] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchPnL = async () => {
    try {
      setLoading(true);
      setError(false);

      const res = await fetch(`${API_BASE}/positions`);

      if (!res.ok) {
        throw new Error(`HTTP error: ${res.status}`);
      }

      const data = await res.json();

      const safeData = Array.isArray(data) ? data : [];

      const totalPnL = safeData.reduce((sum, p) => {
        return sum + (Number(p.pnl) || 0);
      }, 0);

      setPnl(totalPnL);

    } catch (err) {
      console.error("PnL fetch error:", err);
      setError(true);
      setPnl(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPnL();

    const interval = setInterval(fetchPnL, 10000);
    return () => clearInterval(interval);
  }, []);

  // --------------------------
  // 安全化（表示クラッシュ防止）
  // --------------------------
  const safePnL =
    typeof pnl === "number" && !isNaN(pnl)
      ? pnl
      : 0;

  const isPositive = safePnL >= 0;

  return (
    <div className="card">
      <h3>PnL</h3>

      <h2 style={{ color: isPositive ? "lime" : "red" }}>
        {loading
          ? "Loading..."
          : error
            ? "ERROR"
            : safePnL}
      </h2>
    </div>
  );
}