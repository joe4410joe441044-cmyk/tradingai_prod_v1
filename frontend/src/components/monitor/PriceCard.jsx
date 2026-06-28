// src/components/monitor/PriceCard.jsx

import {
  useEffect,
  useRef,
} from "react";

export default function PriceCard({
  price = null,
}) {
  const prev = useRef(null);

  const hasPrice =
    price !== null &&
    price !== undefined &&
    Number.isFinite(
      Number(price)
    );

  const currentPrice =
    hasPrice
      ? Number(price)
      : null;

  useEffect(() => {
    if (!hasPrice) {
      return;
    }

    prev.current =
      Number(price);

  }, [
    price,
    hasPrice,
  ]);

  const color = "#fff";

  const displayPrice =
    hasPrice
      ? currentPrice.toLocaleString()
      : "-";

  return (
    <div
      style={{
        background: "#111",
        borderRadius: "16px",
        padding: "16px",
        boxShadow:
          "0 6px 20px rgba(0,0,0,0.3)",
        textAlign: "center",
        transition: "0.2s",
      }}
    >
      <div
        style={{
          fontSize: "12px",
          opacity: 0.6,
          marginBottom: "8px",
        }}
      >
        Price
      </div>

      <div
        style={{
          fontSize: "32px",
          fontWeight: "bold",
          color,
          transition: "0.2s",
        }}
      >
        {displayPrice}
      </div>

      <div
        style={{
          fontSize: "12px",
          marginTop: "4px",
          opacity: 0.7,
        }}
      >
        -
      </div>
    </div>
  );
}