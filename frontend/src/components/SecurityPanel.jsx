import React, { useEffect, useRef, useState } from "react";
import {
  fetchSecurityAlerts,
  fetchSecurityStatus,
  resolveMediaUrl,
  runSecurityScan,
} from "../ipc/apiClient.js";
import { useSecurityStore } from "../state/securityStore.js";

const STATUS_POLL_MS = 10000;

function formatTime(value) {
  if (!value) {
    return "—";
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "short",
      timeStyle: "medium",
    }).format(new Date(value));
  } catch {
    return String(value);
  }
}

export function SecurityPanel() {
  const status = useSecurityStore((state) => state.status);
  const alerts = useSecurityStore((state) => state.alerts);
  const setStatus = useSecurityStore((state) => state.setStatus);
  const setAlerts = useSecurityStore((state) => state.setAlerts);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanNotice, setScanNotice] = useState("");
  const pollRef = useRef(null);

  async function refreshStatus() {
    try {
      setStatus(await fetchSecurityStatus());
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function refreshAlerts() {
    try {
      setAlerts(await fetchSecurityAlerts(25));
    } catch {
      // Alerts also arrive live over the event bus; a failed fetch isn't fatal.
    }
  }

  useEffect(() => {
    refreshStatus();
    refreshAlerts();
    pollRef.current = window.setInterval(refreshStatus, STATUS_POLL_MS);
    return () => window.clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function scanNow() {
    setScanning(true);
    setScanNotice("");
    setError("");
    try {
      const found = await runSecurityScan();
      setAlerts(found);
      setScanNotice(
        found.length
          ? `Scan flagged ${found.length} camera${found.length > 1 ? "s" : ""}.`
          : "Scan complete — nothing notable on any camera.",
      );
      await refreshStatus();
    } catch (err) {
      setError(err.message);
    } finally {
      setScanning(false);
    }
  }

  const cameras = status?.cameras || [];
  const configuredCameras = cameras.filter((camera) => camera.configured).length;
  const monitorState = !status
    ? "pending"
    : status.running
      ? "ok"
      : status.enabled
        ? "pending"
        : "error";
  const monitorLabel = !status
    ? "Checking…"
    : status.running
      ? "Monitoring live"
      : status.enabled
        ? "Enabled — idle"
        : "Disabled";

  return (
    <section className="panel security-panel" aria-label="Security monitor">
      <header className="security-header">
        <div>
          <h1>Security Monitor</h1>
          <p>
            Odin watches your cameras with its local vision model and raises an alert when it sees
            something worth your attention. Footage never leaves this machine.
          </p>
          <div className="runtime-status" aria-label="Monitor status">
            <span className={`status-light ${monitorState}`} />
            <span>{monitorLabel}</span>
            {status && (
              <>
                <span>
                  {configuredCameras}/{cameras.length || 0} cameras
                </span>
                <span>{status.push_enabled ? "Push on" : "Push off"}</span>
              </>
            )}
          </div>
        </div>
        <div className="security-actions">
          <button type="button" onClick={scanNow} disabled={scanning || !cameras.length}>
            {scanning ? "Scanning…" : "Scan now"}
          </button>
        </div>
      </header>

      {error && <p className="error provider-notice">{error}</p>}
      {scanNotice && <p className="voice-notice">{scanNotice}</p>}

      {status && !status.enabled && (
        <p className="setting-note">
          The monitor is off. Start the backend with <code>JARVIS_SECURITY_MONITOR=enabled</code> and
          a <code>data/cameras.json</code> to begin watching. See the README → Security camera
          monitor.
        </p>
      )}

      {status && !cameras.length && status.enabled && (
        <p className="setting-note">
          No cameras are configured yet. Add them to <code>data/cameras.json</code> (one RTSP URL per
          NVR channel) and restart the backend.
        </p>
      )}

      {cameras.length > 0 && (
        <div className="security-cameras">
          <h2>Cameras</h2>
          <ul className="camera-list">
            {cameras.map((camera) => (
              <li key={camera.name} className={`camera-row ${camera.configured ? "" : "unconfigured"}`}>
                <span className={`status-light ${camera.last_error ? "error" : camera.configured ? "ok" : "pending"}`} />
                <span className="camera-name">{camera.name}</span>
                <small>
                  {camera.last_error
                    ? camera.last_error
                    : camera.last_scanned_at
                      ? `Last checked ${formatTime(camera.last_scanned_at)}`
                      : camera.configured
                        ? "Waiting for first scan"
                        : "Not configured"}
                </small>
              </li>
            ))}
          </ul>
        </div>
      )}

      {status && (
        <div className="security-watch">
          <h2>Watching for</h2>
          <ul className="watch-list">
            {status.watch_for.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <small>
            Scans every {status.interval_seconds}s · {status.cooldown_seconds}s cooldown per camera ·
            alerts via {status.notifier === "unconfigured" ? "the app only" : status.notifier}
          </small>
        </div>
      )}

      <div className="security-alerts">
        <h2>Recent alerts</h2>
        {alerts.length === 0 ? (
          <p className="empty-state">No alerts yet. When Odin spots something, it shows up here.</p>
        ) : (
          <ul className="alert-list">
            {alerts.map((alert) => (
              <li key={alert.alert_id} className="alert-card">
                {alert.image_url && (
                  <img
                    className="alert-thumb"
                    src={resolveMediaUrl(alert.image_url)}
                    alt={`${alert.camera}: ${alert.summary}`}
                    loading="lazy"
                  />
                )}
                <div className="alert-body">
                  <div className="alert-meta">
                    <strong>{alert.camera}</strong>
                    <small>{formatTime(alert.at)}</small>
                  </div>
                  <p>{alert.summary}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
