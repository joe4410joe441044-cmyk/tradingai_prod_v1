import { useState, useEffect } from "react";

const API_BASE = "http://34.85.66.137:8000";

export default function PriceCard() {
  const [price, setPrice] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchPrice = async () => {
    try {
      setLoading(true);

      const res = await fetch(`${API_BASE}/price`);
      const data = await res.json();

      setPrice(data.price ?? 0);
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