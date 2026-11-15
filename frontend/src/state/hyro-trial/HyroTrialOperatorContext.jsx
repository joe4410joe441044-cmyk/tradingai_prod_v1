/* eslint-disable react-refresh/only-export-components */
import {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useRef,
    useState,
} from "react";

import {
    EMPTY_HYRO_SETTINGS,
    HYRO_TRIAL_OPERATOR_ENABLED,
    deriveHyroCoreReference,
    deriveHyroTrialAccountStatus,
    deriveHyroTrialReadiness,
    DEFAULT_HYRO_TRIAL_CLIENT,
    validateHyroTrialSettings,
} from "../../features/prop-accounts/hyroTrialOperatorFeature.js";

const HyroTrialOperatorContext = createContext(null);

const initialSimulation = Object.freeze({
    state: "STOPPED",
    accountId: null,
    accountName: null,
    startedAt: null,
    stoppedAt: null,
});

const staleRefreshState = () => ({
    state: "SNAPSHOT_STALE",
    previousAt: null,
    updatedAt: null,
    error: null,
});

export function HyroTrialOperatorProvider({
    children,
    client = DEFAULT_HYRO_TRIAL_CLIENT,
    enabled = HYRO_TRIAL_OPERATOR_ENABLED,
    now = () => new Date().toISOString(),
}) {
    const [accountMode, setAccountMode] = useState("KUCOIN");
    const [connection, setConnection] = useState({ state: "NOT_CHECKED", error: null });
    const [challengeList, setChallengeList] = useState({ state: "IDLE", quality: "UNKNOWN", items: [], error: null });
    const [selectedChallengeId, setSelectedChallengeId] = useState("");
    const [drafts, setDrafts] = useState({});
    const [savedSettings, setSavedSettings] = useState({});
    const [simulation, setSimulation] = useState(initialSimulation);
    const [actionError, setActionError] = useState(null);
    const [counts, setCounts] = useState({ externalNetworkCalls: 0, orderCalls: 0 });
    const [refreshState, setRefreshState] = useState({ state: "SNAPSHOT_STALE", previousAt: null, updatedAt: null, error: null });
    const modeRef = useRef(accountMode);
    const requestGeneration = useRef(0);
    const lifecycleToken = useRef(null);
    const refreshToken = useRef(null);

    const selectAccountMode = useCallback((mode) => {
        if (!enabled || !["KUCOIN", "HYRO"].includes(mode)) return;
        requestGeneration.current += 1;
        refreshToken.current = null;
        modeRef.current = mode;
        setRefreshState(staleRefreshState());
        setAccountMode(mode);
        setConnection((current) => current.state === "CHECKING"
            ? { state: "NOT_CHECKED", error: null }
            : current);
        setChallengeList((current) => current.state === "LOADING"
            ? { state: "IDLE", quality: "UNKNOWN", items: current.items, error: null }
            : current);
        setActionError(null);
    }, [enabled]);

    const checkConnection = useCallback(async () => {
        if (!enabled || modeRef.current !== "HYRO" || connection.state === "CHECKING") return;
        const generation = ++requestGeneration.current;
        setConnection({ state: "CHECKING", error: null });
        try {
            const result = await client.checkConnection();
            if (generation !== requestGeneration.current || modeRef.current !== "HYRO") return;
            setConnection({ state: result?.state === "CONNECTED_SAMPLE" ? "CONNECTED_SAMPLE" : "FAILED", error: null });
            setCounts((current) => ({
                externalNetworkCalls: current.externalNetworkCalls + Number(result?.externalNetworkCalls || 0),
                orderCalls: current.orderCalls + Number(result?.orderCalls || 0),
            }));
        } catch {
            if (generation !== requestGeneration.current || modeRef.current !== "HYRO") return;
            setConnection({ state: "FAILED", error: "隔離サンプル接続を確認できませんでした" });
        }
    }, [client, connection.state, enabled]);

    const loadChallenges = useCallback(async () => {
        if (!enabled || modeRef.current !== "HYRO" || challengeList.state === "LOADING") return;
        const generation = ++requestGeneration.current;
        refreshToken.current = null;
        setRefreshState(staleRefreshState());
        setChallengeList({ state: "LOADING", quality: "UNKNOWN", items: [], error: null });
        try {
            const result = await client.listChallenges();
            if (generation !== requestGeneration.current || modeRef.current !== "HYRO") return;
            const items = Array.isArray(result?.challenges) ? result.challenges : [];
            const quality = result?.quality === "COMPLETE_SAMPLE" ? "COMPLETE_SAMPLE" : "INCOMPLETE";
            setChallengeList({
                state: quality !== "COMPLETE_SAMPLE" ? "INCOMPLETE" : items.length ? "READY" : "EMPTY",
                quality,
                items,
                error: quality === "COMPLETE_SAMPLE" ? null : "一覧の完全性を確認できません",
            });
            setCounts((current) => ({
                externalNetworkCalls: current.externalNetworkCalls + Number(result?.externalNetworkCalls || 0),
                orderCalls: current.orderCalls + Number(result?.orderCalls || 0),
            }));
        } catch {
            if (generation !== requestGeneration.current || modeRef.current !== "HYRO") return;
            setChallengeList({ state: "FAILED", quality: "FAILED", items: [], error: "チャレンジ一覧を取得できませんでした" });
        }
    }, [challengeList.state, client, enabled]);

    const selectedChallenge = challengeList.items.find(({ id }) => id === selectedChallengeId) ?? null;
    const selectedDraft = selectedChallengeId
        ? drafts[selectedChallengeId] ?? EMPTY_HYRO_SETTINGS
        : EMPTY_HYRO_SETTINGS;
    const selectedSavedSettings = selectedChallengeId ? savedSettings[selectedChallengeId] ?? null : null;

    const selectChallenge = useCallback((challengeId) => {
        const exists = challengeList.items.some(({ id }) => id === challengeId);
        requestGeneration.current += 1;
        refreshToken.current = null;
        setRefreshState(staleRefreshState());
        setSelectedChallengeId(exists ? challengeId : "");
        setActionError(null);
    }, [challengeList.items]);

    const updateDraft = useCallback((name, value) => {
        if (!selectedChallengeId || !Object.hasOwn(EMPTY_HYRO_SETTINGS, name)) return;
        setDrafts((current) => ({
            ...current,
            [selectedChallengeId]: {
                ...(current[selectedChallengeId] ?? EMPTY_HYRO_SETTINGS),
                [name]: value,
            },
        }));
        setActionError(null);
    }, [selectedChallengeId]);

    const saveSelectedSettings = useCallback(() => {
        if (!selectedChallengeId) {
            setActionError("チャレンジを選択してください");
            return false;
        }
        const validation = validateHyroTrialSettings(selectedDraft);
        if (!validation.valid) {
            setActionError(validation.errors.join(" / "));
            return false;
        }
        setSavedSettings((current) => ({ ...current, [selectedChallengeId]: { ...selectedDraft } }));
        setActionError(null);
        return true;
    }, [selectedChallengeId, selectedDraft]);

    const readiness = deriveHyroTrialReadiness({
        selectedChallenge,
        savedSettings: selectedSavedSettings,
        simulation,
    });

    const startSimulation = useCallback(async () => {
        if (!selectedChallenge || !selectedSavedSettings || readiness.state !== "READY" || lifecycleToken.current) return false;
        const token = {};
        lifecycleToken.current = token;
        setActionError(null);
        setSimulation((current) => ({ ...current, state: "STARTING" }));
        try {
            const result = await client.startSimulation({
                accountId: selectedChallenge.id,
                settings: selectedSavedSettings,
            });
            if (lifecycleToken.current !== token) return false;
            if (result?.state !== "RUNNING") throw new Error("unexpected state");
            setCounts((current) => ({ ...current, orderCalls: current.orderCalls + Number(result?.orderCalls || 0) }));
            setSimulation({
                state: "RUNNING",
                accountId: selectedChallenge.id,
                accountName: selectedChallenge.accountName,
                startedAt: now(),
                stoppedAt: null,
            });
            return true;
        } catch {
            if (lifecycleToken.current === token) {
                setSimulation(initialSimulation);
                setActionError("シミュレーションSTARTに失敗しました。再操作できます");
            }
            return false;
        } finally {
            if (lifecycleToken.current === token) lifecycleToken.current = null;
        }
    }, [client, now, readiness.state, selectedChallenge, selectedSavedSettings]);

    const stopSimulation = useCallback(async () => {
        if (simulation.state !== "RUNNING" || lifecycleToken.current) return false;
        const token = {};
        const running = simulation;
        lifecycleToken.current = token;
        setActionError(null);
        setSimulation((current) => ({ ...current, state: "STOPPING" }));
        try {
            const result = await client.stopSimulation({ accountId: running.accountId });
            if (lifecycleToken.current !== token) return false;
            if (result?.state !== "STOPPED") throw new Error("unexpected state");
            setCounts((current) => ({ ...current, orderCalls: current.orderCalls + Number(result?.orderCalls || 0) }));
            setSimulation({ ...running, state: "STOPPED", stoppedAt: now() });
            return true;
        } catch {
            if (lifecycleToken.current === token) {
                setSimulation(running);
                setActionError("シミュレーションSTOPに失敗しました。再操作できます");
            }
            return false;
        } finally {
            if (lifecycleToken.current === token) lifecycleToken.current = null;
        }
    }, [client, now, simulation]);

    const refreshIssuedProgress = useCallback(async () => {
        if (
            selectedChallenge?.readKind !== "ISSUED_READ_ONLY"
            || refreshToken.current
            || typeof client.refreshIssuedProgress !== "function"
        ) return false;
        const token = {};
        const generation = requestGeneration.current;
        const challengeId = selectedChallenge.id;
        const previousAt = selectedChallenge.updatedAt;
        let settled = false;
        refreshToken.current = token;
        setRefreshState({ state: "REFRESHING", previousAt, updatedAt: null, error: null });
        try {
            const result = await client.refreshIssuedProgress();
            if (
                refreshToken.current !== token
                || generation !== requestGeneration.current
                || modeRef.current !== "HYRO"
                || selectedChallengeId !== challengeId
            ) return false;
            if (!result?.ok || result.challenge?.id !== challengeId) {
                settled = true;
                setRefreshState({
                    state: "FAILED_STALE",
                    previousAt,
                    updatedAt: null,
                    error: result?.code || "HYRO_TRIAL_REFRESH_FAILED",
                });
                return false;
            }
            settled = true;
            setChallengeList((current) => ({
                ...current,
                quality: result.challenge.dataQuality,
                items: current.items.map((item) => item.id === challengeId ? result.challenge : item),
            }));
            setRefreshState({
                state: result.challenge.dataQuality === "PARTIAL" ? "PARTIAL" : "SUCCESS",
                previousAt,
                updatedAt: result.challenge.updatedAt,
                error: null,
            });
            return true;
        } catch {
            if (refreshToken.current === token) {
                settled = true;
                setRefreshState({
                    state: "FAILED_STALE",
                    previousAt,
                    updatedAt: null,
                    error: "HYRO_TRIAL_REFRESH_FAILED",
                });
            }
            return false;
        } finally {
            if (refreshToken.current === token) {
                refreshToken.current = null;
                if (!settled) setRefreshState(staleRefreshState());
            }
        }
    }, [client, selectedChallenge, selectedChallengeId]);

    const value = useMemo(() => ({
        enabled,
        accountMode,
        selectAccountMode,
        connection,
        checkConnection,
        challengeList,
        loadChallenges,
        selectedChallengeId,
        selectedChallenge,
        selectChallenge,
        selectedDraft,
        selectedSavedSettings,
        updateDraft,
        saveSelectedSettings,
        readiness,
        refreshState,
        refreshIssuedProgress,
        simulation,
        startSimulation,
        stopSimulation,
        actionError,
        counts,
        accountStatus: deriveHyroTrialAccountStatus(selectedChallenge),
        coreReference: deriveHyroCoreReference(selectedChallenge),
        realHyroExecutionEnabled: false,
    }), [
        accountMode, actionError, challengeList, checkConnection, connection, counts,
        refreshIssuedProgress, refreshState,
        enabled, loadChallenges, readiness, saveSelectedSettings, selectAccountMode,
        selectChallenge, selectedChallenge, selectedChallengeId, selectedDraft,
        selectedSavedSettings, simulation, startSimulation, stopSimulation, updateDraft,
    ]);

    return <HyroTrialOperatorContext.Provider value={value}>{children}</HyroTrialOperatorContext.Provider>;
}

export function useHyroTrialOperator() {
    const context = useContext(HyroTrialOperatorContext);
    if (!context) throw new Error("HyroTrialOperatorProvider is required");
    return context;
}
