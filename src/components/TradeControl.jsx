import React from "react";

export default function TradeControl({ config, onChange }) {

  const toggleDryRun = () => {

    // 🚨 liveでOFFにする時だけ確認
    if (config.mode === "live" && config.dry_run === true) {
      const ok = window.confirm(
        "⚠️ REAL TRADINGになります。\n本当にdry_runをOFFにしますか？"
      );
      if (!ok) return;
    }

    const newConfig = {
      ...config,
      dry_run: !config.dry_run
    };

    onChange(newConfig);
  };

  return (
    <div style={{ border: "1px solid #ccc", padding: "10px", marginTop: "10px" }}>

      <h4>Control</h4>

      {/* DRY RUN表示 */}
      <p>
        DRY RUN:{" "}
        <b style={{ color: config.dry_run ? "green" : "red" }}>
          {config.dry_run ? "ON (SAFE)" : "OFF (REAL)"}
        </b>
      </p>

      {/* トグルボタン */}
      <button onClick={toggleDryRun}>
        Toggle Dry Run
      </button>

      {/* 🚨 本番警告 */}
      {config.mode === "live" && !config.dry_run && (
        <div style={{ color: "red", fontWeight: "bold" }}>
          ⚠️ REAL TRADING ACTIVE
        </div>
      )}

    </div>
  );
}