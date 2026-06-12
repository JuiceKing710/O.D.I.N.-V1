import React, { useEffect, useRef, useState } from "react";
import { sendChatMessage } from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";
import { useChatStore } from "../state/chatStore.js";
import { useOdinVoice } from "../hooks/useOdinVoice.js";

const DOCK_MESSAGE_LIMIT = 14;

export function ChatDock() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const endRef = useRef(null);
  const inputRef = useRef(null);
  const { conversationId, currentUser, settings, setConversationId } = useAppState();
  const messages = useChatStore((state) => state.messages);
  const streaming = useChatStore((state) => state.streaming);
  const wakeSignal = useChatStore((state) => state.wakeSignal);
  const addMessage = useChatStore((state) => state.addMessage);
  const setVoiceState = useChatStore((state) => state.setVoiceState);
  const voice = useOdinVoice();
  const voiceEnabled = settings?.voice_mode !== "disabled";
  const visible = messages.slice(-DOCK_MESSAGE_LIMIT);
  const streamingText = streaming?.text || "";

  useEffect(() => {
    if (open) {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [open, messages.length, streamingText]);

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (wakeSignal > 0) {
      setOpen(true);
    }
  }, [wakeSignal]);

  async function handleSubmit(event) {
    event.preventDefault();
    const text = input.trim();
    if (!text || sending) {
      return;
    }
    setError("");
    setSending(true);
    if (voiceEnabled) {
      voice.warmUp();
    }
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
      addMessage({
        conversationId: response.conversation_id,
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.reply,
      });
      if (voiceEnabled && voice.available) {
        await voice.speak(response.reply);
      } else {
        setVoiceState("idle");
      }
    } catch (requestError) {
      setError(requestError.message);
      setVoiceState("idle");
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  if (!open) {
    return (
      <button
        className="dock-toggle"
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Speak with Odin"
      >
        <span aria-hidden="true">ᛟ</span>
        Speak with Odin
      </button>
    );
  }

  return (
    <aside className="chat-dock" aria-label="Odin chat dock">
      <header className="dock-header">
        <div>
          <strong>Odin</strong>
          <small>Conversation {conversationId ? `#${conversationId}` : "new"}</small>
        </div>
        <div className="dock-actions">
          <button type="button" onClick={() => voice.stop()} aria-label="Stop speaking">
            ■
          </button>
          <button type="button" onClick={() => setOpen(false)} aria-label="Close chat dock">
            ✕
          </button>
        </div>
      </header>
      <div className="dock-messages">
        {visible.length === 0 && !streamingText && (
          <p className="dock-empty">Ask Odin anything — he is listening.</p>
        )}
        {visible.map((message) => (
          <article key={message.id} className={`dock-message ${message.role}`}>
            <span>{message.role === "assistant" ? "Odin" : "You"}</span>
            <p>{message.content}</p>
          </article>
        ))}
        {streamingText && (
          <article className="dock-message assistant streaming">
            <span>Odin</span>
            <p>
              {streamingText}
              {streaming?.active && <i className="stream-cursor" aria-hidden="true" />}
            </p>
          </article>
        )}
        <div ref={endRef} />
      </div>
      {error && <p className="dock-error">{error}</p>}
      <form className="dock-composer" onSubmit={handleSubmit}>
        <input
          ref={inputRef}
          type="text"
          placeholder="Speak with Odin…"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          aria-label="Message Odin"
        />
        <button type="submit" disabled={!input.trim() || sending}>
          {sending ? "…" : "Send"}
        </button>
      </form>
    </aside>
  );
}
