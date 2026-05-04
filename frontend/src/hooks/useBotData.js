import { useEffect, useState, useRef } from "react";

const WS_URL = "ws://127.0.0.1:8001/ws";

export default function useBotData() {
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const isConnectingRef = useRef(false);

  const [data, setData] = useState({
    status: "STOPPED",
    price: 0,
    balance: 0,
    equity: 0,
    pnl: 0,
    positions: [],
    logs: [],
    connection: "OFFLINE",
    risk: null,
    symbol: null
  });

  // =========================
  // WebSocket接続
  // =========================
  const connect = () => {
    if (wsRef.current || isConnectingRef.current) return;

    isConnectingRef.current = true;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("🟢 WS CONNECTED");
      isConnectingRef.current = false;

      setData(prev => ({
        ...prev,
        connection: "ONLINE"
      }));
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);

        console.log("📡 WS DATA:", payload);

        // 🔥 完全上書き（←これ重要）
        setData({
          status: payload.status ?? "STOPPED",
          price: payload.price ?? 0,
          balance: payload.balance ?? 0,
          equity: payload.equity ?? 0,
          pnl: payload.pnl ?? 0,
          positions: payload.positions ?? [],
          logs: payload.logs ?? [],
          connection: "ONLINE",
          risk: payload.risk ?? null,
          symbol: payload.symbol ?? null
        });

      } catch (e) {
        console.error("❌ WS PARSE ERROR", event.data);
      }
    };

    ws.onerror = (e) => {
      console.error("🔴 WS ERROR", e);
    };

    ws.onclose = (event) => {
      console.log("🔴 WS CLOSED", event.code);

      setData(prev => ({
        ...prev,
        connection: "OFFLINE"
      }));

      wsRef.current = null;
      isConnectingRef.current = false;

      // 正常終了なら再接続しない
      if (event.code === 1000) return;

      if (!reconnectTimerRef.current) {
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null;
          connect();
        }, 2000);
      }
    };
  };

  // =========================
  // 初期化
  // =========================
  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      isConnectingRef.current = false;
    };
  }, []);

  // =========================
  // UIに渡す
  // =========================
  return data;
}