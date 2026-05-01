import { useEffect, useState, useRef } from "react";

const WS_URL = "ws://127.0.0.1:8001/ws";
const API_URL = "http://127.0.0.1:8001/api/bot/summary";

export default function useBotData() {
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const isConnectingRef = useRef(false);

  const [data, setData] = useState({
    status: "LOADING",
    price: 0,
    balance: 0,
    equity: 0,
    pnl: 0,
    positions: [],
    logs: [],
    connection: "OFFLINE",
    risk: null
  });

  // =========================
  // 初回API取得（完全上書き）
  // =========================
  const fetchInitial = async () => {
    try {
      const res = await fetch(API_URL);
      const json = await res.json();

      console.log("📡 INIT API:", json);

      setData({
        status: json.status ?? "UNKNOWN",
        price: json.price ?? 0,
        balance: json.balance ?? 0,
        equity: json.equity ?? 0,
        pnl: json.pnl ?? 0,
        positions: json.positions ?? [],
        logs: json.logs ?? [],
        connection: "ONLINE",
        risk: json.risk ?? null
      });

    } catch (e) {
      console.error("❌ INIT FETCH ERROR", e);
    }
  };

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
        const msg = JSON.parse(event.data);
        console.log("📡 WS RAW:", msg);

        const payload = msg.data ?? msg;

        // 🔥 必要項目だけ更新（崩さない）
        setData(prev => ({
          status: payload.status ?? prev.status,
          price: payload.price ?? prev.price,
          balance: payload.balance ?? prev.balance,
          equity: payload.equity ?? prev.equity,
          pnl: payload.pnl ?? prev.pnl,
          positions: payload.positions ?? prev.positions ?? [],
          logs: payload.logs ?? prev.logs ?? [],
          connection: "ONLINE",
          risk: payload.risk ?? prev.risk
        }));

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
    fetchInitial();
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

  return data;
}