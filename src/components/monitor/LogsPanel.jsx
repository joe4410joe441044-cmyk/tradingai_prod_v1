export default function LogsPanel({ logs = [], loading, error }) {
  return (
    <div
      style={{
        background: "#111",
        borderRadius: "16px",
        padding: "16px",
        boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
    >
      {/* CONTENT */}
      <div
        style={{
          flex: 1,
          maxHeight: "300px",
          overflowY: "auto",
          background: "#0b0b0b",
          borderRadius: "10px",
          padding: "10px",
          fontSize: "12px",
          fontFamily: "monospace",
        }}
      >
        {loading && <div style={{ opacity: 0.6 }}>Loading...</div>}

        {error && (
          <div style={{ color: "#f87171" }}>
            Fetch error
          </div>
        )}

        {!loading && logs.length === 0 && (
          <div style={{ opacity: 0.5 }}>
            No logs
          </div>
        )}

        {!loading &&
          logs.map((log, i) => (
            <div
              key={i}
              style={{
                padding: "4px 0",
                borderBottom: "1px solid rgba(255,255,255,0.05)",
              }}
            >
              {typeof log === "string"
                ? log
                : JSON.stringify(log)}
            </div>
          ))}
      </div>
    </div>
  );
}