import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createAdvisorBrowserGatewayClient } from
    "../../features/ai-advisor/conversation/advisorBrowserGatewayClient.js";
import AdvisorGroundedResponse from "./AdvisorGroundedResponse.jsx";
import {
    beginAdvisorRequest,
    clearAdvisorConversation,
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
}) {
    const [prompt, setPrompt] = useState("");
    const [conversation, setConversation] = useState(initialAdvisorConversationState);
    const [availability, setAvailability] = useState("UNAVAILABLE");
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
        const controller = new AbortController();
        client.getStatus({ signal: controller.signal })
            .then((status) => {
                if (mountedRef.current) setAvailability(status);
            })
            .catch((error) => {
                if (mountedRef.current) {
                    setAvailability(
                        error?.code === "AUTHENTICATION_REQUIRED"
                            ? "AUTHENTICATION_REQUIRED"
                            : "UNAVAILABLE",
                    );
                }
            });
        return () => {
            mountedRef.current = false;
            controller.abort();
            controllerRef.current?.abort();
        };
    }, [client]);

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
        setConversation((state) => clearAdvisorConversation(state));
        if (!sending) setPrompt("");
    }, [sending]);

    return (
        <section aria-label="AI Advisor conversation" className="advisor-conversation">
            <div aria-live="polite" className="advisor-conversation__availability">
                <strong>Advisor Availability</strong>
                <span>{availability}</span>
            </div>
            <div className="advisor-conversation__boundary">
                Read-only advisor · No order execution · No configuration changes
            </div>
            <div aria-label="Conversation Thread" className="advisor-conversation__thread">
                {conversation.messages.length === 0
                    ? <p className="advisor-conversation__empty">Start a session-memory conversation.</p>
                    : conversation.messages.map((message) => (
                        <AdvisorMessage key={message.id} message={message} />
                    ))}
            </div>
            <div className="advisor-conversation__composer">
                <label htmlFor="advisor-prompt">Prompt Input</label>
                <textarea
                    autoComplete="off"
                    id="advisor-prompt"
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder="Ask about TradingAI. Do not enter secrets or credentials."
                    rows="4"
                    value={prompt}
                />
                <div className="advisor-conversation__composer-footer">
                    <span>{utf8ByteLength(prompt)} / {MAX_ADVISOR_PROMPT_BYTES} UTF-8 bytes</span>
                    <div>
                        <button disabled={sendDisabled} onClick={send} type="button">Send</button>
                        <button disabled={!sending} onClick={cancel} type="button">Cancel</button>
                        <button disabled={sending || (!prompt && conversation.messages.length === 0)}
                            onClick={clear} type="button">Clear</button>
                    </div>
                </div>
                {availability !== "AVAILABLE" && (
                    <p className="advisor-conversation__failure" role="status">
                        Safe Failure: AI Advisor is {availability.toLowerCase()}.
                    </p>
                )}
            </div>
        </section>
    );
}
