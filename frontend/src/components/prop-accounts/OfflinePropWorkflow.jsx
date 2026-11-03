import { useEffect, useRef, useState } from "react";

import { createOfflineAccount, evaluateOfflineAccount, reviseOfflineAccount } from "../../features/prop-accounts/offlinePropWorkflowClient.js";
import { DEFAULT_ACCOUNT_INPUT, DEFAULT_EVALUATION_INPUT, buildEvaluationRequest, requestIsCurrent, responseMatchesScope } from "../../features/prop-accounts/offlinePropWorkflow.js";
import PropOutcomeCard from "./PropOutcomeCard.jsx";

const RULE_FIELDS = [
    ["initialBalance", "初期資本", "通貨建て。最大損失と利益目標の基準です。"],
    ["maximumLossPct", "最大損失率 (%)", "初期資本 × 割合。境界未満でBLOCK。"],
    ["dailyLossPct", "日次損失率 (%)", "日次baseline × 割合。"],
    ["profitTargetPct", "利益目標率 (%)", "balanceによる進捗。到達は合格を意味しません。"],
];
const BASELINE_FIELDS = [
    ["referenceValue", "日次baseline", "明示したtrading day開始時のequity基準。"],
    ["tradingDay", "Trading day", "UTCの日付 (YYYY-MM-DD)。"],
    ["timezone", "Timezone", "初期版はUTC固定。"],
    ["dayBoundaryLocalTime", "Reset time", "初期版は00:00:00固定。"],
];
const OBSERVATION_FIELDS = [
    ["balance", "Balance", "空欄は欠損としてUNKNOWNを維持。"],
    ["equity", "Equity", "空欄は0に補完しません。"],
    ["realizedPnl", "Realized PnL", "文字列Decimal。負数可。"],
    ["unrealizedPnl", "Unrealized PnL", "文字列Decimal。負数可。"],
    ["observedAt", "Observed at", "RFC3339。"],
    ["receivedAt", "Received at", "RFC3339。"],
    ["evaluatedAt", "Evaluated at / cutoff", "RFC3339。同じ時点をknowledge cutoffに使用。"],
];

function FieldGrid({ fields, input, onChange, errors }) {
    return <div className="cc-prop-offline__fields">{fields.map(([name, label, help]) => (
        <label key={name}>
            <span>{label}</span>
            <input
                aria-describedby={`${name}-help`}
                aria-invalid={errors?.[name] ? "true" : "false"}
                id={`offline-${name}`}
                name={name}
                onChange={(event) => onChange(name, event.target.value)}
                value={input[name]}
            />
            <small id={`${name}-help`}>{errors?.[name] ?? help}</small>
        </label>
    ))}</div>;
}

