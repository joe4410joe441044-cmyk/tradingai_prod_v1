import AdvisorRuntimeStatus from "../components/ai-advisor/AdvisorRuntimeStatus";
import AdvisorConversation from "../components/ai-advisor/AdvisorConversation";
import useAdvisorRuntime from "../features/ai-advisor/runtime/useAdvisorRuntime";

export default function AIAdvisorPage() {
    const runtime = useAdvisorRuntime();
    const runtimeLabel = runtime.connectionState === "CONNECTED"
        ? "Connected"
        : runtime.connectionState === "REFRESHING"
            ? "Refreshing"
            : runtime.connectionState === "DEGRADED"
                ? "Degraded"
                : "Not Connected";
    const apiLabel = runtime.data
        ? "Ready"
        : runtime.connectionState === "DISCONNECTED"
            ? "Unavailable"
            : "Connecting";

    return (
        <main className="ai-advisor-page">
            <header className="ai-advisor-page__header">
                <div className="ai-advisor-page__heading">
                    <h1>AI ADVISOR</h1>
                    <p>TradingAI Intelligent Assistant</p>
                </div>

                <div
                    aria-label="AI Advisor system status"
                    className="ai-advisor-page__status-group"
                >
                    <span className="ai-advisor-page__status ai-advisor-page__status--ready">
                        Platform Ready
                    </span>
                    <span className="ai-advisor-page__status">
                        <strong>AI Provider</strong> Not Configured
                    </span>
                    <span className={`ai-advisor-page__status ${
                        runtime.data ? "ai-advisor-page__status--ready" : ""
                    }`}>
                        <strong>API</strong> {apiLabel}
                    </span>
                    <span className="ai-advisor-page__status">
                        <strong>Runtime</strong> {runtimeLabel}
                    </span>
                    <span className="ai-advisor-page__status">
                        <strong>Knowledge</strong> Not Indexed
                    </span>
                </div>
            </header>

            <div className="ai-advisor-page__workspace">
                <section className="ai-advisor-page__panel ai-advisor-page__conversations">
                    <h2>CONVERSATIONS</h2>
                    <div className="ai-advisor-page__panel-content">
                        <p className="ai-advisor-page__empty-message">No conversations yet</p>
                        <h3>Future</h3>
                        <ul>
                            <li>Recent sessions</li>
                            <li>Favorites</li>
                            <li>Search</li>
                            <li>Categories</li>
                        </ul>
                    </div>
                </section>

                <section className="ai-advisor-page__panel ai-advisor-page__advisor">
                    <h2>ADVISOR WORKSPACE</h2>
                    <div className="ai-advisor-page__advisor-content">
                        <AdvisorRuntimeStatus
                            connectionState={runtime.connectionState}
                            data={runtime.data}
                            error={runtime.error}
                            lastSuccessfulAt={runtime.lastSuccessfulAt}
                            loading={runtime.loading}
                            onRetry={runtime.retry}
                        />
                        <AdvisorConversation />
                    </div>
                </section>

                <section className="ai-advisor-page__panel ai-advisor-page__context-system">
                    <h2>CONTEXT &amp; SYSTEM</h2>
                    <div className="ai-advisor-page__context-content">
                        <section>
                            <h3>CONTEXT</h3>
                            <dl>
                                <div><dt>Scope</dt><dd>TradingAI Project</dd></div>
                                <div><dt>Page</dt><dd>AI Advisor</dd></div>
                                <div><dt>Mode</dt><dd>Platform Ready</dd></div>
                            </dl>
                        </section>

                        <section>
                            <h3>RUNTIME</h3>
                            <dl>
                                <div><dt>Status</dt><dd>{runtimeLabel}</dd></div>
                                <div><dt>Bot Runtime</dt><dd>{runtime.data?.bot.state || "—"}</dd></div>
                                <div><dt>Freshness</dt><dd>{runtime.data?.runtime.freshness || "—"}</dd></div>
                            </dl>
                        </section>

                        <section>
                            <h3>KNOWLEDGE</h3>
                            <dl>
                                <div><dt>Status</dt><dd>Not Indexed</dd></div>
                                <div><dt>Sources</dt><dd>No sources configured</dd></div>
                            </dl>
                        </section>

                        <section>
                            <h3>CAPABILITIES</h3>
                            <p>Future capabilities</p>
                            <ul>
                                <li>TradingAI specification search</li>
                                <li>Codebase analysis</li>
                                <li>Runtime diagnostics</li>
                                <li>Log investigation</li>
                                <li>Strategy explanation</li>
                                <li>Money Management guidance</li>
                                <li>Codex development assistance</li>
                            </ul>
                        </section>
                    </div>
                </section>
            </div>
        </main>
    );
}
