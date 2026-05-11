export default function StatusPanel({

  balance = 0,
  equity = 0,
  pnl = 0,
  price = 0,

  currentDD = 0,
  lossStreak = 0,

  riskLevel = "LOW",

  killSwitch = false,
  botStatus = "STOPPED",

  position = "NONE",
  entryPrice = null,

  lastSignal = "-",
  lastBlock = "-",

  engineState = "READY",
  connection = "OFFLINE",

}) {

  // =========================
  // FORMAT
  // =========================

  const format = (num) => {

    if (
      num === null ||
      num === undefined
    ) {
      return "-";
    }

    return Number(num).toLocaleString(
      undefined,
      {
        maximumFractionDigits: 4,
      }
    );
  };

  // =========================
  // COLORS
  // =========================

  const statusColor =
    botStatus === "RUNNING"
      ? "#00ff88"
      : "#ff4d4f";

  const connectionColor =
    connection === "CONNECTED"
      ? "#00ff88"
      : "#ff4d4f";

  const engineColor =
    engineState === "READY"
      ? "#00ff88"
      : "#ffaa00";

  const killSwitchColor =
    killSwitch
      ? "#ff4d4f"
      : "#facc15";

  const pnlColor =
    Number(pnl) >= 0
      ? "#00ff88"
      : "#ff4d4f";

  const positionColor =
    position === "BUY"
      ? "#00ff88"
      : position === "SELL"
      ? "#ff4d4f"
      : "#ccc";

  // =========================
  // RISK COLOR
  // =========================

  const riskColor =

    riskLevel === "CRITICAL"
      ? "#ff0000"

      : riskLevel === "HIGH"
      ? "#ff4d4f"

      : riskLevel === "MEDIUM"
      ? "#ffaa00"

      : "#00ff88";

  // =========================
  // UI
  // =========================

  return (

    <div className="panel-section">

      {/* ========================= */}
      {/* TITLE */}
      {/* ========================= */}

      <div className="panel-header">

        <h3>
          🔵 STATUS
        </h3>

      </div>

      {/* ========================= */}
      {/* STATUS CARD */}
      {/* ========================= */}

      <div className="execution-status-card">

        {/* BALANCE */}

        <div className="status-row">

          <span className="label">
            Balance
          </span>

          <span className="value">
            {format(balance)}
          </span>

        </div>

        {/* EQUITY */}

        <div className="status-row">

          <span className="label">
            Equity
          </span>

          <span className="value">
            {format(equity)}
          </span>

        </div>

        {/* PNL */}

        <div className="status-row">

          <span className="label">
            PnL
          </span>

          <span
            className="value"
            style={{
              color: pnlColor,
            }}
          >
            {format(pnl)}
          </span>

        </div>

        {/* PRICE */}

        <div className="status-row">

          <span className="label">
            Price
          </span>

          <span className="value">
            {format(price)}
          </span>

        </div>

        {/* POSITION */}

        <div className="status-row">

          <span className="label">
            Position
          </span>

          <span
            className="value"
            style={{
              color: positionColor,
            }}
          >
            {position?.side || "NONE"}
          </span>

        </div>

        {/* ENTRY PRICE */}

        <div className="status-row">

          <span className="label">
            Entry Price
          </span>

          <span className="value">

            {
              entryPrice
                ? format(entryPrice)
                : "-"
            }

          </span>

        </div>

        {/* CURRENT DD */}

        <div className="status-row">

          <span className="label">
            Current DD
          </span>

          <span className="value">

            {format(currentDD)}%

          </span>

        </div>

        {/* LOSS STREAK */}

        <div className="status-row">

          <span className="label">
            Loss Streak
          </span>

          <span className="value">

            {lossStreak ?? 0}

          </span>

        </div>

        {/* RISK LEVEL */}

        <div className="status-row">

          <span className="label">
            Risk Level
          </span>

          <span
            className="value"
            style={{
              color: riskColor,
            }}
          >

            {riskLevel}

          </span>

        </div>

        {/* LAST SIGNAL */}

        <div className="status-row">

          <span className="label">
            Last Signal
          </span>

          <span className="value">

            {lastSignal || "-"}

          </span>

        </div>

        {/* LAST BLOCK */}

        <div className="status-row">

          <span className="label">
            Last Block
          </span>

          <span className="value">

            {lastBlock || "-"}

          </span>

        </div>

        {/* ENGINE STATE */}

        <div className="status-row">

          <span className="label">
            Engine State
          </span>

          <span
            className="value"
            style={{
              color: engineColor,
            }}
          >

            {engineState || "READY"}

          </span>

        </div>

        {/* KILL SWITCH */}

        <div className="status-row">

          <span className="label">
            Kill Switch
          </span>

          <span
            className="value"
            style={{
              color: killSwitchColor,
            }}
          >

            {
              killSwitch
                ? "ACTIVE"
                : "SAFE"
            }

          </span>

        </div>

        {/* BOT STATUS */}

        <div className="status-row">

          <span className="label">
            Bot Status
          </span>

          <span
            className="value"
            style={{
              color: statusColor,
            }}
          >

            {botStatus}

          </span>

        </div>

        {/* CONNECTION */}

        <div className="status-row">

          <span className="label">
            Connection
          </span>

          <span
            className="value"
            style={{
              color: connectionColor,
            }}
          >

            {connection}

          </span>

        </div>

      </div>

    </div>
  );
}