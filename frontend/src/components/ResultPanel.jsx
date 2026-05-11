export default function ResultPanel({

  price = null,

  balance = null,

  risk_percent = null,

  sl_percent = null,

  tp_percent = null,

  timeExit = null,

}) {

  // =========================
  // SAFE NUMBER
  // =========================

  const safeNum = (
    v
  ) => {

    if (
      v === null ||
      v === undefined
    ) {

      return null;

    }

    const n = Number(v);

    return Number.isFinite(n)
      ? n
      : null;

  };

  // =========================
  // BASE VALUES
  // =========================

  const p =
    safeNum(price);

  const bal =
    safeNum(balance);

  const riskPercent =
    safeNum(risk_percent);

  const slPercent =
    safeNum(sl_percent);

  const tpPercent =
    safeNum(tp_percent);

  // =========================
  // CALCULATIONS
  // =========================

  const risk =

    (
      bal !== null &&
      riskPercent !== null
    )

      ? (
          bal *
          (
            riskPercent / 100
          )
        )

      : null;

  const qty =

    (
      p !== null &&
      p > 0 &&
      risk !== null
    )

      ? (
          risk / p
        )

      : null;

  const tp =

    (
      p !== null &&
      p > 0 &&
      tpPercent !== null
    )

      ? (
          p * (
            1 +
            (
              tpPercent / 100
            )
          )
        )

      : null;

  const sl =

    (
      p !== null &&
      p > 0 &&
      slPercent !== null
    )

      ? (
          p * (
            1 -
            (
              slPercent / 100
            )
          )
        )

      : null;

  const ddAfter =
    slPercent;

  const positionSize =
    risk;

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
      !Number.isFinite(
        Number(num)
      )
    ) {

      return "-";

    }

    return Number(num)
      .toLocaleString(
        undefined,
        {
          minimumFractionDigits: 0,
          maximumFractionDigits:
            digits,
        }
      );

  };

  // =========================
  // VALIDATION
  // =========================

  const isValid =

    (
      p !== null &&
      p > 0 &&
      bal !== null &&
      bal > 0 &&
      risk !== null &&
      risk > 0
    );

  // =========================
  // UI
  // =========================

  return (

    <div className="result-panel">

      {/* HEADER */}

      <div className="panel-header">

        <h3>
          🟡 Result Monitor
        </h3>

        <span
          className={
            isValid
              ? "running"
              : "stopped"
          }

          style={{
            fontWeight: "bold",
            fontSize: "12px",
          }}
        >

          {
            isValid
              ? "VALID"
              : "INVALID"
          }

        </span>

      </div>

      {/* RESULT GRID */}

      <div className="monitor-grid">

        {/* POSITION SIZE */}

        <div className="monitor-item">

          <span>
            Position Size
          </span>

          <strong>

            {
              format(
                positionSize
              )
            } USDT

          </strong>

        </div>

        {/* QTY */}

        <div className="monitor-item">

          <span>
            Qty
          </span>

          <strong>

            {
              format(
                qty,
                6
              )
            }

          </strong>

        </div>

        {/* RISK */}

        <div className="monitor-item">

          <span>
            Risk Amount
          </span>

          <strong>

            {
              format(
                risk
              )
            } USDT

          </strong>

        </div>

        {/* DD */}

        <div className="monitor-item">

          <span>
            DD After Trade
          </span>

          <strong className="warning">

            {
              format(
                ddAfter
              )
            } %

          </strong>

        </div>

        {/* TP */}

        <div className="monitor-item">

          <span>
            TP Price
          </span>

          <strong className="running">

            {
              format(
                tp,
                4
              )
            }

          </strong>

        </div>

        {/* SL */}

        <div className="monitor-item">

          <span>
            SL Price
          </span>

          <strong className="stopped">

            {
              format(
                sl,
                4
              )
            }

          </strong>

        </div>

        {/* TIME EXIT */}

        <div className="monitor-item">

          <span>
            Time Exit
          </span>

          <strong>

            {
              timeExit ??
              "-"
            } sec

          </strong>

        </div>

        {/* STATUS */}

        <div className="monitor-item">

          <span>
            Status
          </span>

          <strong
            className={
              isValid
                ? "running"
                : "stopped"
            }
          >

            {
              isValid
                ? "READY"
                : "INVALID"
            }

          </strong>

        </div>

      </div>

    </div>

  );

}