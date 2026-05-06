import { useState, useEffect, useRef } from "react";
import StrategyControl from "./StrategyControl";

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
// Trade Settings + Strategy統合版
// =========================
export default function TradeConfigPanel({ onChange }) {

  const [config, setConfig] = useState({
    // ===== trade =====
    risk_percent: "1",
    sl_percent: "1",
    leverage: "10",
    symbol: "BTCUSDT",

    // ===== strategy =====
    mode: 0.62,
    gamma: 0.0025,
    delta_buy: 0.56,
    sigma: 0.02,
    edge: 0.00025
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
  // 🔥 Backend送信（改善版）
  // =========================
  const timerRef = useRef(null);
  const lastSentRef = useRef(null); // ← 重複送信防止

  const sendConfig = (cfg) => {
    clearTimeout(timerRef.current);

    timerRef.current = setTimeout(async () => {
      try {
        const json = JSON.stringify(cfg);

        // 🔥 同一内容なら送らない
        if (lastSentRef.current === json) return;
        lastSentRef.current = json;

        console.log("📤 SEND CONFIG:", cfg);

        const res = await fetch("http://localhost:8001/config", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: json
        });

        if (!res.ok) {
          console.error("❌ APIエラー", res.status);
        }

      } catch (e) {
        console.error("❌ Config送信失敗", e);
      }
    }, 250); // 少し余裕持たせる
  };

  // =========================
  // 親へ通知 + Backend送信（統一）
  // =========================
  const emitChange = (cfg) => {

    const payload = {
      symbol: cfg.symbol,
      risk_percent: Number(cfg.risk_percent || 0),
      sl_percent: Number(cfg.sl_percent || 0),
      leverage: Number(cfg.leverage || 0),

      // strategy
      mode: cfg.mode,
      gamma: cfg.gamma,
      delta_buy: cfg.delta_buy,
      sigma: cfg.sigma,
      edge: cfg.edge
    };

    // 親へ
    if (onChange) onChange(payload);

    // Backendへ
    sendConfig(payload);
  };

  // =========================
  // 初回同期
  // =========================
  useEffect(() => {
    emitChange(config);
  }, []);

  // =========================
  // クリーンアップ（重要）
  // =========================
  useEffect(() => {
    return () => {
      clearTimeout(timerRef.current);
    };
  }, []);

  // =========================
  // 更新処理
  // =========================
  const updateConfig = (key, value) => {
    const newConfig = { ...config, [key]: value };
    setConfig(newConfig);
    emitChange(newConfig);
  };

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
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </Row>

      <div style={{ fontSize: 12, color: "#aaa", marginBottom: 12 }}>
        選択中: {config.symbol}
      </div>

      <Row label="Risk %">
        <input
          value={config.risk_percent}
          style={inputStyle}
          onChange={e => handleNumberInput("risk_percent", e.target.value)}
        />
      </Row>

      <Row label="SL %">
        <input
          value={config.sl_percent}
          style={inputStyle}
          onChange={e => handleNumberInput("sl_percent", e.target.value)}
        />
      </Row>

      <Row label="Leverage">
        <input
          value={config.leverage}
          style={inputStyle}
          onChange={e => handleNumberInput("leverage", e.target.value)}
        />
      </Row>

      {/* =========================
          🧠 Strategy Control
      ========================= */}
      <div style={{ marginTop: 30 }}>
        <StrategyControl
          values={config}
          onChange={(updates) => {
            const newConfig = { ...config, ...updates };
            setConfig(newConfig);
            emitChange(newConfig);
          }}
        />
      </div>
    </div>
  );
}