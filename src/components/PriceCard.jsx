import { useState, useEffect } from "react";

const API_BASE = "http://35.194.104.74:8000";

export default function PriceCard() {
  const [price, setPrice] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchPrice = async () => {
    try {
      setLoading(true);

      const res = await fetch(`${API_BASE}/positions`);
      const data = await res.json();

      if (!Array.isArray(data) || data.length === 0) {
        setPrice(null);
        return;
      }

      // 🔥 最新ポジションの価格を使用
      const latest = data[data.length - 1];

      setPrice(latest.mark_price ?? latest.entry_price ?? 0);

    } catch (err) {
      console.error("Price fetch error:", err);
      setPrice("ERROR");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPrice();

    const interval = setInterval(fetchPrice, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="card">
      <h3>Price</h3>

      <h2>
        {loading ? "Loading..." : price}
      </h2>
    </div>
  );
}
