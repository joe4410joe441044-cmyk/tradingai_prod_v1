import { useState } from "react";

import AdvisorConversation from "../components/ai-advisor/AdvisorConversation";
import AdvisorConversationHistory from "../components/ai-advisor/AdvisorConversationHistory";
import AdvisorDisclosure from "../components/ai-advisor/AdvisorDisclosure";
import AdvisorRuntimeStatus from "../components/ai-advisor/AdvisorRuntimeStatus";
import OperatorLogin from "../components/auth/OperatorLogin";
import useAdvisorRuntime from "../features/ai-advisor/runtime/useAdvisorRuntime";

export default function AIAdvisorPage() {
    const runtime = useAdvisorRuntime();
    const [archivedExchanges, setArchivedExchanges] = useState([]);

    const runtimeLabel = runtime.connectionState === "CONNECTED"
        ? "Connected"
        : runtime.connectionState === "REFRESHING"
            ? "Refreshing"
            : runtime.connectionState === "DEGRADED"
                ? "Degraded"
                : runtime.connectionState === "LOADING"
                    ? "Connecting"
                    : "Not Connected";

    const headerStatus = (() => {
        switch (runtime.connectionState) {
            case "CONNECTED":
                return { label: "Connected（接続済み）", tone: "ok" };
            case "REFRESHING":
                return { label: "Refreshing", tone: "ok" };
            case "DEGRADED":
                return { label: "Runtime degraded", tone: "warning" };
            case "DISCONNECTED":
                return { label: "Runtime unavailable", tone: "danger" };
            default:
                return { label: "Connecting", tone: "neutral" };
        }
    })();

    return (
        <main className="ai-advisor-page">
            <header className="ai-advisor-page__header">
                <div className="ai-advisor-page__brand">
                    <span className="ai-advisor-page__title">AI Advisor（AIアドバイザー）</span>
                    <span
                        className={`ai-advisor-page__compact-status ai-advisor-page__compact-status--${
                            headerStatus.tone
                        }`}
                    >
                        {headerStatus.label}
                    </span>
                </div>

                <div className="ai-advisor-page__auth">
                    <OperatorLogin />
                </div>
            </header>

            <section
                aria-label="AI Advisor conversation"
                className="ai-advisor-page__primary"
            >
                <AdvisorConversation onHistoryChange={setArchivedExchanges} />
            </section>

            <section
                aria-label="Advisor on-demand details"
                className="ai-advisor-page__details"
            >
                <AdvisorDisclosure title={`Conversation History（会話履歴） · ${
                    archivedExchanges.length
                }`}>
                    <div className="ai-advisor-page__history">
                        <AdvisorConversationHistory exchanges={archivedExchanges} />
                    </div>
                </AdvisorDisclosure>

                <AdvisorDisclosure
                    kicker="ON DEMAND"
                    title="System / Runtime Details（システム / ランタイム詳細）"
                >
                    <AdvisorRuntimeStatus
                        connectionState={runtime.connectionState}
                        data={runtime.data}
                        error={runtime.error}
                        lastSuccessfulAt={runtime.lastSuccessfulAt}
                        loading={runtime.loading}
                        onRetry={runtime.retry}
                    />
                </AdvisorDisclosure>

                <AdvisorDisclosure kicker="ON DEMAND" title="Context & Knowledge（コンテキスト / ナレッジ）">
                    <div className="ai-advisor-page__context-content">
                        <section>
                            <h3>CONTEXT</h3>
                            <dl>
                                <div><dt>Scope</dt><dd>TradingAI Project</dd></div>
                                <div><dt>Page</dt><dd>AI Advisor</dd></div>
                                <div><dt>Mode</dt><dd>Read-only advisor</dd></div>
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
                                <div><dt>Status</dt><dd>Authoritative static grounding</dd></div>
                                <div><dt>Validation</dt><dd>Approved and hash-verified per request</dd></div>
                                <div><dt>Sources</dt><dd>Shown in answer citations when used</dd></div>
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
                </AdvisorDisclosure>
            </section>
        </main>
    );
}
