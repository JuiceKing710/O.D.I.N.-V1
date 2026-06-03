import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { AICore } from "./components/AICore.jsx";
import { ChatView } from "./components/ChatView.jsx";
import { ProjectDashboard } from "./components/ProjectDashboard.jsx";
import { SettingsPanel } from "./components/SettingsPanel.jsx";
import { useChatStore } from "./state/chatStore.js";
import "./styles.css";

function App() {
  const [activePanel, setActivePanel] = useState("chat");
  const voiceState = useChatStore((state) => state.voiceState);

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Jarvis navigation">
        <AICore state={voiceState} />
        <nav className="tabs" aria-label="Primary">
          {["chat", "projects", "settings"].map((panel) => (
            <button
              key={panel}
              className={activePanel === panel ? "tab active" : "tab"}
              onClick={() => setActivePanel(panel)}
              type="button"
            >
              {panel}
            </button>
          ))}
        </nav>
      </aside>
      <section className="workspace">
        {activePanel === "chat" && <ChatView />}
        {activePanel === "projects" && <ProjectDashboard />}
        {activePanel === "settings" && <SettingsPanel />}
      </section>
    </main>
  );
}

const root = createRoot(document.getElementById("root"));
root.render(<App />);

