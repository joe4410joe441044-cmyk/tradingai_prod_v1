export default function SignalLog({ logs = [] }) {

  // =========================
  // MAX LOGS
  // =========================

  const maxLogs = 50;

  // =========================
  // DISPLAY LOGS
  // =========================

  const displayLogs =
    logs.length > 0
      ? logs.slice(0, maxLogs)
      : [
          {
            time: "12:01:04",
            type: "BUY SIGNAL",
            value: "Momentum detected",
          },
          {
            time: "12:01:06",
            type: "IMBALANCE",
            value: "0.62 confirmed",
          },
          {
            time: "12:01:08",
            type: "ENTRY VALID",
            value: "Cooldown OFF",
          },
          {
            time: "12:01:10",
            type: "BLOCK",
            value: "Fake wall detected",
          },
        ];

  // =========================
  // UI
  // =========================

  return (

    <div
      className="panel-section"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "4px",
      }}
    >

      <h3
        style={{
          margin: 0,
          fontSize: "11px",
          color: "#888",
          letterSpacing: "0.5px",
        }}
      >
        📊 Signal Log
      </h3>

      <div
        className="log-container"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "3px",
        }}
      >

        {displayLogs.length === 0 ? (

          <div
            className="log-empty"
            style={{
              fontSize: "11px",
              opacity: 0.5,
            }}
          >
            No signals yet...
          </div>

        ) : (

          displayLogs.map((log, idx) => (

            <div
              key={idx}
              className="log-row"
              style={{
                fontSize: "11px",
                padding: "4px 6px",
                lineHeight: 1.2,

                background: "#101010",
                borderRadius: "6px",

                border: "1px solid #1a1a1a",

                transition: "0.2s",
                cursor: "default",

                display: "flex",
                alignItems: "center",

                wordBreak: "break-word",
              }}

              onMouseEnter={(e) => {
                e.currentTarget.style.background = "#151515";
              }}

              onMouseLeave={(e) => {
                e.currentTarget.style.background = "#101010";
              }}
            >

              {formatLog(log)}

            </div>

          ))

        )}

      </div>

    </div>
  );
}

/* ========================= */
/* FORMAT */
/* ========================= */

function formatLog(log) {

  if (typeof log === "string")
    return log;

  // =========================
  // TIME
  // =========================

  let time = "--:--:--";

  if (log.time) {

    try {

      time = new Date(log.time).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });

    } catch {

      time = log.time;

    }
  }

  // =========================
  // TYPE / VALUE
  // =========================

  const type =
    log.type || "INFO";

  const value =
    log.value ?? "";

  // =========================
  // COLORS
  // =========================

  let color = "#ccc";

  if (type.includes("BUY"))
    color = "#00ff99";

  else if (type.includes("SELL"))
    color = "#ff4d4d";

  else if (
    type.includes("TP")
  )
    color = "#00e5ff";

  else if (
    type.includes("SL")
  )
    color = "#ff9900";

  else if (
    type.includes("BLOCK")
  )
    color = "#ffaa00";

  else if (
    type.includes("VALID")
  )
    color = "#00ccff";

  else if (
    type.includes("IMBALANCE")
  )
    color = "#bb86fc";

  // =========================
  // UI
  // =========================

  return (

    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "6px",
        width: "100%",
      }}
    >

      <span
        style={{
          color: "#666",
          minWidth: "64px",
          fontSize: "10px",
          fontFamily: "monospace",
        }}
      >
        {time}
      </span>

      <span
        style={{
          color,
          fontWeight: "600",
          whiteSpace: "nowrap",
        }}
      >
        {type}
      </span>

      <span
        style={{
          color: "#ccc",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {value}
      </span>

    </div>

  );
}