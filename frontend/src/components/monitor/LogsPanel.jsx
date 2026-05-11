import SignalLog from "../SignalLog";
import TradeLog from "../TradeLog";

export default function LogsPanel({

  signalLogs = [],
  tradeLogs = [],

  routerTelemetry = {},
  executionRoute = "NONE",
  routerReason = "NONE",

  loading,
  error,

}) {

  const telemetry = {

    route:
      routerTelemetry?.route ||
      executionRoute ||
      "NONE",

    reason:
      routerTelemetry?.reason ||
      routerReason ||
      "NONE",

    mode:
      routerTelemetry?.mode ||
      "SAFE",

    priority:
      routerTelemetry?.priority ||
      "NORMAL",

    allowed:
      routerTelemetry?.allowed ||
      false,

    survivability:
      routerTelemetry?.survivability ||
      0,

  };

  return (

    <div
      style={{
        background: "#111",
        borderRadius: "16px",
        padding: "12px",
        boxShadow: "0 6px 20px rgba(0,0,0,0.3)",

        display: "flex",
        flexDirection: "column",
        gap: "12px",

        height: "100%",
      }}
    >

      {/* LOADING */}

      {loading && (

        <div
          style={{
            opacity: 0.6,
            fontSize: "11px",
          }}
        >
          Loading...
        </div>

      )}

      {/* ERROR */}

      {error && (

        <div
          style={{
            color: "#f87171",
            fontSize: "11px",
          }}
        >
          Fetch error
        </div>

      )}

      {/* LOG CONTENT */}

      {!loading && !error && (

        <>

          {/* EXECUTION TELEMETRY */}

          <div
            style={{
              background: "#0b0b0b",
              borderRadius: "10px",

              padding: "8px",

              border: "1px solid #1a1a1a",

              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >

            <div
              style={{
                fontSize: "11px",
                fontWeight: "600",
                color: "#888",
                letterSpacing: "0.5px",
              }}
            >
              EXECUTION TELEMETRY
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "6px",
                fontSize: "11px",
                fontFamily: "monospace",
              }}
            >

              <div
                style={{
                  color: "#00ff88",
                }}
              >
                ROUTE: {telemetry.route}
              </div>

              <div
                style={{
                  color: telemetry.allowed
                    ? "#00ff88"
                    : "#ff4d4f",
                }}
              >
                {
                  telemetry.allowed
                    ? "GATE: PASS"
                    : "GATE: BLOCK"
                }
              </div>

              <div
                style={{
                  color: "#ffaa00",
                }}
              >
                MODE: {telemetry.mode}
              </div>

              <div
                style={{
                  color: "#00d4ff",
                }}
              >
                PRIORITY: {telemetry.priority}
              </div>

              <div
                style={{
                  color: "#ff8800",
                }}
              >
                SURV: {
                  Math.round(
                    telemetry.survivability || 0
                  )
                }
              </div>

              <div
                style={{
                  color: "#cccccc",
                }}
              >
                REASON: {telemetry.reason}
              </div>

            </div>

          </div>

          {/* SIGNAL LOG */}

          <div
            style={{
              flex: 1,
              background: "#0b0b0b",
              borderRadius: "10px",

              padding: "6px",

              overflowY: "auto",
              overflowX: "hidden",

              maxHeight: "300px",

              border: "1px solid #1a1a1a",

              display: "flex",
              flexDirection: "column",
              gap: "4px",
            }}
          >

            <div
              style={{
                fontSize: "11px",
                fontWeight: "600",
                color: "#888",
                marginBottom: "4px",
                letterSpacing: "0.5px",
              }}
            >
              SIGNAL LOG
            </div>

            {/* =========================
                INTELLIGENCE LOGS
            ========================= */}

            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "4px",
              }}
            >

              {signalLogs.map((log, index) => (

                <div
                  key={index}

                  className="log-row"

                  style={{

                    borderColor:

                      log.type === "NO TRADE" ||
                      log.type === "SPOOF"

                        ? "#ff4d4f"

                        : log.type === "BURST"

                        ? "#ffaa00"

                        : log.type === "EXECUTION"

                        ? "#ff8800"

                        : "#242424",

                    background:

                      log.type === "NO TRADE" ||
                      log.type === "SPOOF"

                        ? "rgba(255,77,79,0.08)"

                        : log.type === "BURST"

                        ? "rgba(255,170,0,0.08)"

                        : log.type === "EXECUTION"

                        ? "rgba(255,136,0,0.08)"

                        : "#181818",

                    border: "1px solid",

                    borderRadius: "8px",

                    padding: "8px",

                    fontSize: "11px",

                    fontFamily: "monospace",

                  }}
                >

                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      marginBottom: "3px",
                    }}
                  >

                    <span
                      style={{
                        color: "#888",
                      }}
                    >
                      {log.time}
                    </span>

                    <span
                      style={{
                        fontWeight: "700",
                        color:

                          log.type === "NO TRADE" ||
                          log.type === "SPOOF"

                            ? "#ff4d4f"

                            : log.type === "BURST"

                            ? "#ffaa00"

                            : log.type === "EXECUTION"

                            ? "#ff8800"

                            : "#00ff88",
                      }}
                    >
                      {log.type}
                    </span>

                  </div>

                  <div
                    style={{
                      color: "#ddd",
                    }}
                  >
                    {log.value}
                  </div>

                </div>

              ))}

            </div>

          </div>

          {/* TRADE LOG */}

          <div
            style={{
              flex: 1,
              background: "#0b0b0b",
              borderRadius: "10px",

              padding: "6px",

              overflowY: "auto",
              overflowX: "hidden",

              maxHeight: "300px",

              border: "1px solid #1a1a1a",

              display: "flex",
              flexDirection: "column",
              gap: "4px",
            }}
          >

            <div
              style={{
                fontSize: "11px",
                fontWeight: "600",
                color: "#888",
                marginBottom: "4px",
                letterSpacing: "0.5px",
              }}
            >
              TRADE LOG
            </div>

            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "4px",
              }}
            >

              {tradeLogs.map((log, index) => (

                <div
                  key={index}
                  style={{
                    background: "#181818",
                    border: "1px solid #242424",
                    borderRadius: "8px",
                    padding: "8px",
                    fontSize: "11px",
                    fontFamily: "monospace",

                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                  }}
                >

                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                    }}
                  >

                    <span
                      style={{
                        color: "#888",
                      }}
                    >
                      {log.timestamp}
                    </span>

                    <span
                      style={{
                        color: "#00ff88",
                        fontWeight: "700",
                      }}
                    >
                      {log.action}
                    </span>

                  </div>

                  <div
                    style={{
                      color: "#ddd",
                    }}
                  >
                    SYMBOL: {log.symbol}
                  </div>

                  <div
                    style={{
                      color:
                        Number(log.pnl) >= 0
                          ? "#00ff88"
                          : "#ff4d4f",
                    }}
                  >
                    PNL: {log.pnl}
                  </div>

                  <div
                    style={{
                      color: "#00d4ff",
                    }}
                  >
                    [ROUTER] {
                      log.executionRoute ||
                      "NONE"
                    }
                  </div>

                  <div
                    style={{
                      color: "#ffaa00",
                    }}
                  >
                    [GATE] {
                      log.routerReason ||
                      "NONE"
                    }
                  </div>

                  <div
                    style={{
                      color: "#00ff88",
                    }}
                  >
                    [MODE] {
                      log.executionMode ||
                      "SAFE"
                    }
                  </div>

                  <div
                    style={{
                      color: "#ff8800",
                    }}
                  >
                    [SURV] {
                      Math.round(
                        log.survivabilityScore || 0
                      )
                    }
                  </div>

                </div>

              ))}

            </div>

          </div>

        </>

      )}

    </div>

  );
}