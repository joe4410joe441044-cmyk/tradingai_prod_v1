export default function PositionsTable({ positions, loading }) {
  if (loading) return <div>Loading...</div>

  if (!positions || positions.length === 0) {
    return <div>No positions</div>
  }

  return (
    <table border="1">
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
  )
}