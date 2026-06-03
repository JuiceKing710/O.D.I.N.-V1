import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { AICore } from "./components/AICore.jsx";
import { ChatView } from "./components/ChatView.jsx";
import { CoreFocusView } from "./components/CoreFocusView.jsx";
import { ProjectDashboard } from "./components/ProjectDashboard.jsx";
import { SettingsPanel } from "./components/SettingsPanel.jsx";
import { connectEvents } from "./ipc/apiClient.js";
import { AppStateProvider, useAppState } from "./state/appContext.jsx";
import { useChatStore } from "./state/chatStore.js";
import "./styles.css";

const PANELS = [
  { id: "chat", label: "Chat" },
  { id: "projects", label: "Projects" },
  { id: "settings", label: "Settings" },
];

function App() {
  const [activePanel, setActivePanel] = useState("chat");
  const [coreFocus, setCoreFocus] = useState(false);
  const { conversationId, currentUser } = useAppState();
  const messages = useChatStore((state) => state.messages);
  const tasks = useChatStore((state) => state.tasks);
  const voiceState = useChatStore((state) => state.voiceState);
  const applyEvent = useChatStore((state) => state.applyEvent);
  const panelCounts = {
    chat: messages.length,
    projects: tasks.length,
  };

  useEffect(() => connectEvents(applyEvent), [applyEvent]);

  if (coreFocus) {
    return (
      <CoreFocusView
        messages={messages}
        onExit={() => setCoreFocus(false)}
        state={voiceState}
      />
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Jarvis navigation">
        <AICore state={voiceState} />
        <nav className="tabs" aria-label="Primary">
          {PANELS.map((panel) => (
            <button
              key={panel.id}
              className={activePanel === panel.id ? "tab active" : "tab"}
              onClick={() => {
                setActivePanel(panel.id);
                setCoreFocus(false);
              }}
              type="button"
            >
              <span>{panel.label}</span>
              {panelCounts[panel.id] > 0 && <strong>{panelCounts[panel.id]}</strong>}
            </button>
          ))}
        </nav>
        <dl className="sidebar-status" aria-label="Session status">
          <div>
            <dt>User</dt>
            <dd>{currentUser.displayName}</dd>
          </div>
          <div>
            <dt>Conversation</dt>
            <dd>{conversationId || "New"}</dd>
          </div>
          <div>
            <dt>Voice</dt>
            <dd>{voiceState}</dd>
          </div>
          <div>
            <dt>Messages</dt>
            <dd>{messages.length}</dd>
          </div>
          <div>
            <dt>Projects</dt>
            <dd>{tasks.length}</dd>
          </div>
        </dl>
      </aside>
      <section className="workspace">
        {activePanel === "chat" && <ChatView onOpenCoreFocus={() => setCoreFocus(true)} />}
        {activePanel === "projects" && <ProjectDashboard />}
        {activePanel === "settings" && <SettingsPanel />}
      </section>
    </main>
  );
}

const root = createRoot(document.getElementById("root"));
root.render(
  <AppStateProvider>
    <App />
  </AppStateProvider>,
);
