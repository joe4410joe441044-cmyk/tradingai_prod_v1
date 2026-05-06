export default function SignalLog({ logs = [] }) {

  // 最大表示件数
  const maxLogs = 50;

  const displayLogs =
    logs
      .slice(-maxLogs)
      .reverse();

  return (
    <div className="log-container">

      {displayLogs.length === 0 ? (

        <div className="log-empty">
          No signals yet...
        </div>

      ) : (

        displayLogs.map((log, idx) => (
          <div
            key={idx}
            className="log-row"
          >
            {formatLog(log)}
          </div>
        ))

      )}

    </div>
  );
}

/* ========================= */
/* FORMAT */
/* ========================= */

function formatLog(log) {

  if (typeof log === "string")
    return log;

  const time =
    log.time || "--:--:--";

  const type =
    log.type || "INFO";

  const value =
    log.value ?? "";

  let color = "#ccc";

  if (type.includes("BUY"))
    color = "#00ff88";

  else if (type.includes("SELL"))
    color = "#ff4d4f";

  else if (type.includes("BLOCK"))
    color = "#ffaa00";

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