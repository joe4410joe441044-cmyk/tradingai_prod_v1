const DEFAULT_INTERVAL_MS = 3000;
const DEFAULT_MAX_BACKOFF_MS = 30000;

export function createMoneyManagementPollingController({
  fetchStatus,
  onRequestStart = () => {},
  onSuccess = () => {},
  onError = () => {},
  onStale = () => {},
  onPollingState = () => {},
  pollingIntervalMs = DEFAULT_INTERVAL_MS,
  maximumBackoffMs = DEFAULT_MAX_BACKOFF_MS,
  now = () => Date.now(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  documentRef = typeof document === "undefined" ? null : document,
} = {}) {
  if (typeof fetchStatus !== "function") {
    throw new TypeError("fetchStatus is required");
  }
  if (!Number.isInteger(pollingIntervalMs) || pollingIntervalMs <= 0) {
    throw new TypeError("pollingIntervalMs must be a positive integer");
  }
  if (!Number.isInteger(maximumBackoffMs) || maximumBackoffMs < pollingIntervalMs) {
    throw new TypeError("maximumBackoffMs is invalid");
  }

  let running = false;
  let requestSequence = 0;
  let activeRequest = null;
  let pollTimer = null;
  let staleTimer = null;
  let consecutiveFailures = 0;

  const clearPollTimer = () => {
    if (pollTimer !== null) clearTimer(pollTimer);
    pollTimer = null;
  };
  const clearStaleTimer = () => {
    if (staleTimer !== null) clearTimer(staleTimer);
    staleTimer = null;
  };
  const hidden = () => documentRef?.visibilityState === "hidden";

  const armStaleTimer = () => {
    clearStaleTimer();
    staleTimer = setTimer(() => {
      staleTimer = null;
      if (running) onStale(true);
    }, pollingIntervalMs * 3);
  };

  const schedule = (delay) => {
    clearPollTimer();
    if (!running || hidden()) return;
    pollTimer = setTimer(() => {
      pollTimer = null;
      void execute();
    }, delay);
  };

  const nextBackoff = () =>
    Math.min(
      pollingIntervalMs * (2 ** Math.max(0, consecutiveFailures - 1)),
      maximumBackoffMs,
    );

  async function execute({ supersede = false } = {}) {
    if (!running || hidden()) return null;
    if (activeRequest && !supersede) return activeRequest.promise;
    if (activeRequest && supersede) {
      activeRequest.controller.abort();
    }
    clearPollTimer();
    const requestId = ++requestSequence;
    const controller = new AbortController();
    onRequestStart({
      requestId,
      startedAt: now(),
    });
    const promise = Promise.resolve()
      .then(() => fetchStatus({ signal: controller.signal, requestId }))
      .then((result) => {
        if (!running || requestId !== requestSequence || hidden()) return null;
        consecutiveFailures = 0;
        const receivedAt = now();
        onSuccess({ requestId, result, receivedAt });
        onStale(false);
        armStaleTimer();
        schedule(pollingIntervalMs);
        return result;
      })
      .catch((error) => {
        if (!running || requestId !== requestSequence || controller.signal.aborted) {
          return null;
        }
        consecutiveFailures += 1;
        onError({
          requestId,
          error,
          receivedAt: now(),
          consecutiveFailures,
        });
        onStale(true);
        schedule(nextBackoff());
        return null;
      })
      .finally(() => {
        if (activeRequest?.requestId === requestId) {
          activeRequest = null;
        }
      });
    activeRequest = { requestId, controller, promise };
    return promise;
  }

  const visibilityChanged = () => {
    if (!running) return;
    if (hidden()) {
      clearPollTimer();
      clearStaleTimer();
      activeRequest?.controller.abort();
      onPollingState("SUSPENDED");
      onStale(true);
    } else {
      onPollingState("RUNNING");
      void execute({ supersede: true });
    }
  };

  return Object.freeze({
    start() {
      if (running) return false;
      running = true;
      documentRef?.addEventListener("visibilitychange", visibilityChanged);
      if (hidden()) {
        onPollingState("SUSPENDED");
        onStale(true);
      } else {
        onPollingState("RUNNING");
        void execute();
      }
      return true;
    },
    stop() {
      if (!running) return false;
      running = false;
      requestSequence += 1;
      clearPollTimer();
      clearStaleTimer();
      activeRequest?.controller.abort();
      activeRequest = null;
      documentRef?.removeEventListener("visibilitychange", visibilityChanged);
      onPollingState("STOPPED");
      onStale(true);
      return true;
    },
    refresh(options = {}) {
      return execute(options);
    },
    getSnapshot() {
      return Object.freeze({
        running,
        requestSequence,
        requestInFlight: activeRequest !== null,
        consecutiveFailures,
        pollingState: !running
          ? "STOPPED"
          : hidden()
            ? "SUSPENDED"
            : "RUNNING",
      });
    },
  });
}
