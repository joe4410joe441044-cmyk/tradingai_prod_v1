import { useState, useEffect } from 'react';

const API_BASE = 'http://34.85.66.137:8000';

export default function BalanceCard() {
  const [balance, setBalance] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchBalance = async () => {
    try {
      setLoading(true);

      const res = await fetch(`${API_BASE}/balance`);
      const data = await res.json();

      setBalance(data.balance ?? 0);
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
        {loading
          ? 'Loading...'
          : balance}
      </h2>
    </div>
  );
}