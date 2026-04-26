import { useEffect, useRef } from "react";

const WS_URL = "ws://127.0.0.1:8000/ws/events";

export default function useEventWS(onMessage) {
  const wsRef = useRef(null);
  const retryRef = useRef(0);
  const timerRef = useRef(null);
  const onMessageRef = useRef(onMessage);

  // 最新のonMessageを保持
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    let isMounted = true;

    const clearTimer = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const connect = () => {
      if (!isMounted) return;

      // 🔥 多重接続防止（CONNECTINGも含めてブロック）
      if (wsRef.current) return;

      console.log("🔌 WS CONNECT TRY:", WS_URL);

      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("✅ WS CONNECTED");
        retryRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          // 🔥 heartbeatはUIに流さない
          if (data?.type === "ping") return;

          onMessageRef.current?.(data);
        } catch (e) {
          console.error("WS PARSE ERROR", e);
        }
      };

      ws.onerror = (err) => {
        console.warn("⚠️ WS ERROR", err);
      };

      ws.onclose = () => {
        console.warn("❌ WS CLOSED");

        // 🔥 参照クリア（最重要）
        wsRef.current = null;

        if (!isMounted) return;

        retryRef.current += 1;

        // 🔥 バックオフ（最大3秒）
        const delay = Math.min(3000, retryRef.current * 1000);

        clearTimer();
        timerRef.current = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      console.log("🛑 WS CLEANUP");

      isMounted = false;

      clearTimer();

      // 🔥 StrictMode対策：OPEN/CONNECTING時のみ安全にclose
      if (
        wsRef.current &&
        (wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING)
      ) {
        try {
          wsRef.current.close();
        } catch (e) {
          console.warn("WS close error", e);
        }
      }

      wsRef.current = null;
    };
  }, []);
}