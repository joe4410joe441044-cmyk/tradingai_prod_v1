import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createAdvisorBrowserGatewayClient } from
    "../../features/ai-advisor/conversation/advisorBrowserGatewayClient.js";
import {
    OPERATOR_AUTH_STATE,
    getOperatorAuthStatus,
    subscribeOperatorAuthStatus,
} from "../../features/auth/operatorAuth.js";
import AdvisorGroundedResponse from "./AdvisorGroundedResponse.jsx";
import {
    beginAdvisorRequest,
    completeAdvisorRequest,
    failAdvisorRequest,
    initialAdvisorConversationState,
    MAX_ADVISOR_PROMPT_BYTES,
    utf8ByteLength,
    validateAdvisorPrompt,
} from "../../features/ai-advisor/conversation/advisorConversationModel.js";

export function AdvisorMessage({ message }) {
    return (
        <article className={`advisor-conversation__message advisor-conversation__message--${
            message.role.toLowerCase()
        }`}>
            <strong>{message.role === "USER" ? "You" : "AI Advisor"}</strong>
            <p>{message.content}</p>
            <AdvisorGroundedResponse response={message.groundedResponse} />
            <small>{message.status.replaceAll("_", " ")}</small>
        </article>
    );
}

export default function AdvisorConversation({
    gatewayClient = null,
    onHistoryChange = null,
}) {
    const [prompt, setPrompt] = useState("");
    const [conversation, setConversation] = useState(initialAdvisorConversationState);
    const [availability, setAvailability] = useState("UNAVAILABLE");
    const [operatorStatus, setOperatorStatus] = useState(() => getOperatorAuthStatus());
    const controllerRef = useRef(null);
    const mountedRef = useRef(true);
    const client = useMemo(
        () => gatewayClient || createAdvisorBrowserGatewayClient(),
        [gatewayClient],
    );
    const validation = useMemo(() => validateAdvisorPrompt(prompt), [prompt]);
    const authReady = availability === "AVAILABLE";
    const sending = conversation.activeRequestId !== null;
    const sendDisabled = !authReady || !validation.valid || sending;

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            controllerRef.current?.abort();
        };
    }, []);

    useEffect(() => {
        return subscribeOperatorAuthStatus(setOperatorStatus);
    }, []);

    useEffect(() => {
        onHistoryChange?.(conversation.archivedExchanges);
    }, [conversation.archivedExchanges, onHistoryChange]);

    useEffect(() => {
        let cancelled = false;
        const controller = new AbortController();
        const unauthenticated = (
            operatorStatus === OPERATOR_AUTH_STATE.UNAUTHENTICATED
            || operatorStatus === OPERATOR_AUTH_STATE.SESSION_EXPIRED
        );
        if (unauthenticated) {
            // Logout/session-expiry invalidates the authenticated advisor state
            // immediately instead of waiting for a network round-trip, so Send
            // is disabled right away.
            setAvailability("AUTHENTICATION_REQUIRED");
            controllerRef.current?.abort();
            controllerRef.current = null;
            setPrompt("");
            setConversation(initialAdvisorConversationState);
            return () => {
                cancelled = true;
                controller.abort();
            };
        }
        client.getStatus({ signal: controller.signal })
            .then((status) => {
                if (!cancelled) setAvailability(status);
            })
            .catch((error) => {
                if (!cancelled) {
                    setAvailability(
                        error?.code === "AUTHENTICATION_REQUIRED"
                            ? "AUTHENTICATION_REQUIRED"
                            : "UNAVAILABLE",
                    );
                }
            });
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [client, operatorStatus]);

    const send = useCallback(async () => {
        if (sendDisabled || controllerRef.current !== null) return;
        const requestId = crypto.randomUUID();
        const createdAt = new Date().toISOString();
        const controller = new AbortController();
        controllerRef.current = controller;
        setConversation((state) => beginAdvisorRequest(state, {
            requestId,
            userMessageId: crypto.randomUUID(),
            assistantMessageId: crypto.randomUUID(),
            content: prompt,
            createdAt,
        }));
        try {
            const response = await client.requestAdvice(prompt, {
                signal: controller.signal,
            });
            if (mountedRef.current) {
                setConversation((state) => (
                    completeAdvisorRequest(
                        state,
                        requestId,
                        response.summary,
                        response,
                    )
                ));
                setPrompt("");
            }
        } catch (error) {
            if (mountedRef.current) {
                setConversation((state) => (
                    failAdvisorRequest(
                        state,
                        requestId,
                        typeof error?.code === "string"
                            ? error.code
                            : "UNKNOWN_SAFE_FAILURE",
                    )
                ));
            }
        } finally {
            if (controllerRef.current === controller) controllerRef.current = null;
        }
    }, [
        client,
        prompt,
        sendDisabled,
    ]);

    const cancel = useCallback(() => {
        controllerRef.current?.abort();
    }, []);
    const clear = useCallback(() => {
        if (!sending) setPrompt("");
    }, [sending]);

    return (
        <section aria-label="AI Advisor conversation" className="advisor-conversation">
            <div className="advisor-conversation__composer">
                <label htmlFor="advisor-prompt">Prompt Input（質問入力）</label>
                <textarea
                    autoComplete="off"
                    id="advisor-prompt"
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder="Ask TradingAI...（TradingAIについて質問してください）"
                    rows="3"
                    value={prompt}
                />
                <div className="advisor-conversation__composer-footer">
                    <span className="advisor-conversation__boundary">
                        READ ONLY（読み取り専用） · No execution（実行なし） · No config changes（設定変更なし）
                    </span>
                    <span>{utf8ByteLength(prompt)} / {MAX_ADVISOR_PROMPT_BYTES} UTF-8 bytes</span>
                    <div>
                        <button disabled={sendDisabled} onClick={send} type="button">Send（送信）</button>
                        <button disabled={!sending} onClick={cancel} type="button">Cancel（キャンセル）</button>
                        <button disabled={sending || !prompt}
                            onClick={clear} type="button">Clear（クリア）</button>
                    </div>
                </div>
                {availability !== "AVAILABLE" && (
                    <p className="advisor-conversation__failure" role="status">
                        {availability === "AUTHENTICATION_REQUIRED"
                            ? "Authentication required"
                            : "AI Advisor unavailable"}
                    </p>
                )}
            </div>
            <div aria-label="Conversation Thread" className="advisor-conversation__thread">
                {conversation.messages.length === 0
                    ? <p className="advisor-conversation__empty">Ask TradingAI a question.（TradingAIについて質問してください。）</p>
                    : conversation.messages.map((message) => (
                        <AdvisorMessage key={message.id} message={message} />
                    ))}
            </div>
        </section>
    );
}
