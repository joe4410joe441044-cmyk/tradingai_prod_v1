export default function AITimeline({ events }) {
  return (
    <div style={{ padding: 20 }}>
      <h2>AI Timeline</h2>

      {events.map((e, i) => (
        <div
          key={i}
          style={{
            border: "1px solid #333",
            marginBottom: 10,
            padding: 10,
            borderRadius: 8,
          }}
        >
          <div><b>Stage:</b> {e.stage}</div>
          <div><b>Symbol:</b> {e.symbol}</div>
          <div><b>Action:</b> {e.action}</div>
          <div><b>Reason:</b> {e.reason}</div>
          <div><b>Confidence:</b> {e.confidence}</div>
        </div>
      ))}
    </div>
  );
}