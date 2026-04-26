// src/components/monitor/PriceCard.jsx

import { useEffect, useRef } from "react";

export default function PriceCard({ price = 0 }) {
  const prev = useRef(price);

  const isUp = price > prev.current;
  const isDown = price < prev.current;

  useEffect(() => {
    prev.current = price;
  }, [price]);

  const color = isUp ? "#4ade80" : isDown ? "#f87171" : "#fff";

  return (
    <div
      style={{
        background: "#111",
        borderRadius: "16px",
        padding: "16px",
        boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
        textAlign: "center",
        transition: "0.2s",
      }}
    >
      {/* TITLE */}
      <div
        style={{
          fontSize: "12px",
          opacity: 0.6,
          marginBottom: "8px",
        }}
      >
        Price
      </div>

      {/* VALUE */}
      <div
        style={{
          fontSize: "32px",
          fontWeight: "bold",
          color,
          transition: "0.2s",
        }}
      >
        {Number(price).toLocaleString()}
      </div>

      {/* DIRECTION */}
      <div style={{ fontSize: "12px", marginTop: "4px", opacity: 0.7 }}>
        {isUp && "▲ UP"}
        {isDown && "▼ DOWN"}
        {!isUp && !isDown && "-"}
      </div>
    </div>
  );
}