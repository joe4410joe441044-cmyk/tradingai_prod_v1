export default function PropOutcomeCard({ scenario }) {
    if (scenario.status === "PRE_EVALUATION_REJECTED") {
        return (
            <section className="cc-prop-accounts__card cc-prop-accounts__outcome" data-testid="outcome-card">
                <header className="cc-prop-accounts__card-header"><div><span>SYNTHETIC EVALUATION</span><h2>評価前検証失敗</h2></div><b>REJECTED</b></header>
                <p className="cc-prop-accounts__missing">{scenario.rejection.errorCode}: {scenario.rejection.message}</p>
                <p>Complete Outcomeは生成されていません。検証失敗をUNKNOWNの計算結果へ捏造していません。</p>
            </section>
        );
    }
    if (scenario.status !== "READY") {
        return <section className="cc-prop-accounts__card cc-prop-accounts__outcome" data-testid="outcome-card"><h2>評価fixtureを安全に表示できません</h2><p>{scenario.errorCode}</p></section>;
    }
    const { outcome } = scenario;
    const { calculation, coverage, references } = outcome;
    return (
        <section className="cc-prop-accounts__card cc-prop-accounts__outcome" data-testid="outcome-card">
            <header className="cc-prop-accounts__card-header">
                <div><span>SYNTHETIC EVALUATION</span><h2>計算結果 — {calculation.overallState}</h2></div>
                <b className="cc-prop-accounts__badge cc-prop-accounts__badge--warning">計算上の適合 ≠ 取引可能</b>
            </header>
            <p className="cc-prop-accounts__sample-rule">historical / synthetic fixture — 実口座未接続。PASSや目標到達はChallenge合格・READY・実行権限を意味しません。</p>
            <div className="cc-prop-accounts__outcome-summary" data-testid="outcome-summary">
                <div><span>Result</span><strong>{calculation.overallState}</strong></div>
                <div><span>Candidate</span><strong>{calculation.candidateStatus}</strong></div>
                <div><span>Coverage</span><strong>{coverage.completeness}</strong></div>
                <div><span>Execution</span><strong className="is-disabled">DISABLED</strong></div>
            </div>
            <dl className="cc-prop-accounts__definition-grid">
                <div><dt>Evaluated at</dt><dd>{outcome.evaluatedAt}</dd></div>
                <div><dt>Knowledge cutoff</dt><dd>{outcome.knowledgeCutoffAt}</dd></div>
                <div><dt>Snapshot</dt><dd>{references.snapshotId}</dd></div>
                <div><dt>Baseline</dt><dd>{references.baselineId ?? "なし"}</dd></div>
                <div><dt>Observation</dt><dd>{references.observationId}</dd></div>
                <div><dt>Purpose</dt><dd>{outcome.purpose}</dd></div>
            </dl>
            <div className="cc-prop-accounts__rule-grid" data-testid="outcome-rule-results">
                {calculation.ruleResults.map((result) => (
                    <article key={result.ruleCode}>
                        <span>{result.ruleCode}</span><strong>{result.state}</strong>
                        <dl>
                            <div><dt>閾値</dt><dd>{result.threshold ?? "不明"} {result.unit}</dd></div>
                            <div><dt>計算値</dt><dd>{result.actual ?? "不明"} {result.unit}</dd></div>
                            <div><dt>残余 / progress</dt><dd>{result.headroom ?? "不明"} {result.unit}</dd></div>
                            <div><dt>Reason</dt><dd>{result.reasonCode ?? "なし"}</dd></div>
                        </dl>
                    </article>
                ))}
            </div>
            <details data-testid="outcome-evidence-details">
                <summary>根拠・coverage不足理由を開く</summary>
                <dl className="cc-prop-accounts__definition-grid">
                    <div><dt>Coverage reasons</dt><dd>{coverage.unknownReasonCodes.join(" / ") || "なし"}</dd></div>
                    <div><dt>Unknown rules</dt><dd>{calculation.unknownRuleCodes.join(" / ") || "なし"}</dd></div>
                    <div><dt>Blocking rules</dt><dd>{calculation.blockingRuleCodes.join(" / ") || "なし"}</dd></div>
                    <div><dt>Evidence link</dt><dd>{references.evidenceLinkId}</dd></div>
                    <div><dt>Validation scope</dt><dd>{outcome.provenanceValidation.scope}</dd></div>
                    <div><dt>Authority reason</dt><dd>{outcome.authority.reasonCode}</dd></div>
                </dl>
            </details>
        </section>
    );
}
