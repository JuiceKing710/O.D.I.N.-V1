import React, { useEffect, useRef, useState } from "react";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition.js";
import { useSpeechSynthesis } from "../hooks/useSpeechSynthesis.js";
import { fetchModels, sendChatMessage } from "../ipc/apiClient.js";
import { useChatStore } from "../state/chatStore.js";

const MESSAGE_RENDER_LIMIT = 120;
const SCROLL_BOTTOM_THRESHOLD = 96;

export function ChatView({ onOpenCoreFocus }) {
  const [input, setInput] = useState("");
  const [isPinnedToLatest, setIsPinnedToLatest] = useState(true);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [speakingMessageId, setSpeakingMessageId] = useState("");
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  const [voiceNotice, setVoiceNotice] = useState("");
  const [providerStatus, setProviderStatus] = useState({
    error: "",
    loading: true,
    provider: null,
  });
  const inputRef = useRef(null);
  const messageEndRef = useRef(null);
  const messageListRef = useRef(null);
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
  const recognition = useSpeechRecognition({
    onStart: () => setVoiceState("listening"),
    onEnd: () => setVoiceState("idle"),
    onResult: (text) => {
      setInput(text);
      void sendMessage(text);
    },
  });
  const provider = providerStatus.provider;
  const providerAvailable = Boolean(provider?.available);
  const providerState = providerStatus.loading ? "pending" : providerAvailable ? "ok" : "error";
  const providerLabel = provider?.provider || "provider";
  const modelLabel = provider?.selected_model || "no model selected";
  const providerMessage =
    provider?.error || providerStatus.error || "Language model provider is unavailable.";
  const visibleMessages = messages.slice(-MESSAGE_RENDER_LIMIT);
  const hiddenMessageCount = Math.max(messages.length - visibleMessages.length, 0);

  useEffect(() => {
    let cancelled = false;
    fetchModels()
      .then((response) => {
        if (!cancelled) {
          setProviderStatus({
            error: "",
            loading: false,
            provider: response.provider,
          });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setProviderStatus({
            error: error.message,
            loading: false,
            provider: null,
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (isPinnedToLatest) {
      messageEndRef.current?.scrollIntoView({ block: "end" });
      setShowJumpLatest(false);
    }
  }, [isPinnedToLatest, messages.length]);

  function isNearMessageListBottom(element) {
    return (
      element.scrollHeight - element.scrollTop - element.clientHeight <= SCROLL_BOTTOM_THRESHOLD
    );
  }

  function handleMessageScroll() {
    const list = messageListRef.current;
    if (!list) {
      return;
    }
    const nearBottom = isNearMessageListBottom(list);
    setIsPinnedToLatest(nearBottom);
    setShowJumpLatest(!nearBottom && messages.length > 0);
  }

  function jumpToLatest() {
    setIsPinnedToLatest(true);
    setShowJumpLatest(false);
    requestAnimationFrame(() => {
      messageEndRef.current?.scrollIntoView({ block: "end" });
      inputRef.current?.focus();
    });
  }

  function speakMessage(message) {
    if (!message?.content) {
      return;
    }
    if (!speech.available) {
      setVoiceNotice("Browser speech is unavailable. Try Chrome or check macOS voice settings.");
      return;
    }
    setSpeakingMessageId(message.id || "");
    setVoiceNotice("");
    speech.speak(message.content);
  }

  function stopSpeech() {
    speech.stop();
    setSpeakingMessageId("");
    setVoiceState("idle");
  }

  async function sendMessage(rawText) {
    const text = rawText.trim();
    if (!text) {
      return;
    }
    speech.warmUp();
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
    } finally {
      inputRef.current?.focus();
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    await sendMessage(input);
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
          <div className="runtime-status" aria-label="Runtime status">
            <span className={`status-light ${providerState}`} />
            <span>{providerStatus.loading ? "Checking Ollama" : providerLabel}</span>
            <span>{modelLabel}</span>
          </div>
        </div>
        <div className="voice-controls" aria-label="Voice controls">
          <button
            className={voiceEnabled ? "toggle active" : "toggle"}
            type="button"
            onClick={() => {
              speech.warmUp();
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
          <button
            className={recognition.listening ? "toggle active" : "toggle"}
            type="button"
            onClick={() => {
              speech.warmUp();
              recognition.toggle();
            }}
            disabled={!recognition.available}
          >
            {recognition.listening ? "Listening" : "Mic"}
          </button>
          <button
            type="button"
            onClick={() => {
              setVoiceEnabled(true);
              speakMessage({
                id: "voice-test",
                role: "assistant",
                content: "Jarvis voice test. If you can hear this, speech output is working.",
              });
            }}
            disabled={!speech.available}
          >
            Test Voice
          </button>
          <button type="button" onClick={onOpenCoreFocus}>
            Core
          </button>
          <span className={`voice-pill ${voiceState}`}>{voiceState}</span>
        </div>
      </header>
      {voiceNotice && <p className="voice-notice">{voiceNotice}</p>}
      {!providerStatus.loading && !providerAvailable && (
        <p className="error provider-notice">{providerMessage}</p>
      )}
      {recognition.error && <p className="voice-notice">{recognition.error}</p>}
      {recognition.transcript && (
        <div className="dictation-preview">
          <span>Heard</span>
          <p>{recognition.transcript}</p>
        </div>
      )}
      <div className="message-stage">
        <div
          className="message-list"
          aria-live="polite"
          onScroll={handleMessageScroll}
          ref={messageListRef}
        >
          {hiddenMessageCount > 0 && (
            <div className="message-window-note">
              Showing latest {visibleMessages.length} of {messages.length} messages
            </div>
          )}
          {visibleMessages.map((message) => (
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
          <div ref={messageEndRef} />
        </div>
        {showJumpLatest && (
          <button className="jump-latest" type="button" onClick={jumpToLatest}>
            Latest
          </button>
        )}
      </div>
      <form className="composer" onSubmit={handleSubmit}>
        <label htmlFor="chat-input">Message</label>
        <textarea
          id="chat-input"
          ref={inputRef}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={3}
        />
        <button type="submit">Send</button>
      </form>
    </section>
  );
}
