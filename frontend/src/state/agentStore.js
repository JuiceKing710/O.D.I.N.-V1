import { create } from "zustand";

// Mirrors the backend's agent.* event stream into a single "current run" view:
// plan queries, per-step status, and the final cited report. Steps are upserted
// by label so a "running" step flips to "done" in place rather than duplicating.
const emptyRun = {
  runId: null,
  taskId: null,
  status: "idle", // idle | starting | running | done | error
  goal: "",
  queries: [],
  steps: [],
  report: "",
  sources: [],
  error: "",
};

export const useAgentStore = create((set) => ({
  run: { ...emptyRun },
  startRun: (goal) => set({ run: { ...emptyRun, status: "starting", goal } }),
  applyAgentEvent: (event) =>
    set((state) => {
      if (!event.type || !event.type.startsWith("agent.")) {
        return {};
      }
      const payload = event.payload || {};
      const run = state.run;
      switch (event.type) {
        case "agent.started":
          return {
            run: {
              ...emptyRun,
              runId: payload.run_id,
              taskId: payload.task_id,
              status: "running",
              goal: payload.goal || run.goal,
            },
          };
        case "agent.plan":
          return { run: { ...run, queries: payload.queries || [] } };
        case "agent.step": {
          const steps = [...run.steps];
          const step = {
            label: payload.label,
            kind: payload.kind,
            status: payload.status,
            detail: payload.detail || "",
          };
          const index = steps.findIndex((current) => current.label === step.label);
          if (index >= 0) {
            steps[index] = step;
          } else {
            steps.push(step);
          }
          return { run: { ...run, steps } };
        }
        case "agent.complete":
          return {
            run: {
              ...run,
              status: "done",
              report: payload.report || "",
              sources: payload.sources || [],
              taskId: payload.task_id ?? run.taskId,
            },
          };
        case "agent.error":
          return { run: { ...run, status: "error", error: payload.error || "Agent failed" } };
        default:
          return {};
      }
    }),
}));
