// src/components/monitor/PriceCard.jsx

import {
  useEffect,
  useRef,
} from "react";

export default function PriceCard({
  price = null,
}) {

  const prev =
    useRef(null);

  const hasPrice =

    price !== null &&
    price !== undefined &&
    Number.isFinite(
      Number(price)
    );

  const previousPrice =

    prev.current !== null &&
    prev.current !== undefined &&
    Number.isFinite(
      Number(prev.current)
    )

      ? Number(prev.current)

      : null;

  const currentPrice =

    hasPrice
      ? Number(price)
      : null;

  const isUp =

    (
      currentPrice !== null &&
      previousPrice !== null &&
      currentPrice >
        previousPrice
    );

  const isDown =

    (
      currentPrice !== null &&
      previousPrice !== null &&
      currentPrice <
        previousPrice
    );

  useEffect(() => {

    if (
      hasPrice
    ) {

      prev.current =
        Number(price);

    }

  }, [
    price,
    hasPrice,
  ]);

  const color =

    isUp

      ? "#4ade80"

      : isDown

      ? "#f87171"

      : "#fff";

  const displayPrice =

    hasPrice

      ? Number(price)
          .toLocaleString()

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
        {displayPrice}
      </div>

      {/* DIRECTION */}
      <div
        style={{
          fontSize: "12px",
          marginTop: "4px",
          opacity: 0.7,
        }}
      >

        {isUp && "▲ UP"}

        {isDown && "▼ DOWN"}

        {!isUp &&
          !isDown &&
          "-"}

      </div>

    </div>

  );

}