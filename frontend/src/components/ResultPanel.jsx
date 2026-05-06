export default function ResultPanel({
  price = 0,
  balance = 1000,
  risk_percent = 1,
  sl_percent = 1,
  tp_percent = 1,
  timeExit = 3,
}) {

  const safeNum = (v) => (isNaN(v) || v === null ? 0 : Number(v));

  const p = safeNum(price);
  const bal = safeNum(balance);

  const risk = bal * (risk_percent / 100);
  const qty = p > 0 ? risk / p : 0;

  const tp = p > 0 ? p * (1 + tp_percent / 100) : 0;
  const sl = p > 0 ? p * (1 - sl_percent / 100) : 0;

  const format = (num, digits = 2) => {
    if (!num || num === Infinity) return "-";
    return num.toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits,
    });
  };

  // 🔥 状態判定（ここ重要）
  const isValid = p > 0 && bal > 0 && risk > 0;

  return (
    <div className="card">
      <h2>📊 Result</h2>

      {/* サイズ */}
      <div>Position Size: {format(risk)} USDT</div>
      <div>Qty: {format(qty, 6)}</div>
      <div>Risk Amount: {format(risk)} USDT</div>

      <hr />

      {/* TP / SL */}
      <div>TP Price: {format(tp, 4)}</div>
      <div>SL Price: {format(sl, 4)}</div>

      <div>Time Exit: {timeExit} sec</div>

      {/* ステータス */}
      <div
        style={{
          color: isValid ? "#00ff88" : "#ff4d4f",
          marginTop: 8,
          fontWeight: "bold"
        }}
      >
        Status: {isValid ? "✅ VALID" : "❌ INVALID"}
      </div>
    </div>
  );
}