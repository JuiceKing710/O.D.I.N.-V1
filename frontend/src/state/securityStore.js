import { create } from "zustand";

const ALERT_LIMIT = 50;

function alertKey(alert) {
  return alert.alert_id || `${alert.camera}-${alert.at}`;
}

// Prepend genuinely new alerts (newest first) while leaving already-known ones
// in place, so a duplicate delivery of the same alert never reorders the list.
function mergeAlerts(existing, incoming) {
  const known = new Set(existing.map(alertKey));
  const fresh = [];
  const freshKeys = new Set();
  for (const alert of incoming) {
    const key = alertKey(alert);
    if (known.has(key) || freshKeys.has(key)) {
      continue;
    }
    freshKeys.add(key);
    fresh.push(alert);
  }
  return [...fresh, ...existing].slice(0, ALERT_LIMIT);
}

// Live security state for the monitoring tab. Status comes from polling
// /security/status; alerts arrive both from /security/alerts (on open) and live
// over the event bus as `security.alert`, deduped by alert_id.
export const useSecurityStore = create((set) => ({
  status: null,
  alerts: [],
  setStatus: (status) => set({ status }),
  setAlerts: (alerts) => set((state) => ({ alerts: mergeAlerts(state.alerts, alerts) })),
  applyEvent: (event) =>
    set((state) => {
      if (event.type !== "security.alert") {
        return {};
      }
      return { alerts: mergeAlerts(state.alerts, [event.payload]) };
    }),
}));
