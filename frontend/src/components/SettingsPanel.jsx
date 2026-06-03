import React, { useEffect, useState } from "react";
import { fetchModels, fetchSettings, loadModel } from "../ipc/apiClient.js";

export function SettingsPanel() {
  const [settings, setSettings] = useState(null);
  const [models, setModels] = useState([]);
  const [provider, setProvider] = useState(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([fetchSettings(), fetchModels()])
      .then(([settingsResponse, modelsResponse]) => {
        setSettings(settingsResponse);
        setModels(modelsResponse.models);
        setProvider(modelsResponse.provider);
        setSelectedModel(
          modelsResponse.provider?.selected_model ||
            modelsResponse.models.find((model) => model.loaded)?.id ||
            "",
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
      setProvider(response.provider);
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
          <dt>Provider</dt>
          <dd>
            {provider ? (
              <div className="provider-status">
                <strong>{provider.provider}</strong>
                <span className={provider.available ? "status-ok" : "status-error"}>
                  {provider.available ? "connected" : "offline"}
                </span>
                {provider.base_url && <small>{provider.base_url}</small>}
              </div>
            ) : (
              "Unknown"
            )}
          </dd>
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
                {!models.length && <option value="">No Ollama models found</option>}
                {!models.some((model) => model.id === selectedModel) && selectedModel && (
                  <option value={selectedModel}>{selectedModel}</option>
                )}
              </select>
              <button type="submit" disabled={!selectedModel.trim()}>
                Load
              </button>
            </form>
            {provider?.selected_model && (
              <p className="setting-note">Selected: {provider.selected_model}</p>
            )}
            {provider?.error && <p className="error">{provider.error}</p>}
            {provider && !provider.available && (
              <pre className="command-help">{`ollama serve
ollama pull llama3.2`}</pre>
            )}
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
