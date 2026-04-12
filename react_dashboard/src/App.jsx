import { useState, useEffect } from "react";
import PositionsTable from "./components/PositionsTable.jsx";
import PriceCard from "./components/PriceCard.jsx";
import RightPanel from "./components/RightPanel.jsx";
import AIScoreChart from "./AIScoreChart.jsx";

const API_BASE = "http://34.85.66.137:8000";

export default function App() {
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [botStatus, setBotStatus] = useState({ running: false });
  const [currentPrice, setCurrentPrice] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    const fetchData = async () => {
      try {
        setLoading(true);
        setErrorMsg(null);

        // ----------------------
        // Positions
        // ----------------------
        const posRes = await fetch(`${API_BASE}/positions`, {
          signal: controller.signal,
        });

        if (!posRes.ok) throw new Error("positions fetch failed");

        const posData = await posRes.json();
        const safePositions = Array.isArray(posData) ? posData : [];

        setPositions(safePositions);

        // ----------------------
        // Bot Status
        // ----------------------
        const statusRes = await fetch(`${API_BASE}/bot_status`, {
          signal: controller.signal,
        });

        if (!statusRes.ok) throw new Error("bot_status fetch failed");

        const statusData = await statusRes.json();
        setBotStatus({
          running: statusData?.running ?? false,
        });

        // ----------------------
        // Price
        // ----------------------
        if (safePositions.length > 0) {
          setCurrentPrice(
            safePositions[safePositions.length - 1]?.mark_price ?? null
          );
        } else {
          setCurrentPrice(null);
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          console.error(err);
          setPositions([]);
          setBotStatus({ running: false });
          setCurrentPrice(null);
          setErrorMsg(
            "接続エラー：FastAPIが起動しているか確認してください"
          );
        }
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);

    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, []);

  // ----------------------
  // Bot Control
  // ----------------------
  const startBot = async () => {
    try {
      await fetch(`${API_BASE}/bot/start`, { method: "POST" });
      setBotStatus({ running: true });
    } catch (err) {
      console.error(err);
      setErrorMsg("BOT起動失敗");
    }
  };

  const stopBot = async () => {
    try {
      await fetch(`${API_BASE}/bot/stop`, { method: "POST" });
      setBotStatus({ running: false });
    } catch (err) {
      console.error(err);
      setErrorMsg("BOT停止失敗");
    }
  };

  // ----------------------
  // UI
  // ----------------------
  return (
    <div style={{ display: "flex", gap: "20px", padding: "20px" }}>
      {/* LEFT */}
      <div style={{ flex: 1 }}>
        <PriceCard currentPrice={currentPrice} />
        <PositionsTable positions={positions} loading={loading} />

        {errorMsg && (
          <div style={{ color: "red", marginTop: "10px" }}>
            {errorMsg}
          </div>
        )}

        <div style={{ marginTop: "20px" }}>
          <button
            onClick={startBot}
            disabled={botStatus.running}
            style={{ marginRight: "10px" }}
          >
            Start Bot
          </button>

          <button
            onClick={stopBot}
            disabled={!botStatus.running}
          >
            Stop Bot
          </button>

          <span style={{ marginLeft: "20px" }}>
            Status: {botStatus.running ? "RUNNING" : "STOPPED"}
          </span>
        </div>
      </div>

      {/* RIGHT */}
      <div style={{ width: "350px" }}>
        <RightPanel />
      </div>

      {/* AI SCORE */}
      <div style={{ width: "450px" }}>
        <AIScoreChart symbol="BTCUSDT" />
      </div>
    </div>
  );
}