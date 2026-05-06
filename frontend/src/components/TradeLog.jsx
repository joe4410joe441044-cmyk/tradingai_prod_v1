export default function TradeLog() {

  const logs = [
    "[12:01] ENTRY BUY XRPUSDT",
    "[12:01] TP +5 USDT",
    "[12:05] ENTRY BUY XRPUSDT",
    "[12:05] TIME EXIT",
    "[12:12] SL -10 USDT",
  ];

  return (
    <div className="log-container">

      {logs.length === 0 ? (

        <div className="log-empty">
          No trades yet...
        </div>

      ) : (

        logs.map((log, idx) => (

          <div
            key={idx}
            className="log-row"
          >
            {formatTradeLog(log)}
          </div>

        ))

      )}

    </div>
  );
}

/* ========================= */
/* FORMAT */
/* ========================= */

function formatTradeLog(log) {

  let color = "#ccc";

  if (log.includes("BUY"))
    color = "#00ff88";

  else if (log.includes("SELL"))
    color = "#ff4d4f";

  else if (log.includes("TP"))
    color = "#00ff88";

  else if (log.includes("SL"))
    color = "#ff4d4f";

  else if (log.includes("TIME EXIT"))
    color = "#ffaa00";

  return (
    <span style={{ color }}>
      {log}
    </span>
  );
}