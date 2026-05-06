export default function StrategyMonitor({
  imbalance = 0.18,
  direction = "BUY",
  streak = "BUY x3",
  momentum = "BUY x2",
  fakeWall = false,
  cooldown = "1.2s",
  signal = "BUY",
}) {

  const buyColor = "#00ff88";
  const sellColor = "#ff4d4f";

  const getColor = (val) => {
    if (!val) return "#aaa";

    return val.includes("BUY")
      ? buyColor
      : sellColor;
  };

  return (
    <div className="execution-status-card">

      <div className="status-row">
        <span className="label">
          OB Imbalance
        </span>

        <span className="value">
          {imbalance}
        </span>
      </div>

      <div className="status-row">
        <span className="label">
          OB Direction
        </span>

        <span
          className="value"
          style={{ color: getColor(direction) }}
        >
          {direction}
        </span>
      </div>

      <div className="status-row">
        <span className="label">
          Streak
        </span>

        <span
          className="value"
          style={{ color: getColor(streak) }}
        >
          {streak}
        </span>
      </div>

      <div className="status-row">
        <span className="label">
          Momentum
        </span>

        <span
          className="value"
          style={{ color: getColor(momentum) }}
        >
          {momentum}
        </span>
      </div>

      <div className="status-row">
        <span className="label">
          Fake Wall
        </span>

        <span
          className="value"
          style={{
            color: fakeWall
              ? sellColor
              : buyColor,
          }}
        >
          {fakeWall ? "YES" : "NO"}
        </span>
      </div>

      <div className="status-row">
        <span className="label">
          Cooldown
        </span>

        <span className="value">
          {cooldown}
        </span>
      </div>

      <div className="status-row">
        <span className="label">
          Signal
        </span>

        <span
          className="value"
          style={{ color: getColor(signal) }}
        >
          {signal}
        </span>
      </div>

    </div>
  );
}