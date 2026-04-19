// src/components/monitor/PriceCard.jsx

export default function PriceCard({ price = 0 }) {
  return (
    <div style={{ padding: "10px", border: "1px solid #333" }}>
      
      <h3>Price</h3>

      <p style={{ fontSize: "18px", fontWeight: "bold" }}>
        {price}
      </p>

    </div>
  );
}