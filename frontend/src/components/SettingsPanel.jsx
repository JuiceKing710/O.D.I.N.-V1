import React, { useEffect, useState } from "react";
import { fetchSettings } from "../ipc/apiClient.js";

export function SettingsPanel() {
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchSettings()
      .then(setSettings)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <section className="panel" aria-label="Settings">
      <header>
        <h1>Settings</h1>
      </header>
      {error && <p className="error">{error}</p>}
      {settings ? (
        <dl className="settings-list">
          <dt>Voice</dt>
          <dd>{settings.voice_mode}</dd>
          <dt>Model</dt>
          <dd>{settings.model_name}</dd>
          <dt>Theme</dt>
          <dd>{settings.theme}</dd>
        </dl>
      ) : (
        <div className="empty-state">Loading settings...</div>
      )}
    </section>
  );
}

