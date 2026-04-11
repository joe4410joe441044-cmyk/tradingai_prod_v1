export default function LogsPanel({ logs }) {
  return (
    <div>
      <h3>Logs</h3>

      <div style={{ maxHeight: "300px", overflowY: "scroll" }}>
        {Array.isArray(logs) && logs.length > 0 ? (
          logs.map((log, index) => (
            <div key={log.id ?? index}>
              [{log.time ?? "-"}] {log.type ?? "INFO"} - {log.message ?? ""}
            </div>
          ))
        ) : (
          <p>No logs</p>
        )}
      </div>
    </div>
  );
}