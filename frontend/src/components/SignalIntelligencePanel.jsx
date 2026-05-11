export default function SignalIntelligencePanel({

  signalIntel,

}) {

  // =========================
  // SAFE FALLBACK
  // =========================

  const intel = signalIntel || {

    fakeWall: false,

    liquidityGrab: false,

    spoofProbability: 0,

    absorption: false,

    spreadExplosion: false,

    confidenceScore: 0,

  };

  // =========================
  // COLORS
  // =========================

  const spoofColor =

    intel.spoofProbability >= 80
      ? "#ff0000"

      : intel.spoofProbability >= 50
      ? "#ffaa00"

      : "#00ff88";

  const confidenceColor =

    intel.confidenceScore >= 80
      ? "#00ff88"

      : intel.confidenceScore >= 50
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
          🧠 Signal Intelligence
        </h3>

      </div>

      {/* CARD */}

      <div className="execution-status-card">

        {/* FAKE WALL */}

        <div className="status-row">

          <span className="label">
            Fake Wall
          </span>

          <span
            className="value"
            style={{
              color:
                intel.fakeWall
                  ? "#ff4d4f"
                  : "#00ff88",
            }}
          >

            {
              intel.fakeWall
                ? "DETECTED"
                : "CLEAR"
            }

          </span>

        </div>

        {/* LIQUIDITY GRAB */}

        <div className="status-row">

          <span className="label">
            Liquidity Grab
          </span>

          <span
            className="value"
            style={{
              color:
                intel.liquidityGrab
                  ? "#ffaa00"
                  : "#00ff88",
            }}
          >

            {
              intel.liquidityGrab
                ? "ACTIVE"
                : "NORMAL"
            }

          </span>

        </div>

        {/* SPOOF PROBABILITY */}

        <div className="status-row">

          <span className="label">
            Spoof Probability
          </span>

          <span
            className="value"
            style={{
              color: spoofColor,
            }}
          >

            {
              intel.spoofProbability
            }%

          </span>

        </div>

        {/* ABSORPTION */}

        <div className="status-row">

          <span className="label">
            Absorption
          </span>

          <span
            className="value"
            style={{
              color:
                intel.absorption
                  ? "#00ff88"
                  : "#ccc",
            }}
          >

            {
              intel.absorption
                ? "ACTIVE"
                : "NONE"
            }

          </span>

        </div>

        {/* SPREAD EXPLOSION */}

        <div className="status-row">

          <span className="label">
            Spread Explosion
          </span>

          <span
            className="value"
            style={{
              color:
                intel.spreadExplosion
                  ? "#ff4d4f"
                  : "#00ff88",
            }}
          >

            {
              intel.spreadExplosion
                ? "HIGH"
                : "NORMAL"
            }

          </span>

        </div>

        {/* CONFIDENCE */}

        <div className="status-row">

          <span className="label">
            Confidence Score
          </span>

          <span
            className="value"
            style={{
              color:
                confidenceColor,
            }}
          >

            {
              intel.confidenceScore
            }

          </span>

        </div>

      </div>

    </div>
  );
}