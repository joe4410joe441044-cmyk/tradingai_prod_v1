export default function DerivedIntelligencePanel({

  derivedIntel,

}) {

  // =========================
  // SAFE FALLBACK
  // =========================

  const intel = derivedIntel || {

    marketDanger: "LOW",

    entryQuality: 0,

    executionQuality: 0,

    marketStability: 0,

    trendAggression: 0,

    noTradeZone: false,

    momentumBurst: false,

    executionAnomaly: false,

    unstableMarket: false,

    spoofDanger: false,

  };

  // =========================
  // COLORS
  // =========================

  const dangerColor =

    intel.marketDanger === "HIGH"
      ? "#ff0000"

      : intel.marketDanger === "MEDIUM"
      ? "#ffaa00"

      : "#00ff88";

  const entryColor =

    intel.entryQuality >= 80
      ? "#00ff88"

      : intel.entryQuality >= 50
      ? "#ffaa00"

      : "#ff4d4f";

  const executionColor =

    intel.executionQuality >= 80
      ? "#00ff88"

      : intel.executionQuality >= 50
      ? "#ffaa00"

      : "#ff4d4f";

  const stabilityColor =

    intel.marketStability >= 80
      ? "#00ff88"

      : intel.marketStability >= 50
      ? "#ffaa00"

      : "#ff4d4f";

  // =========================
  // UI
  // =========================

  return (

    <div className="panel-section">

      {/* HEADER */}

      <div className="panel-header">

        <h3>
          🧠 Derived Intelligence
        </h3>

      </div>

      {/* MAIN CARD */}

      <div className="execution-status-card">

        {/* MARKET DANGER */}

        <div className="status-row">

          <span className="label">
            Market Danger
          </span>

          <span
            className="value"
            style={{
              color:
                dangerColor,
            }}
          >

            {
              intel.marketDanger
            }

          </span>

        </div>

        {/* ENTRY QUALITY */}

        <div className="status-row">

          <span className="label">
            Entry Quality
          </span>

          <span
            className="value"
            style={{
              color:
                entryColor,
            }}
          >

            {
              Math.round(
                intel.entryQuality
              )
            }

          </span>

        </div>

        {/* EXECUTION QUALITY */}

        <div className="status-row">

          <span className="label">
            Execution Quality
          </span>

          <span
            className="value"
            style={{
              color:
                executionColor,
            }}
          >

            {
              Math.round(
                intel.executionQuality
              )
            }

          </span>

        </div>

        {/* MARKET STABILITY */}

        <div className="status-row">

          <span className="label">
            Market Stability
          </span>

          <span
            className="value"
            style={{
              color:
                stabilityColor,
            }}
          >

            {
              Math.round(
                intel.marketStability
              )
            }

          </span>

        </div>

        {/* TREND AGGRESSION */}

        <div className="status-row">

          <span className="label">
            Trend Aggression
          </span>

          <span className="value warning">

            {
              Math.round(
                intel.trendAggression
              )
            }

          </span>

        </div>

      </div>

      {/* =========================
          INTELLIGENCE GRID
      ========================= */}

      <div
        className="monitor-grid"
        style={{
          marginTop: "10px",
        }}
      >

        {/* NO TRADE */}

        <div className="monitor-item">

          <span>
            NO TRADE
          </span>

          <strong
            style={{
              color:
                intel.noTradeZone
                  ? "#ff4d4f"
                  : "#00ff88",
            }}
          >

            {
              intel.noTradeZone
                ? "ACTIVE"
                : "CLEAR"
            }

          </strong>

        </div>

        {/* MOMENTUM */}

        <div className="monitor-item">

          <span>
            MOMENTUM
          </span>

          <strong
            style={{
              color:
                intel.momentumBurst
                  ? "#ffaa00"
                  : "#00ff88",
            }}
          >

            {
              intel.momentumBurst
                ? "BURST"
                : "NORMAL"
            }

          </strong>

        </div>

        {/* EXECUTION */}

        <div className="monitor-item">

          <span>
            EXECUTION
          </span>

          <strong
            style={{
              color:
                intel.executionAnomaly
                  ? "#ff4d4f"
                  : "#00ff88",
            }}
          >

            {
              intel.executionAnomaly
                ? "ANOMALY"
                : "STABLE"
            }

          </strong>

        </div>

        {/* MARKET */}

        <div className="monitor-item">

          <span>
            MARKET
          </span>

          <strong
            style={{
              color:
                intel.unstableMarket
                  ? "#ff4d4f"
                  : "#00ff88",
            }}
          >

            {
              intel.unstableMarket
                ? "UNSTABLE"
                : "STABLE"
            }

          </strong>

        </div>

        {/* SPOOF */}

        <div className="monitor-item">

          <span>
            SPOOF
          </span>

          <strong
            style={{
              color:
                intel.spoofDanger
                  ? "#ff4d4f"
                  : "#00ff88",
            }}
          >

            {
              intel.spoofDanger
                ? "HIGH"
                : "LOW"
            }

          </strong>

        </div>

      </div>

    </div>
  );
}