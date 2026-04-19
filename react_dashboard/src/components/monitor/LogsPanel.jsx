export default function LogsPanel({ logs = [], loading, error }) {
  return (
    <div style={{ padding: "10px", border: "1px solid #444" }}>

      <h3>Logs</h3>

      {loading && <p>Loading...</p>}

      {error && (
        <p style={{ color: "red" }}>
          Fetch error
        </p>
      )}

      {!loading && logs.length === 0 ? (
        <p>No logs</p>
      ) : (
        <ul style={{ maxHeight: "300px", overflowY: "auto" }}>
          {logs.map((log, i) => (
            <li key={i}>
              {typeof log === "string"
                ? log
                : JSON.stringify(log)}
            </li>
          ))}
        </ul>
      )}

    </div>
  );
}