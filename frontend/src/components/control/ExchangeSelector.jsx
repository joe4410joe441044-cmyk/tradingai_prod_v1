import React from "react";

export default function ExchangeSelector({ selected, onChange }) {
  const exchanges = ["bybit", "binance", "kucoin", "okx"];

  return (
    <div className="card">
      <h3>Trading Exchange</h3>

      <select
        value={selected}
        onChange={(e) => onChange(e.target.value)}
      >
        {exchanges.map((ex) => (
          <option key={ex} value={ex}>
            {ex.toUpperCase()}
          </option>
        ))}
      </select>
    </div>
  );
}