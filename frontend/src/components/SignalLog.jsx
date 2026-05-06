export default function SignalLog({ logs = [] }) {

  // 最大表示件数（直近優先）
  const maxLogs = 50;
  const displayLogs = logs.slice(-maxLogs).reverse();

  return (
    <div className="card">
      <h2>📊 Signal Log</h2>

      <div
        style={{
          maxHeight: 200,
          overflowY: "auto",
          fontSize: 12,
          lineHeight: "1.6",
        }}
      >
        {displayLogs.length === 0 ? (
          <div style={{ opacity: 0.5 }}>No signals yet...</div>
        ) : (
          displayLogs.map((log, idx) => (
            <div key={idx} style={{ marginBottom: 2 }}>
              {formatLog(log)}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// =========================
// フォーマット関数
// =========================
function formatLog(log) {
  if (typeof log === "string") return log;

  const time = log.time || "--:--:--";
  const type = log.type || "INFO";
  const value = log.value ?? "";

  let color = "#ccc";

  if (type.includes("BUY")) color = "#00ff88";
  else if (type.includes("SELL")) color = "#ff4d4f";
  else if (type.includes("BLOCK")) color = "#ffaa00";

  return (
    <span>
      [{time}]{" "}
      <span style={{ color }}>
        {type}
      </span>{" "}
      {value}
    </span>
  );
}