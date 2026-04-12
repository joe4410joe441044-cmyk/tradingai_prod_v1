// src/components/LogsPanel.jsx

export default function LogsPanel({ logs }) {
  // logsの型ゆれ対策（壊れ防止）
  const safeLogs = Array.isArray(logs)
    ? logs
    : typeof logs === "string"
    ? [{ message: logs }]
    : [];

  return (
    <div>
      <h3>Logs</h3>

      <div style={{ maxHeight: "300px", overflowY: "auto" }}>
        {safeLogs.length > 0 ? (
          safeLogs.map((log, index) => (
            <div
              key={log.id ?? index}
              style={{
                fontSize: "12px",
                padding: "2px 0",
                borderBottom: "1px solid #eee",
              }}
            >
              [{log.time ?? "-"}] {log.type ?? "INFO"} -{" "}
              {log.message ?? log}
            </div>
          ))
        ) : (
          <p>No logs</p>
        )}
      </div>
    </div>
  );
}