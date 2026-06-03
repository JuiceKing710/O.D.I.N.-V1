import React, { useEffect, useState } from "react";
import { fetchModels, fetchSettings, loadModel } from "../ipc/apiClient.js";

export function SettingsPanel() {
  const [settings, setSettings] = useState(null);
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([fetchSettings(), fetchModels()])
      .then(([settingsResponse, modelsResponse]) => {
        setSettings(settingsResponse);
        setModels(modelsResponse.models);
        setSelectedModel(
          modelsResponse.models.find((model) => model.loaded)?.id || settingsResponse.model_name,
        );
      })
      .catch((err) => setError(err.message));
  }, []);

  async function handleModelSubmit(event) {
    event.preventDefault();
    if (!selectedModel.trim()) {
      return;
    }
    try {
      const response = await loadModel(selectedModel);
      setModels(response.models);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

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
          <dd>
            <form className="inline-form" onSubmit={handleModelSubmit}>
              <select
                aria-label="Model"
                value={selectedModel}
                onChange={(event) => setSelectedModel(event.target.value)}
              >
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.id}
                    {model.loaded ? " (loaded)" : ""}
                  </option>
                ))}
                {!models.some((model) => model.id === selectedModel) && selectedModel && (
                  <option value={selectedModel}>{selectedModel}</option>
                )}
              </select>
              <button type="submit">Load</button>
            </form>
          </dd>
          <dt>Theme</dt>
          <dd>{settings.theme}</dd>
        </dl>
      ) : (
        <div className="empty-state">Loading settings...</div>
      )}
    </section>
  );
}
