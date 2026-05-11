export default function TradeLog({ logs = [] }) {

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
            type: "ENTRY BUY",
            value: "XRPUSDT",
          },
          {
            time: "12:01:06",
            type: "TP HIT",
            value: "+5 USDT",
          },
          {
            time: "12:05:02",
            type: "ENTRY BUY",
            value: "XRPUSDT",
          },
          {
            time: "12:05:05",
            type: "TIME EXIT",
            value: "3 sec",
          },
          {
            time: "12:12:10",
            type: "SL HIT",
            value: "-10 USDT",
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
        📜 Trade Log
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
            No trades yet...
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

              {formatTradeLog(log)}

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

function formatTradeLog(log) {

  // =========================
  // STRING SUPPORT
  // =========================

  if (typeof log === "string") {

    let color = "#ccc";

    if (log.includes("BUY"))
      color = "#00ff99";

    else if (log.includes("SELL"))
      color = "#ff4d4d";

    else if (log.includes("TP"))
      color = "#00e5ff";

    else if (log.includes("SL"))
      color = "#ff9900";

    else if (log.includes("TIME EXIT"))
      color = "#ffaa00";

    return (

      <span
        style={{
          color,
          fontSize: "11px",
        }}
      >
        {log}
      </span>

    );
  }

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
    type.includes("EXIT")
  )
    color = "#ffaa00";

  // =========================
  // PNL COLOR
  // =========================

  let pnlColor = "#ccc";

  if (
    typeof value === "string"
  ) {

    if (
      value.includes("+")
    )
      pnlColor = "#00ff99";

    else if (
      value.includes("-")
    )
      pnlColor = "#ff4d4d";
  }

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
          color: pnlColor,
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {value}
      </span>

    </div>

  );
}