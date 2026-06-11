import React from "react";
import {
  formatAgo,
  formatBytes,
  formatRate,
  useSystemStore,
} from "../state/systemStore.js";

const DONUT_RADIUS = 52;
const DONUT_CIRCUMFERENCE = 2 * Math.PI * DONUT_RADIUS;

function UtilizationBar({ label, percent, tone, detail }) {
  return (
    <div className="util-row">
      <span className="util-label">{label}</span>
      <div className="util-track" role="img" aria-label={`${label} at ${Math.round(percent)}%`}>
        <div className={`util-fill ${tone}`} style={{ width: `${Math.min(100, percent)}%` }} />
      </div>
      <span className="util-value">{detail || `${Math.round(percent)}%`}</span>
    </div>
  );
}

export function MetricsRail() {
  const metrics = useSystemStore((state) => state.metrics);
  const activity = useSystemStore((state) => state.activity);
  const coreLoad = metrics ? Math.round(metrics.cpu_percent) : 0;
  const networkPercent = metrics
    ? Math.min(100, ((metrics.network.recv_bytes_per_sec + metrics.network.sent_bytes_per_sec) * 8) / 1e7 * 100)
    : 0;

  return (
    <aside className="metrics-rail" aria-label="Live system metrics">
      <section className="rail-card">
        <h3>AI Core Metrics</h3>
        <div className="core-donut">
          <svg viewBox="0 0 120 120" aria-hidden="true">
            <circle className="donut-track" cx="60" cy="60" r={DONUT_RADIUS} />
            <circle
              className="donut-fill"
              cx="60"
              cy="60"
              r={DONUT_RADIUS}
              strokeDasharray={DONUT_CIRCUMFERENCE}
              strokeDashoffset={DONUT_CIRCUMFERENCE * (1 - coreLoad / 100)}
            />
          </svg>
          <div className="donut-center">
            <strong>{metrics ? `${coreLoad}%` : "—"}</strong>
            <small>core load</small>
          </div>
        </div>
      </section>
      <section className="rail-card">
        <header className="rail-card-head">
          <h3>Activity Stream</h3>
          <span className="live-pill">Live</span>
        </header>
        <ul className="activity-list">
          {activity.length === 0 && <li className="activity-empty">Waiting for activity…</li>}
          {activity.slice(0, 6).map((item) => (
            <li key={item.id}>
              <div>
                <strong>{item.source}</strong>
                <p>{item.detail}</p>
              </div>
              <time>{formatAgo(item.at)}</time>
            </li>
          ))}
        </ul>
      </section>
      <section className="rail-card">
        <h3>Resource Utilization</h3>
        {metrics ? (
          <>
            <UtilizationBar label="CPU" percent={metrics.cpu_percent} tone="tone-cyan" />
            <UtilizationBar label="Memory" percent={metrics.memory.percent} tone="tone-violet" />
            <UtilizationBar label="Storage" percent={metrics.disk.percent} tone="tone-amber" />
            <UtilizationBar
              label="Network"
              percent={networkPercent}
              tone="tone-blue"
              detail={formatRate(metrics.network.recv_bytes_per_sec + metrics.network.sent_bytes_per_sec)}
            />
          </>
        ) : (
          <p className="rail-placeholder">Connecting to telemetry…</p>
        )}
      </section>
      <section className="rail-card">
        <h3>Power &amp; Storage</h3>
        {metrics ? (
          <dl className="power-grid">
            <div>
              <dt>Power</dt>
              <dd>
                {metrics.battery
                  ? `${metrics.battery.percent}% ${metrics.battery.plugged ? "· charging" : "· battery"}`
                  : "AC power"}
              </dd>
            </div>
            <div>
              <dt>Disk</dt>
              <dd>
                {formatBytes(metrics.disk.used_bytes)} / {formatBytes(metrics.disk.total_bytes)}
              </dd>
            </div>
            <div>
              <dt>RAM</dt>
              <dd>
                {formatBytes(metrics.memory.used_bytes)} / {formatBytes(metrics.memory.total_bytes)}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="rail-placeholder">Connecting…</p>
        )}
      </section>
    </aside>
  );
}
