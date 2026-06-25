import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { AgentsView } from "./components/AgentsView.jsx";
import { ChatDock } from "./components/ChatDock.jsx";
import { ChatView } from "./components/ChatView.jsx";
import { CoreFocusView } from "./components/CoreFocusView.jsx";
import { DataPanel } from "./components/DataPanel.jsx";
import { MetricsRail } from "./components/MetricsRail.jsx";
import { OdinStage } from "./components/OdinStage.jsx";
import { ProjectDashboard } from "./components/ProjectDashboard.jsx";
import { SettingsPanel } from "./components/SettingsPanel.jsx";
import { StartupHealth } from "./components/StartupHealth.jsx";
import { TokenGate } from "./components/TokenGate.jsx";
import { TopStrip } from "./components/TopStrip.jsx";
import { connectEvents, fetchSystemOverview } from "./ipc/apiClient.js";
import { AppStateProvider, useAppState } from "./state/appContext.jsx";
import { useAgentStore } from "./state/agentStore.js";
import { useChatStore } from "./state/chatStore.js";
import { useSystemStore } from "./state/systemStore.js";
import "./styles.css";

const PANELS = [
  { id: "overview", label: "Overview", glyph: "◉" },
  { id: "chat", label: "Chat", glyph: "◍" },
  { id: "agents", label: "Agents", glyph: "⬨" },
  { id: "workflows", label: "Workflows", glyph: "⬡" },
  { id: "data", label: "Data Map", glyph: "⬢" },
  { id: "settings", label: "Configuration", glyph: "⚙" },
];

function App() {
  const [activePanel, setActivePanel] = useState("overview");
  const [coreFocus, setCoreFocus] = useState(false);
  const { authRequired, conversationId } = useAppState();
  const messages = useChatStore((state) => state.messages);
  const tasks = useChatStore((state) => state.tasks);
  const voiceState = useChatStore((state) => state.voiceState);
  const applyEvent = useChatStore((state) => state.applyEvent);
  const applySystemEvent = useSystemStore((state) => state.applySystemEvent);
  const applyAgentEvent = useAgentStore((state) => state.applyAgentEvent);
  const setOverview = useSystemStore((state) => state.setOverview);
  const panelCounts = {
    chat: messages.length,
    workflows: tasks.length,
  };

  useEffect(
    () =>
      connectEvents((event) => {
        applyEvent(event);
        applySystemEvent(event);
        applyAgentEvent(event);
      }),
    [applyEvent, applySystemEvent, applyAgentEvent],
  );

  useEffect(() => {
    let cancelled = false;
    async function refreshOverview() {
      try {
        const overview = await fetchSystemOverview();
        if (!cancelled) {
          setOverview(overview);
        }
      } catch {
        // Telemetry stays on its last value until the backend responds again.
      }
    }
    refreshOverview();
    const timer = window.setInterval(refreshOverview, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [setOverview]);

  if (authRequired) {
    return <TokenGate />;
  }

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
    <main className="app-shell odin-shell">
      <aside className="sidebar" aria-label="O.D.I.N. navigation">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            ⬡
          </span>
          <div>
            <strong>O.D.I.N.</strong>
            <small>Core System</small>
          </div>
        </div>
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
              <span className="tab-glyph" aria-hidden="true">
                {panel.glyph}
              </span>
              <span>{panel.label}</span>
              {panelCounts[panel.id] > 0 && <strong>{panelCounts[panel.id]}</strong>}
            </button>
          ))}
        </nav>
        <button className="core-focus-launch" type="button" onClick={() => setCoreFocus(true)}>
          Enter Core Focus
        </button>
        <footer className="sidebar-foot">
          <strong>O.D.I.N. Core</strong>
          <small>Optical Detection &amp; Intelligence Network</small>
          <small>Conversation {conversationId || "new"} · voice {voiceState}</small>
        </footer>
      </aside>
      <section className="workspace odin-workspace">
        <TopStrip />
        <StartupHealth />
        <div className="workspace-body">
          <div className="workspace-main">
            {activePanel === "overview" && (
              <>
                <OdinStage />
                <ChatDock />
              </>
            )}
            {activePanel === "chat" && <ChatView onOpenCoreFocus={() => setCoreFocus(true)} />}
            {activePanel === "agents" && <AgentsView />}
            {activePanel === "workflows" && <ProjectDashboard />}
            {activePanel === "data" && <DataPanel />}
            {activePanel === "settings" && <SettingsPanel />}
          </div>
          <MetricsRail />
        </div>
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
