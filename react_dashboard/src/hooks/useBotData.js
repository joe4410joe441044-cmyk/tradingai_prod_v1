import { useEffect, useState } from "react";

const API = "http://127.0.0.1:8000";

export default function useBotData() {
  const [data, setData] = useState({
    status: "LOADING",
    price: 0,
    balance: 0,
    pnl: 0,
    positions: [],
    logs: [],
    connection: "OFFLINE"
  });

  const fetchData = async () => {
    try {
      const res = await fetch(`${API}/api/bot/summary`);
      const json = await res.json();

      setData({
        status: json.status,
        price: json.price,
        balance: json.balance,
        pnl: json.pnl,
        positions: json.positions || [],
        logs: json.logs || [],
        connection: json.connection
      });
    } catch (e) {
      console.error("API ERROR", e);
      setData(prev => ({ ...prev, connection: "ERROR" }));
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, []);

  return data;
}