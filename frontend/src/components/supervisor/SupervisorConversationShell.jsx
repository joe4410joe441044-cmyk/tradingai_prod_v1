import { useEffect, useRef, useState } from "react";

import {
    createConversationId,
    sendSupervisorConversation,
} from "../../api/supervisorConversationClient";
import {
    createSupervisorSpeechInput,
    SpeechInputState,
} from "../../features/supervisor/speech/supervisorSpeechInput";

const MAX_HISTORY = 20;

export default function SupervisorConversationShell({ supervisorName, agentId }) {
    const [draft, setDraft] = useState("");
    const [messages, setMessages] = useState([]);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState("");
    const [speechState, setSpeechState] = useState(SpeechInputState.IDLE);
    const conversationId = useRef(createConversationId(agentId));
    const requestController = useRef(null);
    const mounted = useRef(true);
    const speech = useRef(null);

    useEffect(() => {
        mounted.current = true;
        speech.current = createSupervisorSpeechInput({
            onTranscript: (transcript) => setDraft((current) => current ? `${current} ${transcript}` : transcript),
            onStateChange: setSpeechState,
        });
        return () => {
            mounted.current = false;
            requestController.current?.abort();
            speech.current?.abort();
        };
    }, []);

    const append = (message) => setMessages((current) => [...current, message].slice(-MAX_HISTORY));

    async function submit(event) {
        event.preventDefault();
        const message = draft.trim();
        if (!message || pending) return;
        const controller = new AbortController();
        requestController.current = controller;
        setPending(true);
        setError("");
        append({ role: "operator", text: message });
        setDraft("");
        try {
            const response = await sendSupervisorConversation({
                agentId,
                message,
                conversationId: conversationId.current,
                signal: controller.signal,
            });
            if (!mounted.current || controller.signal.aborted) return;
            append({
                role: "supervisor",
                text: response.answer,
                status: response.status,
                attention: response.humanAttention,
            });
        } catch (caught) {
            if (!mounted.current || controller.signal.aborted) return;
            setError(caught?.message || "Supervisor response is unavailable.");
        } finally {
            if (mounted.current && requestController.current === controller) {
                requestController.current = null;
                setPending(false);
            }
        }
    }

    function cancel() {
        requestController.current?.abort();
        requestController.current = null;
        setPending(false);
    }

    const speechSupported = speechState !== SpeechInputState.UNSUPPORTED;
    const listening = speechState === SpeechInputState.LISTENING;

    return (
        <div className="supervisor-conversation" aria-label={`${supervisorName} conversation`}>
            <p className="supervisor-conversation__boundary">SHADOW · 実変更なし</p>
            <div className="supervisor-conversation__messages" aria-label={`${supervisorName} message history`}>
                {messages.length === 0 && <p>質問を入力してください。回答は提案・説明のみです。</p>}
                {messages.map((message, index) => (
                    <article className={`supervisor-conversation__message supervisor-conversation__message--${message.role}`} key={`${message.role}-${index}`}>
                        <strong>{message.role === "operator" ? "You" : supervisorName}</strong>
                        <p>{message.text}</p>
                        {message.status && <small>{message.status} · {message.attention}</small>}
                    </article>
                ))}
            </div>

            <form className="supervisor-conversation__composer" onSubmit={submit}>
                <button
                    className="supervisor-conversation__microphone"
                    type="button"
                    disabled={!speechSupported || pending}
                    aria-label={`${supervisorName} microphone`}
                    title={!speechSupported ? "このブラウザは音声入力に対応していません" : "音声を文字入力へ変換"}
                    onClick={() => listening ? speech.current?.abort() : speech.current?.start()}
                >
                    <span aria-hidden="true">●</span>
                </button>
                <label className="supervisor-conversation__input-label">
                    <span className="supervisor-conversation__visually-hidden">{supervisorName}への質問</span>
                    <input
                        type="text"
                        placeholder="質問を入力"
                        maxLength={1000}
                        value={draft}
                        disabled={pending}
                        onChange={(event) => setDraft(event.target.value)}
                    />
                </label>
                <button className="supervisor-conversation__send" type="submit" disabled={pending || !draft.trim()}>
                    送信
                </button>
                {pending && <button className="supervisor-conversation__cancel" type="button" onClick={cancel}>Cancel</button>}
            </form>
            <div className="supervisor-conversation__status" aria-live="polite">
                {pending && <span>Loading…</span>}
                {listening && <span>Listening… 認識結果は送信前に編集できます。</span>}
                {!speechSupported && <span>音声入力非対応。文字入力は利用できます。</span>}
            </div>
            {error && <p className="supervisor-conversation__error" role="alert">{error}</p>}
        </div>
    );
}
