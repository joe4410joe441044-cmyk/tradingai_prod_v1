import { useEffect, useRef, useState } from "react";

/**
 * Reconnecting WebSocket Hook
 * - auto reconnect
 * - stable event stream
 */
export default function useEventWS(url, options = {}) {
  const wsRef = useRef(null);
  const retryRef = useRef(0);
  const [events, setEvents] = useState([]);

  const maxRetry = options.maxRetry ?? 999;
  const retryDelay = options.retryDelay ?? 2000;

  const connect = () => {
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("[WS] connected");
      retryRef.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        setEvents((prev) => [msg, ...prev].slice(0, 100));
      } catch (e) {
        console.error("[WS] parse error", e);
      }
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onclose = () => {
      console.warn("[WS] disconnected");

      if (retryRef.current < maxRetry) {
        retryRef.current += 1;

        console.log(
          `[WS] reconnecting... (${retryRef.current}/${maxRetry})`
        );

        setTimeout(connect, retryDelay);
      }
    };
  };

  useEffect(() => {
    connect();

    return () => {
      wsRef.current?.close();
    };
  }, [url]);

  return events;
}