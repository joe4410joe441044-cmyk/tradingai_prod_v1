import { useState, useEffect } from "react";

// =========================
// 共通Row
// =========================
function Row({ label, children }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 10
      }}
    >
      <span style={{ width: 140 }}>{label}</span>
      {children}
    </div>
  );
}

// =========================
// Risk Panel（入力 + Result）
// =========================
export default function RiskPanel({ onChange, result }) {

  const [maxDD, setMaxDD] = useState("10");
  const [maxLossStreak, setMaxLossStreak] = useState("3");
  const [maxPosition, setMaxPosition] = useState("100");

  const inputStyle = {
    width: 140,
    padding: 6,
    borderRadius: 6,
    border: "1px solid #444",
    background: "#222",
    color: "#fff"
  };

  useEffect(() => {
    if (!onChange) return;

    onChange({
      maxDD: Number(maxDD),
      maxLossStreak: Number(maxLossStreak),
      maxPosition: Number(maxPosition)
    });

  }, [maxDD, maxLossStreak, maxPosition]);

  // =========================
  // 🔥 型固定
  // =========================
  const rawQty = Number(result?.qty) || 0;
  const rawSymbol = result?.symbol || "";
  const symbol = rawSymbol.trim().toUpperCase();
  const symbolUnit = symbol.replace("USDT", "");

  // =========================
  // 🔥 表示用Qty（最終防御ライン）
  // =========================
  const finalQty = (() => {
    const q = Number(result?.qty) || 0;
    const s = (result?.symbol || "").toUpperCase();

    if (!q) return "-";

    // 🔥 XRPは強制整数（絶対）
    if (s.includes("XRP")) return Math.floor(q);

    // 🔥 その他
    if (s.includes("BTC")) return Math.round(q * 1000) / 1000;
    if (s.includes("ETH")) return Math.round(q * 1000) / 1000;
    if (s.includes("SOL")) return Math.round(q * 100) / 100;
    if (s.includes("BNB")) return Math.round(q * 100) / 100;

    return q;
  })();

  // =========================
  // 🔥 デバッグログ
  // =========================
  console.log("===== FINAL DEBUG =====");
  console.log("RESULT:", result);
  console.log("SYMBOL:", symbol);
  console.log("RAW QTY:", rawQty);
  console.log("FINAL QTY:", finalQty);
  console.log("=======================");

  return (
    <div>

      {/* 🔥 確認用 */}
      <h1 style={{ color: "red" }}>
        RISK PANEL ACTIVE
      </h1>

      <h3>🔴 Risk Settings</h3>

      <Row label="Max DD %">
        <input
          value={maxDD}
          style={inputStyle}
          onChange={(e) => setMaxDD(e.target.value)}
        />
      </Row>

      <Row label="Max Loss Streak">
        <input
          value={maxLossStreak}
          style={inputStyle}
          onChange={(e) => setMaxLossStreak(e.target.value)}
        />
      </Row>

      <Row label="Max Position (USDT)">
        <input
          value={maxPosition}
          style={inputStyle}
          onChange={(e) => setMaxPosition(e.target.value)}
        />
      </Row>

      <hr style={{ margin: "16px 0", borderColor: "#333" }} />

      <h4>🟡 Result</h4>

      <div style={{ fontSize: 14 }}>

        <p>Position Size: {result?.positionSize ?? "-"} USDT</p>

        {/* 🔥 最終確定表示（ここが重要） */}
        <p>
          Qty: {finalQty} {symbolUnit}
        </p>

        <p>Risk Amount: {result?.riskAmount ?? "-"} USDT</p>
        <p>DD After Trade: {result?.ddAfter ?? "-"} %</p>

      </div>

    </div>
  );
}