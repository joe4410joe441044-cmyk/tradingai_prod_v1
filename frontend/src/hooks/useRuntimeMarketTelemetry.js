import { useSyncExternalStore } from "react";

import {
    getMarketTelemetrySnapshot,
    getRuntimeTelemetrySnapshot,
    subscribeTelemetry,
} from "../store/telemetryStore.js";

export function useRuntimeMarketTelemetry() {
    const market = useSyncExternalStore(
        subscribeTelemetry,
        getMarketTelemetrySnapshot,
        getMarketTelemetrySnapshot,
    );
    const runtime = useSyncExternalStore(
        subscribeTelemetry,
        getRuntimeTelemetrySnapshot,
        getRuntimeTelemetrySnapshot,
    );
    return { market, runtime };
}
