// src/components/dashboard/AssetDashboard.jsx

import { useState, useEffect } from "react";
import { getAssetSummary } from "../../api/bot";

import BalanceCard from "../BalanceCard";

export default function AssetDashboard() {
  const [asset, setAsset] = useState({
    pnl: 0,
    equity: 0,
    open_positions: 0,
    risk: 0,
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // --------------------------
  // 資産データ取得（統合API）
  // --------------------------
  const fetchAsset = async () => {
    try {
      setLoading(true);
      setError(false);

      const data = await getAssetSummary();

      setAsset({
        pnl: data?.pnl ?? 0,
        equity: data?.equity ?? 0,
        open_positions: data?.open_positions ?? 0,
        risk: data?.risk ?? 0,
      });

    } catch (err) {
      console.error("Asset fetch error:", err);
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  // --------------------------
  // 初回 + 10秒更新
  // --------------------------
  useEffect(() => {
    fetchAsset();

    const interval = setInterval(() => {
      fetchAsset();
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  // --------------------------
  // UI
  // --------------------------
  return (
    <div className="asset-dashboard">

      {/* TOP ROW */}
      <div className="top-row">
        <BalanceCard />

        <div className="card">
          <h3>PnL</h3>
          <h2>
            {loading ? "Loading..." : error ? "ERROR" : `$${asset.pnl}`}
          </h2>
        </div>

        <div className="card">
          <h3>Equity</h3>
          <h2>
            {loading ? "Loading..." : error ? "ERROR" : `$${asset.equity}`}
          </h2>
        </div>
      </div>

      {/* MIDDLE ROW */}
      <div className="middle-row">
        <div className="card">
          <h3>Open Positions</h3>
          <h2>
            {loading ? "..." : asset.open_positions}
          </h2>
        </div>

        <div className="card">
          <h3>Risk</h3>
          <h2>
            {loading ? "..." : `${(asset.risk * 100).toFixed(1)}%`}
          </h2>
        </div>
      </div>

      {/* STATUS */}
      {error && (
        <div className="error-bar">
          ⚠ Asset API Error
        </div>
      )}

    </div>
  );
}