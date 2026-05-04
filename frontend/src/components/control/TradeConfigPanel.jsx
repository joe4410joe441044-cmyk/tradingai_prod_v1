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
// Trade Settings（完全同期版）
// =========================
export default function TradeConfigPanel({ onChange }) {

  const [config, setConfig] = useState({
    risk_percent: "1",
    sl_percent: "1",
    leverage: "10",
    symbol: "BTCUSDT"
  });

  const symbols = [
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "BNBUSDT"
  ];

  const inputStyle = {
    width: 200,
    padding: 6,
    borderRadius: 6,
    border: "1px solid #444",
    background: "#222",
    color: "#fff"
  };

  // =========================
  // 🔥 親へ通知（唯一のデータルート）
  // =========================
  const emitChange = (cfg) => {
    if (onChange) {
      onChange({
        symbol: cfg.symbol,
        risk_percent: Number(cfg.risk_percent || 0),
        sl_percent: Number(cfg.sl_percent || 0),
        leverage: Number(cfg.leverage || 0)
      });
    }
  };

  // =========================
  // 🔥 初回同期
  // =========================
  useEffect(() => {
    emitChange(config);
  }, []);

  // =========================
  // 🔥 更新処理（常に親へ通知）
  // =========================
  const updateConfig = (key, value) => {
    const newConfig = {
      ...config,
      [key]: value
    };

    setConfig(newConfig);
    emitChange(newConfig);
  };

  // =========================
  // 数字入力制御
  // =========================
  const handleNumberInput = (key, value) => {
    if (/^\d*\.?\d*$/.test(value)) {
      updateConfig(key, value);
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

      {/* Symbol */}
      <Row label="Symbol">
        <select
          value={config.symbol}
          style={inputStyle}
          onChange={e => updateConfig("symbol", e.target.value)}
        >
          {symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </Row>

      {/* 🔥 追加：現在選択中 */}
      <div style={{ fontSize: 12, color: "#aaa", marginBottom: 12 }}>
        選択中: {config.symbol}
      </div>

      <Row label="Risk %">
        <input
          type="text"
          value={config.risk_percent}
          style={inputStyle}
          onChange={e => handleNumberInput("risk_percent", e.target.value)}
        />
      </Row>

      <Row label="SL %">
        <input
          type="text"
          value={config.sl_percent}
          style={inputStyle}
          onChange={e => handleNumberInput("sl_percent", e.target.value)}
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