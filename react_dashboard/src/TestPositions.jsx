import { useState, useEffect } from 'react';

export default function TestPositions() {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);

  // データ取得 + 自動更新（10秒ごと）
  useEffect(() => {
    const fetchPositions = () => {
      fetch('http://localhost:8000/positions')
        .then(res => res.json())
        .then(data => {
          setPositions(data);
          setLoading(false);
        })
        .catch(err => {
          console.error('Positions fetch error:', err);
          setLoading(false);
        });
    };

    fetchPositions();
    const interval = setInterval(fetchPositions, 10000); // 10秒ごと更新

    return () => clearInterval(interval);
  }, []);

  if (loading) return <div>Loading Positions...</div>;

  return (
    <div>
      <h2>Positions</h2>
      <table>
        <thead>
          <tr>
            <th>Pair</th>
            <th>Side</th>
            <th>Entry</th>
            <th>Current</th>
            <th>PnL</th>
            <th>Size</th>
          </tr>
        </thead>
        <tbody>
          {positions.map(p => (
            <tr key={p.id}>
              <td>{p.pair}</td>
              <td>{p.side}</td>
              <td>{p.entry}</td>
              <td>{p.current}</td>
              <td>{p.pnl}</td>
              <td>{p.size}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}