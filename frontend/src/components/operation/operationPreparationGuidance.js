// WF-1: map the authoritative readiness values to actionable operator
// guidance. This is presentation-only and NEVER re-derives readiness or
// changes the fail-closed START gate. Returns every applicable blocker.
export const deriveOperationBlockGuidance = ({
    settings,
    config,
    emergencyReadiness,
    positionState,
    orderAuthority,
    selectionReadiness,
    selectionRuntime,
    selectedRuntimeSymbol,
    startMmReadiness,
    mmEntryReadiness,
    governanceReadiness,
    executionReadiness,
    leverageReadiness,
    emergencyState,
    position,
    pendingOrder,
    governanceStatus,
    realOrderAllowed,
    executionEnabled,
    mmConfiguration,
    mmDraft,
}) => {
    const number = (state) => {
        if (String(state).toUpperCase() === "READY") return "READY";
        if (["BLOCKED", "ERROR", "FAILED", "LOCKED", "UNAVAILABLE"].includes(
            String(state).toUpperCase(),
        )) return "BLOCKED";
        if (["WAITING", "PENDING", "PROCESSING", "STARTING", "ON HOLD"].includes(
            String(state).toUpperCase(),
        )) return "WAITING";
        return String(state ?? "UNKNOWN");
    };
    const current = (value, fallback = "UNKNOWN") => (
        value === null || value === undefined || value === "" ? fallback : String(value)
    );
    const notBlocking = (value) => (
        ["READY", "SAFE", "FLAT", "NOT_RELEVANT"].includes(number(value))
    );

    const guidance = [];
    const push = (entry) => {
        if (!entry) return;
        guidance.push({
            ...entry,
            status: number(entry.status),
            current: current(entry.current),
            required: current(entry.required),
        });
    };

    if (!notBlocking(emergencyReadiness)) {
        push({
            id: "emergency",
            label: "Emergency（緊急停止）",
            status: emergencyReadiness,
            current: emergencyState,
            required: "READY",
            section: "⑥ SAFETY / START READINESS",
            en: "Emergency stop authority must be READY before START.",
            ja: "緊急停止がREADYになるまでSTARTできません。",
            fix: "⑥ Emergency を READY に戻す / Restore Emergency to READY",
        });
    }
    if (!notBlocking(positionState)) {
        push({
            id: "position",
            label: "Position（ポジション）",
            status: positionState,
            current: position,
            required: "FLAT (no open position)",
            section: "⑥ SAFETY / START READINESS",
            en: "Position must be FLAT before START.",
            ja: "ポジションはFLATである必要があります。",
            fix: "⑥ ポジションをFLATにしてからSTART / Flatten the position before START",
        });
    }
    if (!notBlocking(orderAuthority)) {
        push({
            id: "pendingOrder",
            label: "Pending Order Authority（保留注文権限）",
            status: orderAuthority,
            current: pendingOrder,
            required: "SAFE (no pending order)",
            section: "⑥ SAFETY / START READINESS",
            en: "Pending order authority must be SAFE (no pending order) before START.",
            ja: "保留注文がない状態(SAFE)である必要があります。",
            fix: "⑥ 保留注文が解消されるまで待つ / Wait for pending orders to settle",
        });
    }
    if (!notBlocking(selectionReadiness)) {
        const isAuto = settings.selectionMode === "AUTO";
        push({
            id: "marketSelection",
            label: "Market Selection（市場選択）",
            status: selectionReadiness,
            current: isAuto
                ? `AUTO runtime=${current(selectionRuntime)} candidate=${current(selectedRuntimeSymbol, "none")}`
                : current(config.displaySymbol),
            required: isAuto
                ? "READY AUTO candidate (or choose MANUAL)"
                : "READY (valid symbol)",
            section: "② MARKET SELECTION",
            en: isAuto
                ? "AUTO candidate runtime is not ready. Choose a MANUAL symbol or wait for the AUTO candidate."
                : "Manual symbol must be a valid, ready market selection.",
            ja: isAuto
                ? "AUTO候補が決定していません。MANUALを選ぶかAUTO候補を待ってください。"
                : "有効なシンボルを選択してください。",
            fix: "② MARKET SELECTION で MANUAL シンボルを選ぶ / ② choose MANUAL symbol or fix AUTO readiness",
        });
    }
    if (!notBlocking(startMmReadiness)) {
        const draftRisk = mmDraft ? current(mmDraft.riskPerTradePercent) : "—";
        const draftDd = mmDraft ? current(mmDraft.maximumDrawdownPercent) : "—";
        const savedRisk = mmConfiguration ? current(mmConfiguration.riskPerTradePercent) : "—";
        const savedDd = mmConfiguration ? current(mmConfiguration.maximumDrawdownPercent) : "—";
        const divergence = (
            mmDraft && mmConfiguration
            && (String(mmDraft.riskPerTradePercent) !== String(mmConfiguration.riskPerTradePercent)
                || String(mmDraft.maximumDrawdownPercent) !== String(mmConfiguration.maximumDrawdownPercent))
        );
        push({
            id: "mmStart",
            label: "MM START CONFIG（開始設定）",
            status: startMmReadiness,
            current: `draft risk=${draftRisk}% dd=${draftDd}% | saved risk=${savedRisk}% dd=${savedDd}%`,
            required: "READY (valid saved risk + max drawdown)",
            section: "③ MONEY MANAGEMENT",
            en: divergence
                ? "MM draft is unsaved and differs from the saved config that is actually sent to START. Save MM to align."
                : "MM START config must be a valid saved risk / max-drawdown configuration.",
            ja: divergence
                ? "MMドラフトが未保存です。STARTには保存済み値が送られます。Save MMしてください。"
                : "有効なリスク/最大ドローダウン設定を保存してください。",
            fix: "③ MONEY MANAGEMENT で設定を整え Save MM / ③ reconcile and Save MM",
        });
    }
    if (!notBlocking(mmEntryReadiness?.state)) {
        push({
            id: "entryPermission",
            label: "Entry Permission（エントリー権限）",
            status: mmEntryReadiness?.state,
            current: current(mmEntryReadiness?.label),
            required: "READY / ENTRY ALLOWED",
            section: "⑥ SAFETY / START READINESS",
            en: "Entry permission is not allowed (runtime MM guard). Resolve the MM recovery/hold before START.",
            ja: "エントリー権限がありません。MMガードを解除してください。",
            fix: "③/⑥ MM の hold/recovery を解消 / resolve MM recovery or hold",
        });
    }
    if (!notBlocking(governanceReadiness)) {
        push({
            id: "governance",
            label: "Governance（ガバナンス）",
            status: governanceReadiness,
            current: governanceStatus,
            required: "READY / OK / ALLOWED",
            section: "⑥ SAFETY / START READINESS",
            en: "Governance must be READY before START.",
            ja: "ガバナンスがREADYになるまでSTARTできません。",
            fix: "⑥ Governance を READY にする / wait for Governance to be ready",
        });
    }
    if (!notBlocking(executionReadiness)) {
        push({
            id: "execution",
            label: "Execution（執行）",
            status: executionReadiness,
            current: `realOrder=${realOrderAllowed ? "ALLOWED" : "DISABLED"} execution=${executionEnabled ? "ENABLED" : "DISABLED"}`,
            required: "SAFE / DISABLED",
            section: "⑥ SAFETY / START READINESS",
            en: "Execution / real-order authority must be disabled before a fresh START.",
            ja: "実行/実注文権限が無効である必要があります。",
            fix: "⑥ 実行権限を無効にしてからSTART / disable execution before START",
        });
    }
    if (!notBlocking(leverageReadiness)) {
        push({
            id: "leverage",
            label: "Leverage Authority（レバレッジ権限）",
            status: leverageReadiness,
            current: `Requested: ${settings.requestedLeverage}x`,
            required: `MM Limit: ${mmConfiguration?.maximumLeverage ?? "n/a"}x`,
            section: "④ TRADE / EXECUTION",
            en: "Requested leverage exceeds MM leverage limit.",
            ja: "要求レバレッジがMM上限を超えています。",
            fix: "④ TRADE / EXECUTION で Requested Leverage を MM上限以下に変更 / Set Requested Leverage to MM limit or less",
        });
    }

    return guidance;
};
