import { useState, useEffect } from 'react';

export default function TestPositions() {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);

  // 郢昴・繝ｻ郢ｧ・ｿ陷ｿ髢・ｾ繝ｻ+ 髢ｾ・ｪ陷榊｢灘ｳｩ隴・ｽｰ
  useEffect(() => {
    const fetchPositions = async () => {
      try {
        const res = await fetch('/api/positions');
        const data = await res.json();

        // 鬩滓ｦ翫・闖ｫ譎・ｽｨ・ｼ繝ｻ莠･・ｮ迚吶・陝・ｽｾ驕ｲ蜴・ｽｼ繝ｻ
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
