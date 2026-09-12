import { useCallback, useEffect, useRef, useState } from "react";
import { getMoneyManagementMonitoring, getMoneyManagementHistory } from "../api/moneyManagementApi.js";
import { createMonitoringReader, loadingMonitoring } from "../state/moneyManagementMonitoringReader.js";

export function useMoneyManagementMonitoring(viewAuthority, enabled = true) {
  const [data, setData] = useState(() => loadingMonitoring(viewAuthority));
  const refreshRef = useRef(() => Promise.resolve());
  useEffect(() => {
    if (!enabled) return undefined;
    const reader = createMonitoringReader({
      getMonitoring: getMoneyManagementMonitoring,
      getHistory: getMoneyManagementHistory,
      onChange: setData,
    });
    let active = true;
    let timer;
    let refreshSequence = 0;
    const refresh = async () => {
      const request = ++refreshSequence;
      clearTimeout(timer);
      await reader.load(viewAuthority);
      if (active && request === refreshSequence) {
        clearTimeout(timer);
        timer = setTimeout(refresh, 3000);
      }
    };
    refreshRef.current = refresh;
    void refresh();
    return () => {
      active = false;
      clearTimeout(timer);
      reader.stop();
      refreshRef.current = () => Promise.resolve();
    };
  }, [viewAuthority, enabled]);
  const refresh = useCallback(() => refreshRef.current(), []);
  // Effects run after paint: never expose the previous View in that render.
  return { ...(enabled && data.authority === viewAuthority ? data : loadingMonitoring(viewAuthority)), refresh };
}
