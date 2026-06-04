import React, { useEffect, useState } from "react";
import { fetchModels, loadModel } from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";

const PERMISSION_DECISIONS = ["prompt", "allowed", "denied"];
const THEME_OPTIONS = ["system", "dark", "light"];
const VOICE_MODE_OPTIONS = ["push_to_talk", "always_listening", "disabled"];

export function SettingsPanel() {
  const [models, setModels] = useState([]);
  const [provider, setProvider] = useState(null);
  const [permissionDraft, setPermissionDraft] = useState({});
  const [selectedModel, setSelectedModel] = useState("");
  const [error, setError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);
  const [themeDraft, setThemeDraft] = useState("system");
  const [voiceModeDraft, setVoiceModeDraft] = useState("push_to_talk");
  const { refreshSettings, saveSettings, settings, settingsError, settingsLoading } =
    useAppState();
  const displayError = error || settingsError;
  const permissionEntries = Object.entries(permissionDraft);

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

  useEffect(() => {
    if (!settings) {
      return;
    }
    setPermissionDraft(settings.permissions || {});
    setThemeDraft(settings.theme);
    setVoiceModeDraft(settings.voice_mode);
  }, [settings]);

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

  async function handleInterfaceSubmit(event) {
    event.preventDefault();
    setSavingSettings(true);
    setSaveNotice("");
    setError("");
    try {
      await saveSettings({
        theme: themeDraft,
        voice_mode: voiceModeDraft,
      });
      setSaveNotice("Interface settings saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingSettings(false);
    }
  }

  async function handlePermissionsSubmit(event) {
    event.preventDefault();
    setSavingSettings(true);
    setSaveNotice("");
    setError("");
    try {
      await saveSettings({ permissions: permissionDraft });
      setSaveNotice("Permissions saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingSettings(false);
    }
  }

  function updatePermission(name, decision) {
    setPermissionDraft((current) => ({
      ...current,
      [name]: decision,
    }));
  }

  return (
    <section className="panel" aria-label="Settings">
      <header>
        <h1>Settings</h1>
      </header>
      {displayError && <p className="error">{displayError}</p>}
      {saveNotice && <p className="setting-note">{saveNotice}</p>}
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
            <form className="settings-form" onSubmit={handleInterfaceSubmit}>
              <label>
                Voice
                <select
                  value={voiceModeDraft}
                  onChange={(event) => setVoiceModeDraft(event.target.value)}
                >
                  {VOICE_MODE_OPTIONS.map((mode) => (
                    <option key={mode} value={mode}>
                      {mode}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Theme
                <select value={themeDraft} onChange={(event) => setThemeDraft(event.target.value)}>
                  {THEME_OPTIONS.map((theme) => (
                    <option key={theme} value={theme}>
                      {theme}
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit" disabled={savingSettings || settingsLoading}>
                {savingSettings ? "Saving" : "Save"}
              </button>
            </form>
          </section>

          <section className="settings-section permissions-section" aria-label="Permissions">
            <div className="section-heading">
              <h2>Permissions</h2>
              <span>{permissionEntries.length}</span>
            </div>
            {permissionEntries.length ? (
              <form className="settings-form" onSubmit={handlePermissionsSubmit}>
                <ul className="permission-list">
                  {permissionEntries.map(([name, decision]) => (
                    <li key={name}>
                      <span>{name.replaceAll("_", " ")}</span>
                      <select
                        aria-label={`${name.replaceAll("_", " ")} permission`}
                        value={decision}
                        onChange={(event) => updatePermission(name, event.target.value)}
                      >
                        {PERMISSION_DECISIONS.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    </li>
                  ))}
                </ul>
                <button type="submit" disabled={savingSettings || settingsLoading}>
                  {savingSettings ? "Saving" : "Save"}
                </button>
              </form>
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