export function OfflinePropWorkflowView({
    accounts, selectedAccount, accountInput, input, status, error, result,
    onAccountInput, onCreate, onRevise, onSelect, onInput, onSubmit,
}) {
    return (
        <section aria-busy={status === "LOADING"} className="cc-prop-offline" data-testid="offline-workflow">
            <header className="cc-prop-offline__header">
                <div><span>INPUT EVALUATION MODE</span><h2>隔離synthetic口座評価</h2></div>
                <b>メモリ内のみ · 再読込で消去</b>
            </header>
            <p className="cc-prop-accounts__sample-rule">隔離デモ / 架空データ / 実口座未接続 — SYNTHETIC固定。公式HyroTraderルール、credential、取引権限は扱いません。</p>

            <fieldset data-testid="offline-account-setup">
                <legend>1. サンプル口座を作成・選択</legend>
                <div className="cc-prop-offline__fields">
                    <label><span>Label</span><input aria-describedby="label-help" aria-invalid={error?.fields?.label ? "true" : "false"} id="offline-label" name="label" onChange={(e) => onAccountInput("label", e.target.value)} value={accountInput.label} /><small id="label-help">{error?.fields?.label ?? "1–80文字の架空表示名。URL・pathは不可。"}</small></label>
                    <label><span>Platform</span><input disabled value="BYBIT_DEMO" /></label>
                    <label><span>Environment</span><input disabled value="EXTERNAL_SIMULATION" /></label>
                    <label><span>Account type</span><input disabled value="PROP" /></label>
                    <label><span>Phase</span><select aria-describedby="phase-help" aria-invalid={error?.fields?.phase ? "true" : "false"} id="offline-phase" name="phase" onChange={(e) => onAccountInput("phase", e.target.value)} value={accountInput.phase}>{["FREE_TRIAL", "CHALLENGE", "VERIFICATION", "FUNDED", "UNKNOWN"].map((value) => <option key={value}>{value}</option>)}</select><small id="phase-help">{error?.fields?.phase ?? "架空口座の評価phase。"}</small></label>
                    <label><span>Currency</span><input aria-describedby="currency-help" aria-invalid={error?.fields?.currency ? "true" : "false"} id="offline-currency" name="currency" onChange={(e) => onAccountInput("currency", e.target.value)} value={accountInput.currency} /><small id="currency-help">{error?.fields?.currency ?? "3–12文字の大文字asset code。"}</small></label>
                </div>
                <div className="cc-prop-offline__actions">
                    <button disabled={status === "LOADING"} onClick={onCreate} type="button">新しいサンプル口座を作成</button>
                    <button disabled={!selectedAccount || status === "LOADING"} onClick={onRevise} type="button">同じ口座をrevision更新</button>
                </div>
                {accounts.length > 0 && <label className="cc-prop-offline__select"><span>評価対象</span><select data-testid="offline-account-select" onChange={(e) => onSelect(e.target.value)} value={selectedAccount?.identity.account_id ?? ""}>{accounts.map((account) => <option key={account.identity.account_id} value={account.identity.account_id}>{account.label} · rev {account.identity.revision}</option>)}</select></label>}
                {selectedAccount && <dl className="cc-prop-accounts__definition-grid" data-testid="offline-account-identity">
                    <div><dt>Account ID</dt><dd>{selectedAccount.identity.account_id}</dd></div>
                    <div><dt>Revision</dt><dd>{selectedAccount.identity.revision}</dd></div>
                    <div><dt>Profile</dt><dd>SYNTHETIC / NOT OFFICIAL</dd></div>
                    <div><dt>Persistence</dt><dd>NONE</dd></div>
                </dl>}
            </fieldset>

            <fieldset disabled={!selectedAccount || status === "LOADING"} data-testid="offline-evaluation-form">
                <legend>2. 架空ルール・baseline・observation</legend>
                <h3>Rules</h3><FieldGrid errors={error?.fields} fields={RULE_FIELDS} input={input} onChange={onInput} />
                <h3>Daily baseline</h3><FieldGrid errors={error?.fields} fields={BASELINE_FIELDS} input={input} onChange={onInput} />
                <h3>Observation / evaluation time</h3><FieldGrid errors={error?.fields} fields={OBSERVATION_FIELDS} input={input} onChange={onInput} />
                <button className="cc-prop-offline__submit" onClick={onSubmit} type="button">{status === "LOADING" ? "評価中…" : "サンプル評価"}</button>
            </fieldset>

            {error && <div className="cc-prop-offline__error" data-testid="offline-error" role="alert"><strong>評価前検証失敗</strong><span>{error.code}: {error.message}</span><small>正常Outcomeは生成・表示していません。</small></div>}
            {result && <div data-testid="offline-result"><PropOutcomeCard scenario={{ status: "READY", outcome: result.outcome }} /></div>}
            <div aria-live="polite" className="cc-prop-offline__sr-only" role="status">
                {status === "LOADING" ? "隔離評価を実行中です" : status === "READY" ? "隔離評価結果を更新しました" : ""}
            </div>
        </section>
    );
}

