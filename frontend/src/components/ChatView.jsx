import React, { useState } from "react";
import { useSpeechSynthesis } from "../hooks/useSpeechSynthesis.js";
import { sendChatMessage } from "../ipc/apiClient.js";
import { useChatStore } from "../state/chatStore.js";

export function ChatView() {
  const [input, setInput] = useState("");
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [speakingMessageId, setSpeakingMessageId] = useState("");
  const messages = useChatStore((state) => state.messages);
  const addMessage = useChatStore((state) => state.addMessage);
  const voiceState = useChatStore((state) => state.voiceState);
  const setVoiceState = useChatStore((state) => state.setVoiceState);
  const speech = useSpeechSynthesis({
    onStart: () => setVoiceState("speaking"),
    onEnd: () => {
      setSpeakingMessageId("");
      setVoiceState("idle");
    },
  });

  function speakMessage(message) {
    if (!message?.content) {
      return;
    }
    setSpeakingMessageId(message.id || "");
    speech.speak(message.content);
  }

  function stopSpeech() {
    speech.stop();
    setSpeakingMessageId("");
    setVoiceState("idle");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const text = input.trim();
    if (!text) {
      return;
    }
    addMessage({ role: "user", content: text });
    setInput("");
    setVoiceState("thinking");
    try {
      const response = await sendChatMessage({ message: text });
      const assistantMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.reply,
      };
      addMessage(assistantMessage);
      if (voiceEnabled && speech.available) {
        speakMessage(assistantMessage);
      } else {
        setVoiceState("idle");
      }
    } catch (error) {
      addMessage({ role: "assistant", content: error.message });
      setVoiceState("idle");
    }
  }

  return (
    <section className="panel chat-panel" aria-label="Chat">
      <header className="chat-header">
        <div>
          <h1>Jarvis</h1>
          <p>
            Voice {speech.available ? "ready" : "unavailable"}{" "}
            {speech.voiceName ? `with ${speech.voiceName}` : ""}
          </p>
        </div>
        <div className="voice-controls" aria-label="Voice controls">
          <button
            className={voiceEnabled ? "toggle active" : "toggle"}
            type="button"
            onClick={() => {
              const next = !voiceEnabled;
              setVoiceEnabled(next);
              if (!next) {
                stopSpeech();
              }
            }}
          >
            Voice
          </button>
          <button type="button" onClick={stopSpeech} disabled={!speech.speaking}>
            Stop
          </button>
          <span className={`voice-pill ${voiceState}`}>{voiceState}</span>
        </div>
      </header>
      <div className="message-list" aria-live="polite">
        {messages.map((message) => (
          <article key={message.id} className={`message ${message.role}`}>
            <div className="message-meta">
              <span>{message.role}</span>
              {message.role === "assistant" && (
                <button
                  type="button"
                  onClick={() =>
                    speakingMessageId === message.id ? stopSpeech() : speakMessage(message)
                  }
                  disabled={!speech.available}
                >
                  {speakingMessageId === message.id && speech.speaking ? "Stop" : "Speak"}
                </button>
              )}
            </div>
            <p>{message.content}</p>
          </article>
        ))}
      </div>
      <form className="composer" onSubmit={handleSubmit}>
        <label htmlFor="chat-input">Message</label>
        <textarea
          id="chat-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={3}
        />
        <button type="submit">Send</button>
      </form>
    </section>
  );
}
