import React, { useEffect, useState } from "react";
import { fetchStartupHealth } from "../ipc/apiClient.js";

const LABELS = {
  backend: "Backend",
  model: "Ollama model",
  voice: "Voice",
  memory: "Memory",
  backups: "Backups",
};

export function StartupHealth() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    try {
      setHealth(await fetchStartupHealth());
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function restartBackend() {
    setError("");
    try {
      if (!globalThis.jarvisDesktop?.restartBackend) {
        throw new Error("Backend restart is available in the desktop app.");
      }
      await globalThis.jarvisDesktop.restartBackend();
      await refresh();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function openMicrophoneSettings() {
    await globalThis.jarvisDesktop?.openMicrophoneSettings?.();
  }

  useEffect(() => {
    refresh();
  }, []);

  const services = Object.entries(health?.services || {});
  const hasWarning = error || services.some(([, service]) => !service.ok);
  if (!hasWarning) {
    return null;
  }

  return (
    <section className="startup-health" aria-label="Startup health">
      <div>
        <strong>{error ? "O.D.I.N. backend is offline" : "O.D.I.N. needs attention"}</strong>
        <small>
          {error
            ? "Start the desktop app again or run the backend from the project directory."
            : "Core chat remains available while optional services are repaired."}
        </small>
      </div>
      {!error && (
        <ul>
          {services.map(([name, service]) => (
            <li key={name} className={service.ok ? "ok" : "warning"}>
              {LABELS[name] || name}: {service.ok ? "ready" : "check settings"}
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={refresh}>
        Check again
      </button>
      {error && globalThis.jarvisDesktop?.restartBackend && (
        <button type="button" onClick={restartBackend}>
          Restart backend
        </button>
      )}
      {!error && health?.services?.voice && !health.services.voice.ok && (
        <button type="button" onClick={openMicrophoneSettings}>
          Microphone settings
        </button>
      )}
    </section>
  );
}
