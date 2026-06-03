import React, { useEffect, useRef, useState } from "react";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition.js";
import { useSpeechSynthesis } from "../hooks/useSpeechSynthesis.js";
import {
  fetchConversationMessages,
  fetchConversations,
  fetchModels,
  sendChatMessage,
} from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";
import { useChatStore } from "../state/chatStore.js";

const MESSAGE_RENDER_LIMIT = 120;
const SCROLL_BOTTOM_THRESHOLD = 96;

export function ChatView({ onOpenCoreFocus }) {
  const [input, setInput] = useState("");
  const [conversationError, setConversationError] = useState("");
  const [conversations, setConversations] = useState([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);
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
  const { conversationId, currentUser, setConversationId, startNewConversation } = useAppState();
  const messages = useChatStore((state) => state.messages);
  const addMessage = useChatStore((state) => state.addMessage);
  const clearMessages = useChatStore((state) => state.clearMessages);
  const setMessages = useChatStore((state) => state.setMessages);
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

  async function refreshConversations() {
    setConversationsLoading(true);
    setConversationError("");
    try {
      const response = await fetchConversations(currentUser.username);
      setConversations(response);
    } catch (error) {
      setConversationError(error.message);
    } finally {
      setConversationsLoading(false);
    }
  }

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
    refreshConversations();
  }, [currentUser.username]);

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

  function handleNewChat() {
    stopSpeech();
    startNewConversation();
    clearMessages();
    setInput("");
    setIsPinnedToLatest(true);
    setShowJumpLatest(false);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  async function openConversation(nextConversationId) {
    stopSpeech();
    setConversationError("");
    try {
      const response = await fetchConversationMessages(nextConversationId, currentUser.username);
      setConversationId(nextConversationId);
      setMessages(
        response.map((message) => ({
          id: `message-${message.msg_id}`,
          role: message.role,
          content: message.content,
          conversationId: message.convo_id,
        })),
      );
      setInput("");
      setIsPinnedToLatest(true);
      setShowJumpLatest(false);
      requestAnimationFrame(() => {
        messageEndRef.current?.scrollIntoView({ block: "end" });
        inputRef.current?.focus();
      });
    } catch (error) {
      setConversationError(error.message);
    }
  }

  function formatConversationTime(value) {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(value));
  }

  async function sendMessage(rawText) {
    const text = rawText.trim();
    if (!text) {
      return;
    }
    speech.warmUp();
    addMessage({ role: "user", content: text, conversationId });
    setInput("");
    setVoiceState("thinking");
    try {
      const response = await sendChatMessage({
        conversationId,
        message: text,
        username: currentUser.username,
      });
      setConversationId(response.conversation_id);
      await refreshConversations();
      const assistantMessage = {
        conversationId: response.conversation_id || conversationId,
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
          <p className="conversation-label">
            Conversation {conversationId ? `#${conversationId}` : "New"}
          </p>
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
            type="button"
            onClick={handleNewChat}
            disabled={!conversationId && !messages.length}
          >
            New Chat
          </button>
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
      {conversationError && <p className="error provider-notice">{conversationError}</p>}
      {recognition.transcript && (
        <div className="dictation-preview">
          <span>Heard</span>
          <p>{recognition.transcript}</p>
        </div>
      )}
      <section className="conversation-history" aria-label="Conversation history">
        <div className="conversation-history-heading">
          <h2>History</h2>
          <button type="button" onClick={refreshConversations} disabled={conversationsLoading}>
            Refresh
          </button>
        </div>
        {conversations.length ? (
          <div className="conversation-list">
            {conversations.map((conversation) => (
              <button
                key={conversation.convo_id}
                className={conversation.convo_id === conversationId ? "active" : ""}
                type="button"
                onClick={() => openConversation(conversation.convo_id)}
              >
                <span>{conversation.title || `Conversation #${conversation.convo_id}`}</span>
                <small>
                  #{conversation.convo_id} · {conversation.message_count} messages ·{" "}
                  {formatConversationTime(conversation.last_activity_at)}
                </small>
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            {conversationsLoading ? "Loading conversations..." : "No conversations yet."}
          </div>
        )}
      </section>
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
