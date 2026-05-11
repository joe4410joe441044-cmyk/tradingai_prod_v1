import { useState, useEffect } from "react";

// =========================
// RISK PANEL
// =========================

export default function RiskPanel({

  onChange,
  result = {},
  risk = {},
  refresh,

}) {

  // =========================
  // LOCAL STATE
  // =========================

  const [maxDD, setMaxDD] = useState(
    risk?.dd_limit || 10
  );

  const [maxLossStreak, setMaxLossStreak] = useState(
    risk?.loss_limit || 3
  );

  const [maxPosition, setMaxPosition] = useState(
    100
  );

  // =========================
  // EFFECT
  // =========================

  useEffect(() => {

    if (!onChange) return;

    onChange({
      maxDD: Number(maxDD),
      maxLossStreak: Number(maxLossStreak),
      maxPosition: Number(maxPosition),
    });

  }, [
    maxDD,
    maxLossStreak,
    maxPosition,
    onChange,
  ]);

  // =========================
  // API
  // =========================

  const updateRisk = async () => {

    try {

      await fetch(
        "/api/risk/update",
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          body: JSON.stringify({
            max_drawdown_pct:
              Number(maxDD),

            max_loss_streak:
              Number(maxLossStreak),
          }),
        }
      );

      refresh && refresh();

    } catch (err) {

      console.error(
        "❌ RISK UPDATE ERROR:",
        err
      );
    }
  };

  const resetRisk = async () => {

    try {

      await fetch(
        "/api/risk/reset",
        {
          method: "POST",
        }
      );

      refresh && refresh();

    } catch (err) {

      console.error(
        "❌ RISK RESET ERROR:",
        err
      );
    }
  };

  // =========================
  // RESULT
  // =========================

  const rawQty =
    Number(result?.qty) || 0;

  const rawSymbol =
    result?.symbol || "";

  const symbol =
    rawSymbol
      .trim()
      .toUpperCase();

  const symbolUnit =
    symbol.replace(
      "USDT",
      ""
    );

  const finalQty = (() => {

    const q =
      Number(result?.qty) || 0;

    const s =
      (result?.symbol || "")
        .toUpperCase();

    if (!q) return "-";

    if (s.includes("XRP")) {
      return Math.floor(q);
    }

    if (
      s.includes("BTC") ||
      s.includes("ETH")
    ) {
      return (
        Math.round(q * 1000) /
        1000
      );
    }

    if (
      s.includes("SOL") ||
      s.includes("BNB")
    ) {
      return (
        Math.round(q * 100) /
        100
      );
    }

    return q;

  })();

  // =========================
  // KILL SWITCH
  // =========================

  const isKill =
    risk?.kill_switch || false;

  // =========================
  // UI
  // =========================

  return (

    <div>

      {/* ========================= */}
      {/* TITLE */}
      {/* ========================= */}

      <div className="panel-header">

        <h3>
          🔴 Risk Settings
        </h3>

      </div>

      {/* ========================= */}
      {/* INPUTS */}
      {/* ========================= */}

      <div className="execution-status-card">

        <div className="status-row">

          <span className="label">
            Max DD %
          </span>

          <input
            value={maxDD}
            onChange={(e) =>
              setMaxDD(
                e.target.value
              )
            }
            style={{
              width: 120,
            }}
          />

        </div>

        <div className="status-row">

          <span className="label">
            Max Loss Streak
          </span>

          <input
            value={maxLossStreak}
            onChange={(e) =>
              setMaxLossStreak(
                e.target.value
              )
            }
            style={{
              width: 120,
            }}
          />

        </div>

        <div className="status-row">

          <span className="label">
            Max Position
          </span>

          <input
            value={maxPosition}
            onChange={(e) =>
              setMaxPosition(
                e.target.value
              )
            }
            style={{
              width: 120,
            }}
          />

        </div>

        {/* ========================= */}
        {/* BUTTONS */}
        {/* ========================= */}

        <div className="execution-buttons">

          <button
            className="start-btn"
            onClick={updateRisk}
          >
            UPDATE
          </button>

          <button
            className="stop-btn"
            onClick={resetRisk}
          >
            RESET
          </button>

        </div>

        {/* ========================= */}
        {/* KILL SWITCH */}
        {/* ========================= */}

        <div className="status-row">

          <span className="label">
            Kill Switch
          </span>

          <span
            className="value"
            style={{
              color: isKill
                ? "#ff4d4f"
                : "#00ff88",
            }}
          >
            {
              isKill
                ? "ACTIVE 🔴"
                : "SAFE 🟢"
            }
          </span>

        </div>

      </div>

      {/* ========================= */}
      {/* RESULT */}
      {/* ========================= */}

      <div
        style={{
          marginTop: 20,
        }}
      >

        <div className="panel-header">

          <h3>
            🟡 Result
          </h3>

        </div>

        <div className="execution-status-card">

          <div className="status-row">

            <span className="label">
              Position Size
            </span>

            <span className="value">
              {
                result?.positionSize
                  ?? "-"
              } USDT
            </span>

          </div>

          <div className="status-row">

            <span className="label">
              Qty
            </span>

            <span className="value">
              {finalQty}
              {" "}
              {symbolUnit}
            </span>

          </div>

          <div className="status-row">

            <span className="label">
              Risk Amount
            </span>

            <span className="value">
              {
                result?.riskAmount
                  ?? "-"
              } USDT
            </span>

          </div>

          <div className="status-row">

            <span className="label">
              DD After Trade
            </span>

            <span className="value">
              {
                result?.ddAfter
                  ?? "-"
              } %
            </span>

          </div>

        </div>

      </div>

    </div>
  );
}