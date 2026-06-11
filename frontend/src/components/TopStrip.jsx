import React, { useEffect, useState } from "react";
import { formatRate, formatUptime, useSystemStore } from "../state/systemStore.js";
import { useAppState } from "../state/appContext.jsx";

export function TopStrip() {
  const metrics = useSystemStore((state) => state.metrics);
  const { currentUser } = useAppState();
  const [, setTick] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => setTick((value) => value + 1), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const ready =
    Boolean(metrics) && Date.now() - new Date(metrics.sampled_at).getTime() < 10000;
  const networkRate = metrics
    ? formatRate(metrics.network.recv_bytes_per_sec + metrics.network.sent_bytes_per_sec)
    : "—";

  return (
    <header className="top-strip">
      <div className="strip-cell">
        <small>System Status</small>
        <strong className={ready ? "status-ok" : "status-warn"}>
          <i className={ready ? "dot ok" : "dot warn"} aria-hidden="true" />
          {ready ? "Operational" : "Starting"}
        </strong>
      </div>
      <div className="strip-cell">
        <small>AI Core Load</small>
        <strong>{metrics ? `${metrics.cpu_percent.toFixed(0)}%` : "—"}</strong>
      </div>
      <div className="strip-cell">
        <small>Network</small>
        <strong>{networkRate}</strong>
      </div>
      <div className="strip-cell">
        <small>Uptime</small>
        <strong>{metrics ? formatUptime(metrics.uptime_seconds) : "—"}</strong>
      </div>
      <div className="strip-user">
        <span className="strip-avatar" aria-hidden="true">
          {currentUser.displayName.slice(0, 1).toUpperCase()}
        </span>
        <div>
          <strong>{currentUser.displayName}</strong>
          <small>Administrator</small>
        </div>
      </div>
    </header>
  );
}
