export default function AIAdvisorPage() {
    return (
        <main className="ai-advisor-page">
            <header className="ai-advisor-page__header">
                <div className="ai-advisor-page__heading">
                    <h1>AI ADVISOR</h1>
                    <p>TradingAI Knowledge, Runtime &amp; Development Intelligence</p>
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
                    <span className="ai-advisor-page__status">
                        <strong>API</strong> Disabled
                    </span>
                    <span className="ai-advisor-page__status">
                        <strong>Runtime</strong> Not Connected
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
                        <div className="ai-advisor-page__welcome">
                            <strong>Platform Ready</strong>
                            <p>
                                TradingAI Advisor is ready for future provider,
                                knowledge and runtime integration.
                            </p>
                            <p>No AI provider is currently configured.</p>
                        </div>

                        <div className="ai-advisor-page__prompt-row">
                            <input
                                aria-label="AI Advisor prompt"
                                disabled
                                placeholder="Connect an AI provider to start a conversation"
                                type="text"
                            />
                            <button disabled type="button">Send</button>
                        </div>
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
                                <div><dt>Status</dt><dd>Not Connected</dd></div>
                                <div><dt>Bot Runtime</dt><dd>Not Connected</dd></div>
                                <div><dt>Telemetry</dt><dd>Not Connected</dd></div>
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
