export default function SupervisorActionableUnknown({ item }) {
    if (!item) return null;
    return (
        <section className="supervisor-actionable-unknown" aria-label="Unknown or unavailable information">
            <h4>Unknown / Not Available（確認できない情報）</h4>
            <p>{item.subject}</p>
            <strong>Reason（理由）</strong><p>{item.reason}</p>
            <strong>Missing Information（不足している情報）</strong><p>{item.missingInformation}</p>
            <strong>Next Step（次にすること）</strong><p>{item.safeNextStep}</p>
            <strong>Decision Impact（判断への影響）</strong><p>{item.decisionImpact}</p>
        </section>
    );
}
