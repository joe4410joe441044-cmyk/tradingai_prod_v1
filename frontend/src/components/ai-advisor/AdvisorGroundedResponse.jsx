export default function AdvisorGroundedResponse({ response }) {
    if (!response || !Array.isArray(response.groundedClaims)) return null;
    const actionableUnknowns = Array.isArray(response.actionableUnknowns)
        ? response.actionableUnknowns
        : [];
    const actionableIds = new Set(
        actionableUnknowns.map((item) => item.unknownId),
    );
    return (
        <section aria-label="Grounded advisor response"
            className="advisor-grounding">
            {response.conclusion && (
                <div>
                    <strong>Conclusion</strong>
                    <p>{response.conclusion}</p>
                </div>
            )}
            {response.responseCategory === "SAFETY_REFUSAL" && (
                <div className="advisor-grounding__refusal">
                    <strong>Refusal</strong>
                    <p>{response.refusalCategory || "SAFETY_REFUSAL"}</p>
                </div>
            )}
            {actionableUnknowns.map((item) => (
                <article className="advisor-grounding__unknown" key={item.unknownId}>
                    <strong>Unknown / Not Available（確認できない情報）</strong>
                    <p>{item.subject}</p>
                    <dl>
                        <div>
                            <dt>Reason（理由）</dt>
                            <dd>{item.reason}</dd>
                        </div>
                        <div>
                            <dt>Missing Information（不足している情報）</dt>
                            <dd>{item.missingInformation}</dd>
                        </div>
                        <div>
                            <dt>Next Step（次にすること）</dt>
                            <dd>{item.safeNextStep}</dd>
                        </div>
                        <div>
                            <dt>Decision Impact（判断への影響）</dt>
                            <dd>{item.decisionImpact}</dd>
                        </div>
                    </dl>
                    <small>Operational Effect: {item.operationalEffect}</small>
                </article>
            ))}
            {response.groundedClaims.filter((claim) => (
                claim.claimType !== "UNKNOWN" || !actionableIds.has(claim.claimId)
            )).map((claim) => (
                <article key={claim.claimId}>
                    <strong>{claim.claimType}</strong>
                    <p>{claim.text}</p>
                    <small>
                        Freshness: {claim.freshness} · Uncertainty: {claim.uncertainty}
                    </small>
                </article>
            ))}
            {response.citations?.map((citation) => (
                <div className="advisor-grounding__citation"
                    key={citation.sourceId}>
                    <strong>Citation</strong>
                    <p>{citation.displayTitle}</p>
                    <small>
                        Version {citation.version} · {citation.freshness}
                    </small>
                </div>
            ))}
            {response.limitations?.length > 0 && (
                <div>
                    <strong>Limitations</strong>
                    {response.limitations.map((limitation) => (
                        <p key={limitation}>{limitation}</p>
                    ))}
                </div>
            )}
            {response.safeAlternative && (
                <div>
                    <strong>Safe Alternative</strong>
                    <p>{response.safeAlternative}</p>
                </div>
            )}
        </section>
    );
}
