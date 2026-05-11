// =========================
// REALTIME WS LIFECYCLE
// =========================

export const createRealtimeWebSocketLifecycle = ({

  url,

  onMessage,
  onOpen,
  onClose,
  onError,

  onReconnect,
  onStale,

  heartbeatInterval = 3000,
  staleTimeout = 5000,
  reconnectDelay = 2000,
  maxReconnect = 10,

  debug = false,

}) => {

  let socket = null;

  let reconnectAttempts = 0;

  let reconnectTimer = null;

  let heartbeatTimer = null;

  let staleCheckTimer = null;

  let lastMessageTime =
    Date.now();

  let staleTriggered =
    false;

  let packetCounter = 0;

  // =========================
  // DEBUG LOG
  // =========================

  const debugLog = (
    ...args
  ) => {

    if (debug) {

      console.log(
        ...args
      );

    }

  };

  // =========================
  // CLEANUP
  // =========================

  const cleanup = () => {

    if (heartbeatTimer) {

      clearInterval(
        heartbeatTimer
      );

      heartbeatTimer = null;

    }

    if (staleCheckTimer) {

      clearInterval(
        staleCheckTimer
      );

      staleCheckTimer = null;

    }

    if (reconnectTimer) {

      clearTimeout(
        reconnectTimer
      );

      reconnectTimer = null;

    }

  };

  // =========================
  // CLOSE SOCKET
  // =========================

  const closeSocket = () => {

    if (socket) {

      socket.close();

      socket = null;

    }

  };

  // =========================
  // STALE DETECTION
  // =========================

  const startStaleDetection = () => {

    staleCheckTimer = setInterval(() => {

      const now = Date.now();

      const elapsed =
        now - lastMessageTime;

      if (
        elapsed > staleTimeout
      ) {

        if (!staleTriggered) {

          staleTriggered = true;

          console.warn(
            "⚠️ WS STALE DETECTED"
          );

          if (onStale) {

            onStale();

          }

        }

      }

    }, 1000);

  };

  // =========================
  // HEARTBEAT
  // =========================

  const startHeartbeat = () => {

    heartbeatTimer = setInterval(() => {

      if (
        socket &&
        socket.readyState ===
          WebSocket.OPEN
      ) {

        // =========================
        // OPTIONAL PING
        // =========================

        // socket.send(
        //   JSON.stringify({
        //     type: "PING",
        //   })
        // );

      }

    }, heartbeatInterval);

  };

  // =========================
  // CONNECT
  // =========================

  const connect = () => {

    console.log(
      "🌐 WS CONNECT:",
      url
    );

    socket =
      new WebSocket(url);

    // =========================
    // OPEN
    // =========================

    socket.onopen = () => {

      reconnectAttempts = 0;

      staleTriggered = false;

      lastMessageTime =
        Date.now();

      console.log(
        "🟢 WS CONNECTED"
      );

      startHeartbeat();

      startStaleDetection();

      if (onOpen) {

        onOpen(socket);

      }

    };

    // =========================
    // MESSAGE
    // =========================

    socket.onmessage = (
      event
    ) => {

      lastMessageTime =
        Date.now();

      staleTriggered =
        false;

      packetCounter += 1;

      // =========================
      // SAMPLE LOGGING
      // =========================

      if (
        debug &&
        packetCounter % 50 === 0
      ) {

        debugLog(
          "📡 WS DATA:",
          event.data
        );

      }

      if (onMessage) {

        onMessage(event);

      }

    };

    // =========================
    // ERROR
    // =========================

    socket.onerror = (
      event
    ) => {

      console.error(
        "❌ WS ERROR EVENT:",
        event
      );

      debugLog(
        "WS URL:",
        socket?.url
      );

      debugLog(
        "WS readyState:",
        socket?.readyState
      );

      debugLog(
        "WS protocol:",
        socket?.protocol
      );

      debugLog(
        "WS extensions:",
        socket?.extensions
      );

      if (onError) {

        onError(event);

      }

    };

    // =========================
    // CLOSE
    // =========================

    socket.onclose = (
      event
    ) => {

      console.error(
        "🔌 WS CLOSED"
      );

      debugLog(
        "Close code:",
        event.code
      );

      debugLog(
        "Close reason:",
        event.reason
      );

      debugLog(
        "Was clean:",
        event.wasClean
      );

      debugLog(
        "WS readyState:",
        socket?.readyState
      );

      cleanup();

      if (onClose) {

        onClose(event);

      }

      if (
        reconnectAttempts <
        maxReconnect
      ) {

        reconnectAttempts += 1;

        if (onReconnect) {

          onReconnect(
            reconnectAttempts
          );

        }

        reconnectTimer =
          setTimeout(() => {

            console.log(
              `♻️ WS RECONNECT ${reconnectAttempts}`
            );

            connect();

          }, reconnectDelay);

      }

    };

  };

  // =========================
  // START
  // =========================

  connect();

  // =========================
  // DESTROY
  // =========================

  return {

    destroy: () => {

      cleanup();

      closeSocket();

    },

  };

};