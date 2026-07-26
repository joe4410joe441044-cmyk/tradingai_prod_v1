export default function AdvisorGroundedResponse({ response }) {
    if (!response || !Array.isArray(response.groundedClaims)) return null;
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
            {response.groundedClaims.map((claim) => (
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
