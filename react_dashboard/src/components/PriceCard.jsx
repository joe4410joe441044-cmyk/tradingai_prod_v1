import { useState, useEffect } from "react";
import { API } from "../api";

export default function PriceCard() {
  const [price, setPrice] = useState(0);

  const fetchData = async () => {
    try {
      const res = await fetch(API.price());

      if (!res.ok) {
        console.error(await res.text());
        return;
      }

      const data = await res.json();

      setPrice(data?.price ?? 0);
    } catch (err) {
      console.error("PriceCard error:", err);
      setPrice(0);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      <h3>Price</h3>
      <p>{price}</p>
    </div>
  );
}
