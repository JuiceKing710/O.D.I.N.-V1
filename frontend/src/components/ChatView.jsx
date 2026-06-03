import React, { useState } from "react";
import { sendChatMessage } from "../ipc/apiClient.js";
import { useChatStore } from "../state/chatStore.js";

export function ChatView() {
  const [input, setInput] = useState("");
  const messages = useChatStore((state) => state.messages);
  const addMessage = useChatStore((state) => state.addMessage);
  const setVoiceState = useChatStore((state) => state.setVoiceState);

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
      addMessage({ role: "assistant", content: response.reply });
      setVoiceState("speaking");
      window.setTimeout(() => setVoiceState("idle"), 700);
    } catch (error) {
      addMessage({ role: "assistant", content: error.message });
      setVoiceState("idle");
    }
  }

  return (
    <section className="panel chat-panel" aria-label="Chat">
      <div className="message-list" aria-live="polite">
        {messages.map((message) => (
          <article key={message.id} className={`message ${message.role}`}>
            <span>{message.role}</span>
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

