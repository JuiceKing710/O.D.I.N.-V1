import { beforeEach, describe, expect, it } from "vitest";
import { useAgentStore } from "./agentStore.js";

function apply(event) {
  useAgentStore.getState().applyAgentEvent(event);
}

describe("agentStore", () => {
  beforeEach(() => {
    useAgentStore.setState({
      run: {
        runId: null,
        taskId: null,
        status: "idle",
        goal: "",
        queries: [],
        steps: [],
        report: "",
        sources: [],
        error: "",
      },
    });
  });

  it("ignores non-agent events", () => {
    apply({ type: "chat.message", payload: {} });
    expect(useAgentStore.getState().run.status).toBe("idle");
  });

  it("tracks a full run lifecycle", () => {
    apply({ type: "agent.started", payload: { run_id: "r1", goal: "g", task_id: 7 } });
    apply({ type: "agent.plan", payload: { run_id: "r1", queries: ["a", "b"] } });
    apply({ type: "agent.complete", payload: { report: "done", sources: [{ title: "T", url: "u" }] } });

    const { run } = useAgentStore.getState();
    expect(run.runId).toBe("r1");
    expect(run.taskId).toBe(7);
    expect(run.queries).toEqual(["a", "b"]);
    expect(run.status).toBe("done");
    expect(run.report).toBe("done");
    expect(run.sources).toHaveLength(1);
  });

  it("upserts a step by label so running flips to done in place", () => {
    apply({ type: "agent.started", payload: { run_id: "r1", goal: "g" } });
    apply({ type: "agent.step", payload: { label: "Search: x", kind: "search", status: "running" } });
    apply({ type: "agent.step", payload: { label: "Search: x", kind: "search", status: "done" } });

    const { steps } = useAgentStore.getState().run;
    expect(steps).toHaveLength(1);
    expect(steps[0].status).toBe("done");
  });

  it("applies a poll snapshot and maps complete -> done", () => {
    useAgentStore.getState().startRun("g");
    useAgentStore.getState().applyRunSnapshot({
      run_id: "r9",
      goal: "g",
      status: "complete",
      task_id: 3,
      queries: ["q1"],
      steps: [{ label: "Search: q1", kind: "search", status: "done" }],
      report: "final",
      sources: [{ title: "T", url: "u" }],
    });
    const { run } = useAgentStore.getState();
    expect(run.status).toBe("done");
    expect(run.runId).toBe("r9");
    expect(run.report).toBe("final");
    expect(run.steps).toHaveLength(1);
  });

  it("ignores a snapshot from a stale run", () => {
    useAgentStore.setState({
      run: { runId: "current", status: "running", goal: "g", queries: [], steps: [], report: "", sources: [], error: "" },
    });
    useAgentStore.getState().applyRunSnapshot({ run_id: "old", status: "complete", report: "stale" });
    expect(useAgentStore.getState().run.report).toBe("");
    expect(useAgentStore.getState().run.runId).toBe("current");
  });

  it("captures errors", () => {
    apply({ type: "agent.started", payload: { run_id: "r1", goal: "g" } });
    apply({ type: "agent.error", payload: { error: "boom" } });
    const { run } = useAgentStore.getState();
    expect(run.status).toBe("error");
    expect(run.error).toBe("boom");
  });
});
