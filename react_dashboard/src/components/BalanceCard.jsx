// src/components/BalanceCard.jsx

import { useState, useEffect } from "react";
import { getBalance } from "../api/bot";

export default function BalanceCard() {
  const [balance, setBalance] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // --------------------------
  // BALANCE取得（API統一版）
  // --------------------------
  const fetchBalance = async () => {
    try {
      setLoading(true);
      setError(false);

      const data = await getBalance();

      // 型ガード（API崩れ対策）
      const normalized =
        typeof data === "number"
          ? data
          : data?.balance ?? 0;

      setBalance(normalized);

    } catch (err) {
      console.error("Balance fetch error:", err);
      setError(true);
      setBalance(0);
    } finally {
      setLoading(false);
    }
  };

  // --------------------------
  // 初回 + 定期更新
  // --------------------------
  useEffect(() => {
    fetchBalance();

    const interval = setInterval(() => {
      fetchBalance();
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  // --------------------------
  // UI
  // --------------------------
  return (
    <div className="card">
      <h3>Balance</h3>

      <h2>
        {loading
          ? "Loading..."
          : error
            ? "ERROR"
            : `$${balance.toLocaleString()}`}
      </h2>
    </div>
  );
}