export default function OfflinePropWorkflow() {
    const [accounts, setAccounts] = useState([]);
    const [selectedId, setSelectedId] = useState("");
    const [accountInput, setAccountInput] = useState({ ...DEFAULT_ACCOUNT_INPUT });
    const [input, setInput] = useState({ ...DEFAULT_EVALUATION_INPUT });
    const [status, setStatus] = useState("IDLE");
    const [error, setError] = useState(null);
    const [result, setResult] = useState(null);
    const generation = useRef(0);
    const sequence = useRef(0);
    const activeController = useRef(null);
    const evaluationToken = useRef(null);
    const mounted = useRef(true);
    const selectedAccount = accounts.find((account) => account.identity.account_id === selectedId) ?? null;

    useEffect(() => () => {
        mounted.current = false;
        activeController.current?.abort();
        activeController.current = null;
    }, []);

    const invalidate = () => {
        generation.current += 1;
        activeController.current?.abort();
        activeController.current = null;
        evaluationToken.current = null;
        setResult(null); setError(null); setStatus("IDLE");
    };
    const request = async (operation) => {
        activeController.current?.abort();
        const controller = new AbortController();
        activeController.current = controller;
        setStatus("LOADING"); setError(null);
        try {
            const response = await operation(controller.signal);
            if (!requestIsCurrent(controller, activeController.current, mounted.current)) return null;
            activeController.current = null;
            return response;
        } catch (failure) {
            if (requestIsCurrent(controller, activeController.current, mounted.current) && failure?.name !== "AbortError") {
                activeController.current = null;
                setError({ code: failure?.code ?? "OFFLINE_BOUNDARY_UNAVAILABLE", message: failure?.message ?? "隔離評価entryを確認してください", fields: failure?.fields ?? {} });
                setStatus("ERROR");
            }
            return null;
        }
    };
    const create = async () => {
        invalidate();
        const requestId = `cc4a-${++sequence.current}`;
        const response = await request((signal) => createOfflineAccount({ requestId, ...accountInput }, signal));
        if (!response || !mounted.current) return;
        setAccounts((current) => [...current, response.account]);
        setSelectedId(response.account.identity.account_id); setStatus("IDLE");
    };
    const revise = async () => {
        if (!selectedAccount) return;
        invalidate();
        const requestId = `cc4a-${++sequence.current}`;
        const response = await request((signal) => reviseOfflineAccount({ requestId, accountId: selectedAccount.identity.account_id, identityRevision: selectedAccount.identity.revision, ...accountInput }, signal));
        if (!response || !mounted.current) return;
        setAccounts((current) => current.map((item) => item.identity.account_id === response.account.identity.account_id ? response.account : item));
        setStatus("IDLE");
    };
    const submit = async () => {
        if (!selectedAccount || evaluationToken.current) return;
        const token = {};
        evaluationToken.current = token;
        const requestId = `cc4a-${++sequence.current}`;
        const submittedGeneration = generation.current;
        const expected = { requestId, accountId: selectedAccount.identity.account_id, identityRevision: selectedAccount.identity.revision, generation: submittedGeneration };
        const payload = buildEvaluationRequest({ requestId, account: selectedAccount, input });
        try {
            const response = await request((signal) => evaluateOfflineAccount(payload, signal));
            if (!response || !mounted.current || !responseMatchesScope(response, { ...expected, currentGeneration: generation.current })) return;
            setResult(response); setStatus("READY");
        } finally {
            if (evaluationToken.current === token) evaluationToken.current = null;
        }
    };

    return <OfflinePropWorkflowView
        accountInput={accountInput} accounts={accounts} error={error} input={input}
        onAccountInput={(name, value) => { invalidate(); setAccountInput((current) => ({ ...current, [name]: value })); }}
        onCreate={create}
        onInput={(name, value) => { invalidate(); setInput((current) => ({ ...current, [name]: value })); }}
        onRevise={revise} onSelect={(value) => { invalidate(); setSelectedId(value); }}
        onSubmit={submit} result={result} selectedAccount={selectedAccount} status={status}
    />;
}
