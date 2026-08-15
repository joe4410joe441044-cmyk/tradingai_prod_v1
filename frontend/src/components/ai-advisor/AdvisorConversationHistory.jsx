import { useState } from "react";

import AdvisorGroundedResponse from "./AdvisorGroundedResponse.jsx";

function displayTime(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime())
        ? "—"
        : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function ArchivedExchange({ exchange }) {
    const [expanded, setExpanded] = useState(false);
    return (
        <article className="advisor-history__item">
            <div className="advisor-history__preview">
                <time dateTime={exchange.createdAt}>{displayTime(exchange.createdAt)}</time>
                <p title={exchange.userMessage.content}>{exchange.userMessage.content}</p>
                <strong>{exchange.status}</strong>
                <button
                    aria-expanded={expanded}
                    onClick={() => setExpanded((value) => !value)}
                    type="button"
                >
                    {expanded ? "Hide（閉じる）" : "View（表示）"}
                </button>
            </div>
            {expanded && (
                <div className="advisor-history__full">
                    <section>
                        <h3>Question（質問）</h3>
                        <p>{exchange.userMessage.content}</p>
                    </section>
                    <section>
                        <h3>Answer（回答）</h3>
                        <p>{exchange.assistantMessage.content}</p>
                        <AdvisorGroundedResponse
                            response={exchange.assistantMessage.groundedResponse}
                        />
                    </section>
                    <section>
                        <h3>Status（状態）</h3>
                        <p>{exchange.status}</p>
                    </section>
                </div>
            )}
        </article>
    );
}

export default function AdvisorConversationHistory({ exchanges }) {
    if (exchanges.length === 0) {
        return (
            <p className="ai-advisor-page__empty-message">
                No archived conversations.（履歴はありません。）
            </p>
        );
    }
    return (
        <div aria-label="Archived conversation exchanges" className="advisor-history">
            {exchanges.map((exchange) => (
                <ArchivedExchange exchange={exchange} key={exchange.requestId} />
            ))}
        </div>
    );
}
