import { useCallback, useEffect, useState } from "react";

import {
    getParameterSettingsConfiguration,
    getParameterSettingsEffective,
    getParameterSettingsRuntime,
    getParameterSettingsSchema,
    getParameterSettingsStatus,
    updateParameterSettingsConfiguration,
} from "./parameterSettingsApi.js";
import {
    applyDraftChange,
    draftFromConfiguration,
    draftHasErrors,
    normalizeScope,
    performSave,
} from "./parameterSettingsModel.js";

/* =================================================
   PARAMETER SETTINGS data controller.

   Loads the canonical schema + CONFIGURED / EFFECTIVE / RUNTIME / STATUS
   reads for the selected scope and exposes a single save action backed by
   the one authenticated write endpoint.  It never touches bot lifecycle,
   order, leverage, quantity, symbol or mode authority.
================================================= */

export function useParameterSettings(initialScope = "PAPER") {
    const [scope, setScopeState] = useState(normalizeScope(initialScope));
    const [schema, setSchema] = useState(null);
    const [configuration, setConfiguration] = useState(null);
    const [effective, setEffective] = useState(null);
    const [runtime, setRuntime] = useState(null);
    const [status, setStatus] = useState(null);
    const [draft, setDraft] = useState({});
    const [loading, setLoading] = useState(true);
    const [saveState, setSaveState] = useState({ phase: "IDLE" });
    const [conflict, setConflict] = useState(null);

    const loadScope = useCallback(async (nextScope) => {
        setLoading(true);
        const [configurationResult, effectiveResult, runtimeResult] = (
            await Promise.all([
                getParameterSettingsConfiguration(nextScope),
                getParameterSettingsEffective(nextScope),
                getParameterSettingsRuntime(nextScope),
            ])
        );
        const configurationBody = configurationResult?.ok
            ? configurationResult.body
            : null;
        setConfiguration(configurationBody);
        setEffective(effectiveResult?.ok ? effectiveResult.body : null);
        setRuntime(runtimeResult?.ok ? runtimeResult.body : null);
        setDraft(draftFromConfiguration(configurationBody));
        setLoading(false);
    }, []);

    useEffect(() => {
        let active = true;
        (async () => {
            const [schemaResult, statusResult] = await Promise.all([
                getParameterSettingsSchema(),
                getParameterSettingsStatus(),
            ]);
            if (!active) return;
            if (schemaResult?.ok) setSchema(schemaResult.body);
            if (statusResult?.ok) setStatus(statusResult.body);
        })();
        return () => {
            active = false;
        };
    }, []);

    useEffect(() => {
        loadScope(scope);
    }, [scope, loadScope]);

    const setScope = useCallback((nextScope) => {
        setSaveState({ phase: "IDLE" });
        setConflict(null);
        setScopeState(normalizeScope(nextScope));
    }, []);

    const changeDraft = useCallback((name, value) => {
        setDraft((current) => applyDraftChange(current, name, value));
        setSaveState({ phase: "IDLE" });
        setConflict(null);
    }, []);

    const save = useCallback(async ({ confirmLive = false } = {}) => {
        const fieldErrors = draftHasErrors(schema, draft);
        if (Object.keys(fieldErrors).length > 0) {
            setSaveState({ phase: "INVALID", fieldErrors });
            return { ok: false, reason: "FRONTEND_VALIDATION" };
        }
        setSaveState({ phase: "SAVING" });
        const result = await performSave({
            scope,
            parameters: draft,
            expectedRevision: configuration?.configuredRevision,
            confirmLive,
            schema,
            api: {
                updateConfiguration: updateParameterSettingsConfiguration,
            },
        });
        if (result.ok) {
            setSaveState({
                phase: "SAVED",
                warnings: result.body?.warnings ?? [],
            });
            await loadScope(scope);
            return { ok: true, body: result.body };
        }
        if (result.status === 409) {
            setConflict(result.body);
            setSaveState({ phase: "CONFLICT" });
            return { ok: false, reason: "REVISION_CONFLICT", body: result.body };
        }
        if (result.status === 422) {
            setSaveState({ phase: "INVALID", backend: result.body });
            return { ok: false, reason: "VALIDATION_ERROR", body: result.body };
        }
        setSaveState({ phase: "ERROR", message: result.message });
        return { ok: false, reason: "ERROR", body: result.body };
    }, [scope, draft, schema, configuration, loadScope]);

    return {
        scope,
        setScope,
        schema,
        configuration,
        effective,
        runtime,
        status,
        draft,
        changeDraft,
        loading,
        saveState,
        save,
        conflict,
    };
}
