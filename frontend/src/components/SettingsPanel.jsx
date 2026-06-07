import React, { useEffect, useState } from "react";
import {
  checkRecoveryIntegrity,
  createRecoveryBackup,
  fetchMemoryStatus,
  fetchModels,
  fetchVoiceStatus,
  loadModel,
  resolveApiUrl,
  synthesizeVoice,
} from "../ipc/apiClient.js";
import { useAppState } from "../state/appContext.jsx";

const PERMISSION_DECISIONS = ["prompt", "allowed", "denied"];
const THEME_OPTIONS = ["system", "dark", "light"];
const VOICE_MODE_OPTIONS = ["push_to_talk", "always_listening", "disabled"];

export function SettingsPanel() {
  const [models, setModels] = useState([]);
  const [memoryStatus, setMemoryStatus] = useState(null);
  const [backupSnapshot, setBackupSnapshot] = useState(null);
  const [provider, setProvider] = useState(null);
  const [permissionDraft, setPermissionDraft] = useState({});
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const [recoveryReport, setRecoveryReport] = useState(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [error, setError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);
  const [themeDraft, setThemeDraft] = useState("system");
  const [voiceStatus, setVoiceStatus] = useState(null);
  const [voiceTesting, setVoiceTesting] = useState(false);
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
    fetchVoiceStatus()
      .then((status) => {
        if (!cancelled) {
          setVoiceStatus(status);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
        }
      });
    fetchMemoryStatus()
      .then((status) => {
        if (!cancelled) {
          setMemoryStatus(status);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
        }
      });
    checkRecoveryIntegrity()
      .then((report) => {
        if (!cancelled) {
          setRecoveryReport(report);
        }
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

  async function handleVoiceTest() {
    setVoiceTesting(true);
    setSaveNotice("");
    setError("");
    try {
      const response = await synthesizeVoice({
        text: "Jarvis backend voice synthesis is online.",
      });
      setVoiceStatus((current) => ({
        ...(current || {}),
        state: response.state,
      }));
      const audio = new Audio(resolveApiUrl(response.audio_url));
      await audio.play();
      setSaveNotice("Backend voice test played.");
    } catch (err) {
      setError(err.message);
    } finally {
      setVoiceTesting(false);
    }
  }

  async function handleRecoveryCheck() {
    setRecoveryLoading(true);
    setSaveNotice("");
    setError("");
    try {
      setRecoveryReport(await checkRecoveryIntegrity());
      setSaveNotice("Recovery integrity checked.");
    } catch (err) {
      setError(err.message);
    } finally {
      setRecoveryLoading(false);
    }
  }

  async function handleBackupCreate() {
    setRecoveryLoading(true);
    setSaveNotice("");
    setError("");
    try {
      const snapshot = await createRecoveryBackup();
      setBackupSnapshot(snapshot);
      setRecoveryReport(await checkRecoveryIntegrity());
      setSaveNotice("Backup created.");
    } catch (err) {
      setError(err.message);
    } finally {
      setRecoveryLoading(false);
    }
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

          <section className="settings-section" aria-label="Backend voice">
            <div className="section-heading">
              <h2>Voice</h2>
              {voiceStatus && (
                <span className={voiceStatus.tts_configured ? "status-ok" : "status-error"}>
                  {voiceStatus.tts_configured ? "Ready" : "Offline"}
                </span>
              )}
            </div>
            {voiceStatus ? (
              <>
                <dl className="settings-list">
                  <dt>State</dt>
                  <dd>{voiceStatus.state}</dd>
                  <dt>Speech to text</dt>
                  <dd>
                    {voiceStatus.stt_adapter} ·{" "}
                    {voiceStatus.stt_configured ? "configured" : "not configured"}
                  </dd>
                  <dt>Text to speech</dt>
                  <dd>
                    {voiceStatus.tts_adapter} ·{" "}
                    {voiceStatus.tts_configured ? "configured" : "not configured"}
                  </dd>
                </dl>
                <button
                  className="settings-action"
                  type="button"
                  disabled={!voiceStatus.tts_configured || voiceTesting}
                  onClick={handleVoiceTest}
                >
                  {voiceTesting ? "Testing" : "Test"}
                </button>
              </>
            ) : (
              <div className="empty-state">Voice status unavailable.</div>
            )}
          </section>

          <section className="settings-section" aria-label="Long-term memory">
            <div className="section-heading">
              <h2>Long-term Memory</h2>
              {memoryStatus && (
                <span className={memoryStatus.vector.enabled ? "status-ok" : "status-error"}>
                  {memoryStatus.vector.enabled ? "Vector enabled" : "SQLite fallback"}
                </span>
              )}
            </div>
            {memoryStatus ? (
              <dl className="settings-list">
                <dt>Provider</dt>
                <dd>{memoryStatus.vector.provider}</dd>
                <dt>Collections</dt>
                <dd>
                  {Array.isArray(memoryStatus.vector.collections)
                    ? memoryStatus.vector.collections.join(", ")
                    : "messages, documents, tasks"}
                </dd>
              </dl>
            ) : (
              <div className="empty-state">Memory status unavailable.</div>
            )}
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

          <section className="settings-section" aria-label="Recovery">
            <div className="section-heading">
              <h2>Recovery</h2>
              {recoveryReport && (
                <span className={recoveryReport.ok ? "status-ok" : "status-error"}>
                  {recoveryReport.ok ? "Healthy" : "Check"}
                </span>
              )}
            </div>
            {recoveryReport ? (
              <>
                <dl className="settings-list">
                  <dt>SQLite</dt>
                  <dd>{recoveryReport.sqlite_ok ? "ok" : "failed"}</dd>
                  <dt>Vector</dt>
                  <dd>{recoveryReport.vector_ok ? "ok" : "failed"}</dd>
                  <dt>Encryption</dt>
                  <dd>{recoveryReport.details?.encryption || "unknown"}</dd>
                </dl>
                {backupSnapshot && (
                  <p className="setting-note">Latest backup: {backupSnapshot.path}</p>
                )}
              </>
            ) : (
              <div className="empty-state">Recovery status unavailable.</div>
            )}
            <div className="settings-actions">
              <button type="button" disabled={recoveryLoading} onClick={handleRecoveryCheck}>
                {recoveryLoading ? "Checking" : "Check"}
              </button>
              <button type="button" disabled={recoveryLoading} onClick={handleBackupCreate}>
                {recoveryLoading ? "Working" : "Backup"}
              </button>
            </div>
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
