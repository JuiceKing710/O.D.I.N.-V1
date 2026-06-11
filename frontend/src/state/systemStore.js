import { create } from "zustand";

const ACTIVITY_LIMIT = 30;

const ACTIVITY_LABELS = {
  "chat.message": "Reasoning Engine",
  "voice.state": "Voice Interface",
  "task.updated": "Automation Hub",
  "backup.completed": "Recovery Core",
  "backup.failed": "Recovery Core",
  "permission.requested": "Security Mesh",
  "permission.resolved": "Security Mesh",
  "bot.dispatched": "Automation Hub",
};

function describeEvent(event) {
  if (event.type === "chat.message") {
    const role = event.payload.role === "assistant" ? "O.D.I.N. replied" : "Heard you";
    return `${role}: ${String(event.payload.content || "").slice(0, 80)}`;
  }
  if (event.type === "voice.state") {
    return `Voice ${event.payload.state || "idle"}`;
  }
  if (event.type === "task.updated") {
    const task = event.payload.task || {};
    return `Task "${task.name || "unknown"}" → ${task.status || "updated"}`;
  }
  if (event.type.startsWith("backup")) {
    return event.payload.filename ? `Backup ${event.payload.filename}` : event.type;
  }
  if (event.type.startsWith("permission")) {
    return `${event.payload.permission || "permission"} ${event.type.split(".")[1] || ""}`;
  }
  return event.type;
}

export const useSystemStore = create((set) => ({
  metrics: null,
  nodes: {},
  activity: [],
  setOverview: ({ metrics, nodes }) => set({ metrics, nodes }),
  applySystemEvent: (event) =>
    set((state) => {
      if (event.type === "system.metrics") {
        return { metrics: event.payload };
      }
      if (!ACTIVITY_LABELS[event.type] && !event.type.startsWith("backup")) {
        return {};
      }
      if (state.activity.some((item) => item.id === event.id)) {
        return {};
      }
      const entry = {
        id: event.id,
        source: ACTIVITY_LABELS[event.type] || "System",
        detail: describeEvent(event),
        at: event.created_at,
      };
      return { activity: [entry, ...state.activity].slice(0, ACTIVITY_LIMIT) };
    }),
}));

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(units.length - 1, Math.floor(Math.log2(bytes) / 10));
  return `${(bytes / 2 ** (10 * exponent)).toFixed(exponent > 1 ? 1 : 0)} ${units[exponent]}`;
}

export function formatRate(bytesPerSecond) {
  const bits = (bytesPerSecond || 0) * 8;
  if (bits >= 1e9) {
    return `${(bits / 1e9).toFixed(1)} Gbps`;
  }
  if (bits >= 1e6) {
    return `${(bits / 1e6).toFixed(1)} Mbps`;
  }
  return `${Math.max(0, bits / 1e3).toFixed(0)} Kbps`;
}

export function formatUptime(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "—";
  }
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) {
    return `${days}d ${hours}h ${minutes}m`;
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

export function formatAgo(isoTime) {
  const elapsed = (Date.now() - new Date(isoTime).getTime()) / 1000;
  if (!Number.isFinite(elapsed) || elapsed < 0) {
    return "now";
  }
  if (elapsed < 60) {
    return `${Math.max(1, Math.floor(elapsed))}s ago`;
  }
  if (elapsed < 3600) {
    return `${Math.floor(elapsed / 60)}m ago`;
  }
  return `${Math.floor(elapsed / 3600)}h ago`;
}
