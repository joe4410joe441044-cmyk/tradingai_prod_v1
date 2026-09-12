import { normalizeMonitoringResponse, requireViewAuthority } from "../contracts/moneyManagementMonitoringContracts.js";
import { loadMoneyManagementAnalyticsHistory } from "../analytics/moneyManagementAnalytics.js";

export const loadingMonitoring = (authority) => ({
  authority, monitoring: null, monitoringState: "LOADING", history: [], historyState: "LOADING",
});

// Read-only controller. Identity checks also protect against clients that ignore abort.
export function createMonitoringReader({ getMonitoring, getHistory, onChange }) {
  let sequence = 0;
  let controller;
  let current;
  return {
    async load(authority) {
      requireViewAuthority(authority);
      const request = ++sequence;
      controller?.abort();
      controller = new AbortController();
      const { signal } = controller;
      // Retain only this reader's validated publications for the same View.
      // Background refresh must not turn READY history into initial loading.
      let state = current?.authority === authority ? current : loadingMonitoring(authority);
      current = state;
      onChange(state);
      const publish = (patch) => {
        if (request !== sequence || signal.aborted) return;
        state = { ...state, ...patch };
        current = state;
        onChange(state);
      };
      await Promise.all([
        (async () => {
          try {
            const raw = await getMonitoring(authority, { signal });
            const monitoring = normalizeMonitoringResponse(raw, authority);
            publish({ monitoring, monitoringState: monitoring.freshness });
          } catch {
            publish({ monitoring: null, monitoringState: "ERROR" });
          }
        })(),
        (async () => {
          try {
            const history = await loadMoneyManagementAnalyticsHistory({ client: getHistory, signal, authority });
            publish({ history, historyState: "READY" });
          } catch {
            publish({ history: [], historyState: "ERROR" });
          }
        })(),
      ]);
    },
    stop() {
      sequence += 1;
      controller?.abort();
    },
  };
}
