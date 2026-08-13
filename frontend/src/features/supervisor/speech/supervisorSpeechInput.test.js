import assert from "node:assert/strict";
import test from "node:test";

import { createSupervisorSpeechInput, SpeechInputState } from "./supervisorSpeechInput.js";

test("unsupported browser disables speech without affecting text input", () => {
    const states = [];
    const adapter = createSupervisorSpeechInput({ browser: {}, onStateChange: (state) => states.push(state) });
    assert.equal(adapter.supported, false);
    assert.deepEqual(states, [SpeechInputState.UNSUPPORTED]);
});

test("transcript is exposed for editable input and never auto-sent", () => {
    let recognition;
    class Recognition {
        constructor() { recognition = this; }
        start() { this.onstart(); }
        abort() { this.onerror({ error: "aborted" }); }
    }
    const transcripts = [];
    const adapter = createSupervisorSpeechInput({
        browser: { SpeechRecognition: Recognition, navigator: { language: "ja-JP" } },
        onTranscript: (value) => transcripts.push(value),
    });
    adapter.start();
    recognition.onresult({ results: [[{ transcript: "Risk 0.5 percent" }]] });
    assert.deepEqual(transcripts, ["Risk 0.5 percent"]);
    assert.equal(adapter.supported, true);
});

test("permission denied and no-speech are distinct safe states", () => {
    let recognition;
    class Recognition { constructor() { recognition = this; } start() {} abort() {} }
    const states = [];
    createSupervisorSpeechInput({
        browser: { webkitSpeechRecognition: Recognition },
        onStateChange: (state) => states.push(state),
    });
    recognition.onerror({ error: "not-allowed" });
    recognition.onerror({ error: "no-speech" });
    assert.ok(states.includes(SpeechInputState.PERMISSION_DENIED));
    assert.ok(states.includes(SpeechInputState.NO_SPEECH));
});
