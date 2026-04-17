import { useState, useEffect } from "react";
import { API } from "../api";

export default function BalanceCard() {
  const [balance, setBalance] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      setLoading(true);

      const res = await fetch(API.balance());

      if (!res.ok) {
        console.error(await res.text());
        return;
      }

      const data = await res.json();

      setBalance(data?.balance ?? 0);
    } catch (err) {
      console.error("BalanceCard error:", err);
      setBalance(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  return (
    <div>
      <h3>Balance</h3>
      {loading ? "Loading..." : <p>{balance}</p>}
    </div>
  );
}