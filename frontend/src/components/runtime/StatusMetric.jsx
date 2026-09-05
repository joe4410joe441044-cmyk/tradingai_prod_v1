export default function StatusMetric({
    label,
    value,
    testId,
    tone = "neutral",
}) {
    return (
        <div className="semantic-metric">
            <span className="semantic-metric-label">{label}</span>
            <span
                className={`semantic-metric-value tone-${tone}`}
                data-testid={testId}
            >
                {value}
            </span>
        </div>
    );
}
