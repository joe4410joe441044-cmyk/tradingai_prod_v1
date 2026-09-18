import { useCallback, useEffect, useState } from "react";

import {
    getParameterSettingsPerformance,
    getParameterSettingsPerformanceCompare,
} from "./parameterSettingsApi.js";
import { normalizeScope } from "./parameterSettingsModel.js";

/* =================================================
   PARAMETER PERFORMANCE data controller (E-PERF-3).

   Loads the read-only observed-performance history for the selected scope and
   performs an on-demand Revision A / Revision B comparison.  It is fully
   isolated from configuration authority: a read failure never disables or
   mutates the parameter editor.
================================================= */

export function useParameterPerformance(scope = "PAPER") {
    const normalizedScope = normalizeScope(scope);
    const [performance, setPerformance] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [revisionA, setRevisionA] = useState(null);
    const [revisionB, setRevisionB] = useState(null);
    const [comparison, setComparison] = useState(null);
    const [comparisonLoading, setComparisonLoading] = useState(false);
    const [comparisonError, setComparisonError] = useState(null);

    const load = useCallback(async (target) => {
        setLoading(true);
        setError(null);
        const result = await getParameterSettingsPerformance(target);
        if (result?.ok) {
            setPerformance(result.body);
        } else {
            setPerformance(null);
            setError({ status: result?.status ?? 0 });
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        let active = true;
        (async () => {
            setLoading(true);
            setError(null);
            // A scope change invalidates any previous A/B selection.
            setRevisionA(null);
            setRevisionB(null);
            setComparison(null);
            setComparisonError(null);
            const result = await getParameterSettingsPerformance(
                normalizedScope
            );
            if (!active) return;
            if (result?.ok) {
                setPerformance(result.body);
            } else {
                setPerformance(null);
                setError({ status: result?.status ?? 0 });
            }
            setLoading(false);
        })();
        return () => {
            active = false;
        };
    }, [normalizedScope]);

    useEffect(() => {
        let active = true;
        (async () => {
            if (revisionA === null || revisionB === null) {
                setComparison(null);
                setComparisonError(null);
                return;
            }
            setComparisonLoading(true);
            setComparisonError(null);
            const result = await getParameterSettingsPerformanceCompare(
                normalizedScope,
                revisionA,
                revisionB,
            );
            if (!active) return;
            if (result?.ok) {
                setComparison(result.body);
            } else {
                setComparison(null);
                setComparisonError({ status: result?.status ?? 0 });
            }
            setComparisonLoading(false);
        })();
        return () => {
            active = false;
        };
    }, [normalizedScope, revisionA, revisionB]);

    return {
        performance,
        loading,
        error,
        revisionA,
        revisionB,
        setRevisionA,
        setRevisionB,
        comparison,
        comparisonLoading,
        comparisonError,
        reload: () => load(normalizedScope),
    };
}
