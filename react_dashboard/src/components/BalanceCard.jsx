import { useState, useEffect } from 'react';

const API_BASE = '/api';

export default function BalanceCard() {
  const [balance, setBalance] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchBalance = async () => {
    try {
      setLoading(true);

      const res = await fetch(`${API_BASE}/balance`);

      if (!res.ok) {
        throw new Error('API error');
      }

      const data = await res.json();

      // 🔥 安全対策（APIがobjectでも壊れないように）
      setBalance(data?.balance ?? data ?? 0);

    } catch (err) {
      console.error('Balance fetch error:', err);
      setBalance('ERROR');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBalance();

    const interval = setInterval(fetchBalance, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="card">
      <h3>Balance</h3>

      <h2>
        {loading ? 'Loading...' : balance}
      </h2>
    </div>
  );
}