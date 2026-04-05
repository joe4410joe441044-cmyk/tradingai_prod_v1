export default function LogsPanel({ logs }) {
  return (
    <div>
      <h3>Logs</h3>
      <div style={{ maxHeight: "300px", overflowY: "scroll" }}>
        {logs.map((log) => (
          <div key={log.id}>
            [{log.time}] {log.type} - {log.message}
          </div>
        ))}
      </div>
    </div>
  );
}