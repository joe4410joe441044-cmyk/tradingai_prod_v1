export default function StrategyMonitor({

  strategyData = {},

}) {

  // =========================
  // SAFE FORMATTERS
  // =========================

  const safeFixed = (
    value,
    digits = 2
  ) => {

    return (
      value !== null &&
      value !== undefined &&
      Number.isFinite(
        Number(value)
      )
    )

      ? Number(value).toFixed(
          digits
        )

      : "-";

  };

  // =========================
  // REALTIME DATA
  // =========================

  const {

    imbalance = null,

    momentum = null,

    spread = null,

    edge = null,

    delta = null,

    cooldown = false,

    entryReady = false,

    signal = null,

    direction = null,

    strategyState = null,

    edgeScore = null,

    executionAllowed = false,

    marketEnvironment = null,

    spoofDanger = false,

    liquidityGrab = false,

    gammaState = null,

    deltaPressure = null,

    momentumRegime = null,

    liquidityStability = null,

    spoofProbability = null,

    breakoutLong = false,

    breakoutShort = false,

    marketMakingWindow = false,

    emergencyExit = false,

  } = strategyData;

  // =========================
  // DERIVED VALUES
  // =========================

  const hasImbalance =

    imbalance !== null &&
    Number.isFinite(
      Number(imbalance)
    );

  const hasMomentum =

    momentum !== null &&
    Number.isFinite(
      Number(momentum)
    );

  const hasEdge =

    edge !== null &&
    Number.isFinite(
      Number(edge)
    );

  const hasDelta =

    delta !== null &&
    Number.isFinite(
      Number(delta)
    );

  const orderFlowDirection =

    hasImbalance

      ? (
          imbalance >= 0
            ? "BUY"
            : "SELL"
        )

      : "-";

  const momentumState =

    hasMomentum

      ? (
          Math.abs(momentum) >= 2
            ? "STRONG"
            : Math.abs(momentum) >= 1
            ? "NORMAL"
            : "WEAK"
        )

      : "-";

  // =========================
  // ENTRY QUALITY SCORE
  // =========================

  const signalStrength =

    (
      hasEdge &&
      hasImbalance &&
      hasMomentum
    )

      ? Math.min(

          100,

          Math.max(

            0,

            Math.round(

              (

                Math.abs(edge) * 0.5 +

                Math.abs(imbalance) * 0.3 +

                Math.abs(momentum / 3) * 0.2

              ) * 100

            )

          )

        )

      : 0;

  // =========================
  // EDGE COLOR
  // =========================

  const edgeColor =

    hasEdge

      ? (
          edge >= 0.7
            ? "#00ff99"
            : edge >= 0.4
            ? "#ffaa00"
            : "#ff4d4d"
        )

      : "#999";

  // =========================
  // SIGNAL COLOR
  // =========================

  const signalColor =

    signal === "ENTER_LONG"
      ? "#00ff99"

      : signal === "ENTER_SHORT"
      ? "#ff4d4d"

      : "#999";

  // =========================
  // STRATEGY STATE COLOR
  // =========================

  const strategyStateColor =

    strategyState ===
    "BULLISH_ATTACK"

      ? "#00ff99"

      : strategyState ===
        "BEARISH_ATTACK"

      ? "#ff4d4d"

      : strategyState ===
        "SURVIVAL"

      ? "#ffaa00"

      : "#999";

  // =========================
  // SPOOF STATUS
  // =========================

  const spoofStatus =

    spoofDanger

      ? "DANGER"

      : (
          spoofProbability !== null &&
          spoofProbability >= 40
        )

      ? "WARNING"

      : "SAFE";

  // =========================
  // UI
  // =========================

  return (

    <div
      className="execution-status-card"
      style={{
        gap: "10px",
      }}
    >

      {/* HEADER */}

      <div
        style={{
          display: "flex",
          justifyContent:
            "space-between",
          alignItems: "center",
        }}
      >

        <h3
          style={{
            margin: 0,
            fontSize: "14px",
          }}
        >
          📊 Strategy Monitor
        </h3>

        <span
          style={{
            fontSize: "11px",
            color: "#666",
            letterSpacing: "0.5px",
          }}
        >
          MICROSTRUCTURE EDGE
        </span>

      </div>

      {/* GRID */}

      <div
        className="monitor-grid"
        style={{
          gap: "8px",
        }}
      >

        {/* ORDER FLOW */}

        <div className="monitor-item">

          <span>
            ORDER FLOW
          </span>

          <strong
            className={
              orderFlowDirection ===
              "BUY"

                ? "long"

                : "short"
            }
          >

            {orderFlowDirection}

          </strong>

        </div>

        {/* IMBALANCE */}

        <div className="monitor-item">

          <span>
            IMBALANCE
          </span>

          <strong>

            {safeFixed(
              imbalance,
              2
            )}

          </strong>

        </div>

        {/* MOMENTUM */}

        <div className="monitor-item">

          <span>
            MOMENTUM
          </span>

          <strong
            className={
              momentumState ===
              "STRONG"

                ? "online"

                : momentumState ===
                  "WEAK"

                ? "warning"

                : ""
            }
          >

            {momentumState}

          </strong>

        </div>

        {/* DELTA */}

        <div className="monitor-item">

          <span>
            DELTA
          </span>

          <strong
            className={
              hasDelta &&
              delta >= 0

                ? "long"

                : "short"
            }
          >

            {safeFixed(
              delta,
              2
            )}

          </strong>

        </div>

        {/* SPREAD */}

        <div className="monitor-item">

          <span>
            SPREAD
          </span>

          <strong>

            {safeFixed(
              spread,
              4
            )}

          </strong>

        </div>

        {/* EDGE */}

        <div className="monitor-item">

          <span>
            EDGE
          </span>

          <strong
            style={{
              color: edgeColor,
            }}
          >

            {safeFixed(
              edge,
              2
            )}

          </strong>

        </div>

        {/* COOLDOWN */}

        <div className="monitor-item">

          <span>
            COOLDOWN
          </span>

          <strong
            className={
              cooldown
                ? "danger"
                : "online"
            }
          >

            {cooldown
              ? "ON"
              : "OFF"}

          </strong>

        </div>

        {/* ENTRY READY */}

        <div className="monitor-item">

          <span>
            ENTRY READY
          </span>

          <strong
            className={
              entryReady
                ? "online"
                : "offline"
            }
          >

            {entryReady
              ? "YES"
              : "NO"}

          </strong>

        </div>

        {/* SIGNAL */}

        <div className="monitor-item">

          <span>
            SIGNAL
          </span>

          <strong
            style={{
              color: signalColor,
            }}
          >

            {signal ?? "-"}

          </strong>

        </div>

        {/* DIRECTION */}

        <div className="monitor-item">

          <span>
            DIRECTION
          </span>

          <strong
            className={
              direction === "LONG"
                ? "long"
                : direction === "SHORT"
                ? "short"
                : ""
            }
          >

            {direction ?? "-"}

          </strong>

        </div>

        {/* STRATEGY STATE */}

        <div className="monitor-item">

          <span>
            STATE
          </span>

          <strong
            style={{
              color:
                strategyStateColor,
            }}
          >

            {strategyState ?? "-"}

          </strong>

        </div>

        {/* EDGE SCORE */}

        <div className="monitor-item">

          <span>
            EDGE SCORE
          </span>

          <strong>

            {edgeScore ?? "-"}

          </strong>

        </div>

        {/* EXECUTION */}

        <div className="monitor-item">

          <span>
            EXECUTION
          </span>

          <strong
            className={
              executionAllowed
                ? "online"
                : "danger"
            }
          >

            {executionAllowed
              ? "ALLOWED"
              : "BLOCKED"}

          </strong>

        </div>

        {/* MARKET ENVIRONMENT */}

        <div className="monitor-item">

          <span>
            ENVIRONMENT
          </span>

          <strong>

            {marketEnvironment ??
              "-"}

          </strong>

        </div>

        {/* SPOOF STATUS */}

        <div className="monitor-item">

          <span>
            SPOOF
          </span>

          <strong
            className={
              spoofDanger
                ? "danger"
                : spoofStatus ===
                  "WARNING"
                ? "warning"
                : "online"
            }
          >

            {spoofStatus}

          </strong>

        </div>

        {/* LIQUIDITY GRAB */}

        <div className="monitor-item">

          <span>
            LIQ GRAB
          </span>

          <strong
            className={
              liquidityGrab
                ? "warning"
                : "online"
            }
          >

            {liquidityGrab
              ? "DETECTED"
              : "CLEAR"}

          </strong>

        </div>

        {/* GAMMA */}

        <div className="monitor-item">

          <span>
            GAMMA
          </span>

          <strong>

            {gammaState ?? "-"}

          </strong>

        </div>

        {/* DELTA PRESSURE */}

        <div className="monitor-item">

          <span>
            DELTA PRESSURE
          </span>

          <strong>

            {deltaPressure ?? "-"}

          </strong>

        </div>

        {/* MOMENTUM REGIME */}

        <div className="monitor-item">

          <span>
            MOMENTUM REGIME
          </span>

          <strong>

            {momentumRegime ??
              "-"}

          </strong>

        </div>

        {/* LIQUIDITY */}

        <div className="monitor-item">

          <span>
            LIQUIDITY
          </span>

          <strong>

            {liquidityStability ??
              "-"}

          </strong>

        </div>

        {/* BREAKOUT */}

        <div className="monitor-item">

          <span>
            BREAKOUT
          </span>

          <strong
            className={
              breakoutLong
                ? "long"
                : breakoutShort
                ? "short"
                : ""
            }
          >

            {breakoutLong
              ? "LONG"
              : breakoutShort
              ? "SHORT"
              : "NONE"}

          </strong>

        </div>

        {/* MARKET MAKING */}

        <div className="monitor-item">

          <span>
            MARKET MAKER
          </span>

          <strong
            className={
              marketMakingWindow
                ? "online"
                : "offline"
            }
          >

            {marketMakingWindow
              ? "ACTIVE"
              : "OFF"}

          </strong>

        </div>

        {/* EMERGENCY EXIT */}

        <div className="monitor-item">

          <span>
            EMERGENCY EXIT
          </span>

          <strong
            className={
              emergencyExit
                ? "danger"
                : "online"
            }
          >

            {emergencyExit
              ? "TRIGGERED"
              : "SAFE"}

          </strong>

        </div>

      </div>

      {/* ENTRY QUALITY SCORE */}

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "6px",
          marginTop: "2px",
        }}
      >

        <div
          style={{
            display: "flex",
            justifyContent:
              "space-between",

            fontSize: "11px",
            color: "#888",
          }}
        >

          <span>
            ENTRY QUALITY SCORE
          </span>

          <span
            style={{
              color: edgeColor,
              fontWeight: "600",
            }}
          >
            {signalStrength}%
          </span>

        </div>

        {/* BAR */}

        <div
          style={{
            width: "100%",
            height: "8px",

            background: "#111",

            borderRadius: "999px",

            overflow: "hidden",

            border:
              "1px solid #222",
          }}
        >

          <div
            style={{
              width:
                `${signalStrength}%`,

              height: "100%",

              background:
                edgeColor,

              transition: "0.25s",
            }}
          />

        </div>

      </div>

    </div>

  );

}