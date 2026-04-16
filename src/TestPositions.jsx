import { useState, useEffect } from 'react';

export default function TestPositions() {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);

  // 繝・・繧ｿ蜿門ｾ・+ 閾ｪ蜍墓峩譁ｰ
  useEffect(() => {
    const fetchPositions = async () => {
      try {
        const res = await fetch('/api/positions');
        const data = await res.json();

        // 驟榊・菫晁ｨｼ・亥ｮ牙・蟇ｾ遲厄ｼ・
        if (Array.isArray(data)) {
          setPositions(data);
        } else {
          console.error('Positions is not array:', data);
          setPositions([]);
        }

        setLoading(false);
      } catch (err) {
        console.error('Positions fetch error:', err);
        setLoading(false);
      }
    };

    fetchPositions();
    const interval = setInterval(fetchPositions, 10000);

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
          {positions.map((p, i) => (
            <tr key={i}>
              <td>{p.symbol}</td>
              <td>{p.side}</td>
              <td>{p.entry_price}</td>
              <td>{p.mark_price}</td>
              <td>{p.pnl}</td>
              <td>{p.size}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
