export const SpeechInputState = Object.freeze({
    SUPPORTED: "SUPPORTED",
    UNSUPPORTED: "UNSUPPORTED",
    PERMISSION_DENIED: "PERMISSION_DENIED",
    NO_SPEECH: "NO_SPEECH",
    ABORTED: "ABORTED",
    ERROR: "ERROR",
    LISTENING: "LISTENING",
    IDLE: "IDLE",
});

export function createSupervisorSpeechInput({
    browser = globalThis.window,
    onTranscript,
    onStateChange,
} = {}) {
    const Recognition = browser?.SpeechRecognition || browser?.webkitSpeechRecognition;
    if (!Recognition) {
        onStateChange?.(SpeechInputState.UNSUPPORTED);
        return {
            supported: false,
            start() {},
            abort() {},
        };
    }

    const recognition = new Recognition();
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.lang = browser?.navigator?.language || "ja-JP";
    let state = SpeechInputState.IDLE;
    const update = (next) => {
        state = next;
        onStateChange?.(next);
    };
    recognition.onstart = () => update(SpeechInputState.LISTENING);
    recognition.onresult = (event) => {
        const transcript = event?.results?.[0]?.[0]?.transcript;
        if (typeof transcript === "string" && transcript.trim()) {
            onTranscript?.(transcript.trim());
        }
        update(SpeechInputState.IDLE);
    };
    recognition.onerror = (event) => {
        const next = event?.error === "not-allowed" || event?.error === "service-not-allowed"
            ? SpeechInputState.PERMISSION_DENIED
            : event?.error === "no-speech"
                ? SpeechInputState.NO_SPEECH
                : event?.error === "aborted"
                    ? SpeechInputState.ABORTED
                    : SpeechInputState.ERROR;
        update(next);
    };
    recognition.onend = () => {
        if (state === SpeechInputState.LISTENING) update(SpeechInputState.IDLE);
    };
    onStateChange?.(SpeechInputState.SUPPORTED);

    return {
        supported: true,
        start() { recognition.start(); },
        abort() { recognition.abort(); },
    };
}
