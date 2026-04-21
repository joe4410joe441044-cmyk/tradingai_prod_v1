import { useEffect, useRef, useState } from "react";
import { API, WS } from "../api";

/**
 * PRODUCTION STABLE VERSION + WS UPGRADE (FIXED)
 */

export default function useBotData(interval = 2000) {

  const [state, setState] = useState({
    price: 0,
    balance: 0,
    pnl: 0,
    equity: 0,
    risk: 0,
    openPositions: [],
    logs: [],
    status: "STOPPED",
    connected: false,
  });

  const timerRef = useRef(null);

  // =========================
  // REST: STATUS
  // =========================
  const fetchStatus = async () => {
    try {
      const res = await fetch(API.botStatus());
      const data = await res.json().catch(() => ({}));

      setState(prev => ({
        ...prev,
        status: data?.running ? "RUNNING" : "STOPPED",
        connected: data?.thread_alive ?? false,
      }));
    } catch (e) {
      console.error("status error:", e);
    }
  };

  // =========================
  // REST: PRICE (fallback only)
  // =========================
  const fetchPrice = async () => {
    try {
      const res = await fetch(API.price());
      const data = await res.json().catch(() => ({}));

      setState(prev => ({
        ...prev,
        price: data?.price ?? 0,
      }));
    } catch (e) {
      console.error("price error:", e);
    }
  };

  // =========================
  // REST: SUMMARY
  // =========================
  const fetchSummary = async () => {
    try {
      const res = await fetch(API.summary());
      const data = await res.json().catch(() => ({}));

      setState(prev => ({
        ...prev,
        balance: data?.balance ?? 0,
        pnl: data?.pnl ?? 0,
        equity: data?.equity ?? 0,
        risk: data?.risk ?? 0,
        openPositions: data?.open_positions ?? [],
      }));
    } catch (e) {
      console.error("summary error:", e);
    }
  };

  // =========================
  // REST: LOGS
  // =========================
  const fetchLogs = async () => {
    try {
      const res = await fetch(API.logs());
      const data = await res.json().catch(() => []);

      const newLogs = Array.isArray(data) ? data : [];

      setState(prev => ({
        ...prev,
        logs: [...prev.logs, ...newLogs].slice(-100),
      }));

    } catch (e) {
      console.error("logs error:", e);
    }
  };

  // =========================
  // MASTER LOOP (REST SYNC)
  // =========================
  const fetchAll = async () => {
    await fetchStatus();
    await fetchSummary();
    await fetchLogs();
    await fetchPrice(); // fallback only
  };

  useEffect(() => {
    fetchAll();
    timerRef.current = setInterval(fetchAll, interval);

    return () => clearInterval(timerRef.current);
  }, [interval]);

  // =========================
  // 🚀 WEBSOCKET (REALTIME PRICE ONLY)
  // =========================
  useEffect(() => {

    const ws = new WebSocket(WS.price);

    ws.onopen = () => {
      console.log("WS connected");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        setState(prev => ({
          ...prev,
          price: data.price, // ONLY overwrite price
        }));

      } catch (e) {
        console.error("WS parse error:", e);
      }
    };

    ws.onerror = (err) => {
      console.error("WS error:", err);
    };

    ws.onclose = () => {
      console.log("WS closed");
    };

    return () => ws.close();
  }, []);

  return state;
}