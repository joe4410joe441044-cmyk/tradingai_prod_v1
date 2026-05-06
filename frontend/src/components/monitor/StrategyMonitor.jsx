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
    return val.includes("BUY") ? buyColor : sellColor;
  };

  return (
    <div className="bg-gray-900 p-4 rounded-2xl">
      <h2 className="text-lg mb-3">📊 Strategy Monitor</h2>

      <div className="text-sm space-y-1">

        <div>
          OB Imbalance: {imbalance}
        </div>

        <div>
          OB Direction:{" "}
          <span style={{ color: getColor(direction) }}>
            {direction}
          </span>
        </div>

        <div>
          Streak:{" "}
          <span style={{ color: getColor(streak) }}>
            {streak}
          </span>
        </div>

        <div>
          Momentum:{" "}
          <span style={{ color: getColor(momentum) }}>
            {momentum}
          </span>
        </div>

        <div>
          Fake Wall:{" "}
          <span style={{ color: fakeWall ? sellColor : buyColor }}>
            {fakeWall ? "YES" : "NO"}
          </span>
        </div>

        <div>
          Cooldown: {cooldown}
        </div>

        <div className="mt-2 font-bold">
          Signal:{" "}
          <span style={{ color: getColor(signal) }}>
            {signal}
          </span>
        </div>

      </div>
    </div>
  );
}