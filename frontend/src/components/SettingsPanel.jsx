import React, { useEffect, useState } from "react";
import { fetchModels, loadModel } from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";

export function SettingsPanel() {
  const [models, setModels] = useState([]);
  const [provider, setProvider] = useState(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [error, setError] = useState("");
  const { refreshSettings, settings, settingsError, settingsLoading } = useAppState();
  const displayError = error || settingsError;
  const permissionEntries = Object.entries(settings?.permissions || {});

  useEffect(() => {
    let cancelled = false;
    refreshSettings().catch(() => {
      // The shared settings error is rendered from context.
    });
    fetchModels()
      .then((modelsResponse) => {
        if (cancelled) {
          return;
        }
        setModels(modelsResponse.models);
        setProvider(modelsResponse.provider);
        setSelectedModel(
          modelsResponse.provider?.selected_model ||
            modelsResponse.models.find((model) => model.loaded)?.id ||
            "",
        );
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refreshSettings]);

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
      {displayError && <p className="error">{displayError}</p>}
      {settings ? (
        <div className="settings-grid">
          <section className="settings-section" aria-label="Model provider">
            <div className="section-heading">
              <h2>Model</h2>
              {provider && (
                <span className={provider.available ? "status-ok" : "status-error"}>
                  {provider.available ? "Connected" : "Offline"}
                </span>
              )}
            </div>
            <dl className="settings-list">
              <dt>Provider</dt>
              <dd>
                {provider ? (
                  <div className="provider-status">
                    <strong>{provider.provider}</strong>
                    {provider.base_url && <small>{provider.base_url}</small>}
                  </div>
                ) : (
                  "Unknown"
                )}
              </dd>
              <dt>Selected</dt>
              <dd>{provider?.selected_model || "No model selected"}</dd>
            </dl>
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
            {provider?.error && <p className="error">{provider.error}</p>}
            {provider && !provider.available && (
              <pre className="command-help">{`ollama serve
ollama pull llama3.2`}</pre>
            )}
          </section>

          <section className="settings-section" aria-label="Interface settings">
            <div className="section-heading">
              <h2>Interface</h2>
            </div>
            <dl className="settings-list">
              <dt>Voice</dt>
              <dd>{settings.voice_mode}</dd>
              <dt>Theme</dt>
              <dd>{settings.theme}</dd>
            </dl>
          </section>

          <section className="settings-section permissions-section" aria-label="Permissions">
            <div className="section-heading">
              <h2>Permissions</h2>
              <span>{permissionEntries.length}</span>
            </div>
            {permissionEntries.length ? (
              <ul className="permission-list">
                {permissionEntries.map(([name, decision]) => (
                  <li key={name}>
                    <span>{name.replaceAll("_", " ")}</span>
                    <strong>{decision}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="empty-state">No permission overrides configured.</div>
            )}
          </section>
        </div>
      ) : (
        <div className="empty-state">
          {settingsLoading ? "Loading settings..." : "Settings unavailable."}
        </div>
      )}
    </section>
  );
}
