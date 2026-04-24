import { useEffect, useRef } from "react";

const WS_URL = "ws://127.0.0.1:8000/ws/events";

export default function useEventWS(onMessage) {
  const wsRef = useRef(null);
  const retryRef = useRef(0);

  useEffect(() => {
    let ws;

    const connect = () => {
      console.log("🔌 WS CONNECT TRY:", WS_URL);

      ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("✅ WS CONNECTED");
        retryRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onMessage && onMessage(data);
        } catch (e) {
          console.error("WS PARSE ERROR", e);
        }
      };

      ws.onerror = (err) => {
        console.warn("⚠️ WS ERROR", err);
      };

      ws.onclose = () => {
        console.warn("❌ WS CLOSED");

        retryRef.current += 1;
        setTimeout(connect, Math.min(3000, retryRef.current * 1000));
      };
    };

    connect();

    return () => {
      console.log("🛑 WS CLEANUP");
      ws && ws.close();
    };
  }, [onMessage]);
}