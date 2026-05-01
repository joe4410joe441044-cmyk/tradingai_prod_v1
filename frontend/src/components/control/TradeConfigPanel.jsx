import { useState, useEffect } from "react";

// =========================
// 行コンポーネント
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
      <span style={{ width: 120 }}>{label}</span>
      {children}
    </div>
  );
}

// =========================
// Trade Settings（純入力 + Apply対応）
// =========================
export default function TradeConfigPanel({ onChange }) {

  const [config, setConfig] = useState({
    riskPercent: "1",
    slPercent: "1",
    leverage: "10",
    symbol: "BTCUSDT"
  });

  // 🔥 状態表示（Apply結果）
  const [status, setStatus] = useState("");

  // 🔥 選択可能銘柄
  const symbols = [
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "BNBUSDT"
  ];

  // =========================
  // 数字入力制御
  // =========================
  const handleNumberInput = (key, value) => {
    if (/^\d*\.?\d*$/.test(value)) {
      setConfig(prev => ({ ...prev, [key]: value }));
    }
  };

  // =========================
  // 親へ渡す（プレビュー用）
  // =========================
  useEffect(() => {
    if (!onChange) return;

    onChange({
      symbol: config.symbol,
      riskPercent: Number(config.riskPercent || 0),
      slPercent: Number(config.slPercent || 0),
      leverage: Number(config.leverage || 0)
    });

  }, [config]);

  const inputStyle = {
    width: 200,
    padding: 6,
    borderRadius: 6,
    border: "1px solid #444",
    background: "#222",
    color: "#fff"
  };

  const buttonStyle = {
    padding: "6px 12px",
    borderRadius: 6,
    border: "1px solid #555",
    background: "#333",
    color: "#fff",
    cursor: "pointer"
  };

  // =========================
  // 🔥 Apply（symbol即反映）
  // =========================
  const handleApplySymbol = async () => {
    try {
      setStatus("Applying...");

      const res = await fetch("http://localhost:8001/api/symbol", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ symbol: config.symbol })
      });

      const data = await res.json();

      if (data.error) {
        setStatus("❌ Failed");
        console.error(data.error);
        return;
      }

      setStatus("✅ Applied");
      console.log("Symbol Applied:", data);

    } catch (err) {
      console.error(err);
      setStatus("❌ Error");
    }
  };

  // =========================
  // UI
  // =========================
  return (
    <div
      style={{
        padding: 20,
        borderBottom: "1px solid #333",
        maxWidth: 400
      }}
    >
      <h2>🟢 Trade Settings</h2>

      {/* Symbol + Apply */}
      <Row label="Symbol">
        <div style={{ display: "flex", gap: 8 }}>
          <select
            value={config.symbol}
            style={inputStyle}
            onChange={e =>
              setConfig(prev => ({ ...prev, symbol: e.target.value }))
            }
          >
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>

          <button style={buttonStyle} onClick={handleApplySymbol}>
            Apply
          </button>
        </div>
      </Row>

      {/* Applyステータス表示 */}
      {status && (
        <div style={{ fontSize: 12, marginBottom: 10, color: "#aaa" }}>
          {status}
        </div>
      )}

      <Row label="Risk %">
        <input
          type="text"
          value={config.riskPercent}
          style={inputStyle}
          onChange={e => handleNumberInput("riskPercent", e.target.value)}
        />
      </Row>

      <Row label="SL %">
        <input
          type="text"
          value={config.slPercent}
          style={inputStyle}
          onChange={e => handleNumberInput("slPercent", e.target.value)}
        />
      </Row>

      <Row label="Leverage">
        <input
          type="text"
          value={config.leverage}
          style={inputStyle}
          onChange={e => handleNumberInput("leverage", e.target.value)}
        />
      </Row>
    </div>
  );
}