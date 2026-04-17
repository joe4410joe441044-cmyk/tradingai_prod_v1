import { useState, useEffect } from "react";
import { API } from "../api";

export default function TradeHistory() {
  const [trades, setTrades] = useState([]);

  const fetchData = async () => {
    try {
      const res = await fetch(API.trades());

      if (!res.ok) {
        console.error(await res.text());
        return;
      }

      const data = await res.json();

      setTrades(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error(err);
      setTrades([]);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  return (
    <div>
      <h3>Trade History</h3>

      {trades.length === 0 ? (
        <p>No trades</p>
      ) : (
        <ul>
          {trades.map((t, i) => (
            <li key={i}>
              {t.symbol} | {t.side} | {t.price}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}s