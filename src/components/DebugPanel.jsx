export default function DebugPanel({ data }) {
  if (!data) return null;

  return (
    <div style={{ marginTop: 20 }}>
      <h2>FULL DATA</h2>
      <pre
        style={{
          background: "#111",
          color: "#0f0",
          padding: 10,
          fontSize: 12,
          overflow: "auto",
          maxHeight: 400,
        }}
      >
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}