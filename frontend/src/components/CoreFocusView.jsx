import React from "react";
import { AICore } from "./AICore.jsx";

export function CoreFocusView({ messages, onExit, state }) {
  const ghostMessages = messages.slice(-6);

  return (
    <main className="core-focus-view" aria-label="O.D.I.N. core focus">
      <div className="core-focus-chat" aria-hidden="true">
        {ghostMessages.map((message) => (
          <article key={message.id} className={`ghost-message ${message.role}`}>
            <span>{message.role}</span>
            <p>{message.content}</p>
          </article>
        ))}
      </div>
      <header className="core-focus-header">
        <span>O.D.I.N. Core</span>
        <button type="button" onClick={onExit}>
          Exit
        </button>
      </header>
      <AICore mode="focus" state={state} />
    </main>
  );
}
