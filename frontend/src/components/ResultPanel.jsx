export default function ResultPanel({
  price = 0,
  balance = 1000,

  risk_percent = 1,
  sl_percent = 1,
  tp_percent = 1,
  timeExit = 3,
}) {

  // =========================
  // SAFE NUMBER
  // =========================

  const safeNum = (v) => {
    if (isNaN(v) || v === null || v === undefined) {
      return 0;
    }

    return Number(v);
  };

  // =========================
  // BASE VALUES
  // =========================

  const p = safeNum(price);

  const bal = safeNum(balance);

  // =========================
  // CALCULATIONS
  // =========================

  const risk =
    bal * (risk_percent / 100);

  const qty =
    p > 0
      ? risk / p
      : 0;

  const tp =
    p > 0
      ? p * (1 + tp_percent / 100)
      : 0;

  const sl =
    p > 0
      ? p * (1 - sl_percent / 100)
      : 0;

  // =========================
  // FORMAT
  // =========================

  const format = (
    num,
    digits = 2
  ) => {

    if (
      num === null ||
      num === undefined ||
      isNaN(num) ||
      num === Infinity
    ) {
      return "-";
    }

    return Number(num).toLocaleString(
      undefined,
      {
        minimumFractionDigits: 0,
        maximumFractionDigits: digits,
      }
    );
  };

  // =========================
  // VALIDATION
  // =========================

  const isValid =
    p > 0 &&
    bal > 0 &&
    risk > 0;

  // =========================
  // UI
  // =========================

  return (
    <div className="execution-status-card">

      {/* POSITION SIZE */}
      <div className="status-row">
        <span className="label">
          Position Size
        </span>

        <span className="value">
          {format(risk)} USDT
        </span>
      </div>

      {/* QTY */}
      <div className="status-row">
        <span className="label">
          Qty
        </span>

        <span className="value">
          {format(qty, 6)}
        </span>
      </div>

      {/* RISK AMOUNT */}
      <div className="status-row">
        <span className="label">
          Risk Amount
        </span>

        <span className="value">
          {format(risk)} USDT
        </span>
      </div>

      {/* TP PRICE */}
      <div className="status-row">
        <span className="label">
          TP Price
        </span>

        <span className="value">
          {format(tp, 4)}
        </span>
      </div>

      {/* SL PRICE */}
      <div className="status-row">
        <span className="label">
          SL Price
        </span>

        <span className="value">
          {format(sl, 4)}
        </span>
      </div>

      {/* TIME EXIT */}
      <div className="status-row">
        <span className="label">
          Time Exit
        </span>

        <span className="value">
          {timeExit} sec
        </span>
      </div>

      {/* STATUS */}
      <div className="status-row">
        <span className="label">
          Status
        </span>

        <span
          className="value"
          style={{
            color: isValid
              ? "#00ff88"
              : "#ff4d4f",

            fontWeight: "bold",
          }}
        >
          {isValid
            ? "✅ VALID"
            : "❌ INVALID"}
        </span>
      </div>

    </div>
  );
}