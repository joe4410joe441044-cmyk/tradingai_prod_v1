import { useEffect, useRef, useState } from "react";
import { API } from "../api";

/**
 * PRODUCTION STABLE VERSION + WS UPGRADE
 * - REST: full sync (safety)
 * - WS: price realtime override
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
  // STATUS
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
  // PRICE (REST fallback only)
  // =========================
  const fetchPrice = async () => {
    try {
      const res = await fetch(API.price?.() || "/api/price");
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
  // SUMMARY (ACCOUNT)
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
  // LOGS (append safe)
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
  // MASTER LOOP (REST)
  // =========================
  const fetchAll = async () => {
    await fetchStatus();
    await fetchPrice();
    await fetchSummary();
    await fetchLogs();
  };

  useEffect(() => {
    fetchAll();
    timerRef.current = setInterval(fetchAll, interval);

    return () => clearInterval(timerRef.current);
  }, [interval]);

  // =========================
  // 🚀 WEBSOCKET (REALTIME PRICE)
  // =========================
  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws/price");

    ws.onopen = () => {
      console.log("WS connected");
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      // 🔥 ONLY price override (no state clash)
      setState(prev => ({
        ...prev,
        price: data.price,
      }));
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