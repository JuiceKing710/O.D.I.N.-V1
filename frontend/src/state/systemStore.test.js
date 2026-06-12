import { beforeEach, describe, expect, it } from "vitest";
import {
  branchIntensity,
  buildStaveIntensities,
  formatBytes,
  formatRate,
  formatUptime,
  STAVE_SUBSYSTEMS,
  useSystemStore,
} from "./systemStore.js";
import { useChatStore } from "./chatStore.js";

describe("chatStore streaming", () => {
  beforeEach(() => {
    useChatStore.setState({ messages: [], streaming: null });
  });

  it("accumulates stream deltas and clears on the final assistant message", () => {
    const apply = useChatStore.getState().applyEvent;
    apply({ type: "chat.stream", payload: { conversation_id: 7, delta: "All " } });
    apply({ type: "chat.stream", payload: { conversation_id: 7, delta: "systems nominal." } });

    expect(useChatStore.getState().streaming).toEqual({
      conversationId: 7,
      text: "All systems nominal.",
      active: true,
    });

    apply({ type: "chat.stream.end", payload: { conversation_id: 7 } });
    expect(useChatStore.getState().streaming.active).toBe(false);

    apply({
      id: "evt-9",
      type: "chat.message",
      payload: { role: "assistant", content: "All systems nominal.", conversation_id: 7 },
    });
    expect(useChatStore.getState().streaming).toBeNull();
    expect(useChatStore.getState().messages).toHaveLength(1);
  });
});

describe("systemStore", () => {
  beforeEach(() => {
    useSystemStore.setState({ metrics: null, nodes: {}, activity: [], nodeActivity: {} });
  });

  it("applies system.metrics events to live metrics", () => {
    useSystemStore.getState().applySystemEvent({
      id: "evt-1",
      type: "system.metrics",
      created_at: new Date().toISOString(),
      payload: { cpu_percent: 41.5, memory: { percent: 60 } },
    });

    expect(useSystemStore.getState().metrics.cpu_percent).toBe(41.5);
    expect(useSystemStore.getState().activity).toHaveLength(0);
  });

  it("collects chat and task events into the activity stream once", () => {
    const event = {
      id: "evt-2",
      type: "chat.message",
      created_at: new Date().toISOString(),
      payload: { role: "assistant", content: "All systems nominal." },
    };
    useSystemStore.getState().applySystemEvent(event);
    useSystemStore.getState().applySystemEvent(event);
    useSystemStore.getState().applySystemEvent({
      id: "evt-3",
      type: "task.updated",
      created_at: new Date().toISOString(),
      payload: { task: { name: "calibrate", status: "complete" } },
    });

    const activity = useSystemStore.getState().activity;
    expect(activity).toHaveLength(2);
    expect(activity[1].source).toBe("Reasoning Engine");
    expect(activity[1].detail).toContain("All systems nominal.");
    expect(activity[0].source).toBe("Automation Hub");
  });

  it("stamps subsystem activity for branch lighting", () => {
    const apply = useSystemStore.getState().applySystemEvent;
    apply({ id: "evt-4", type: "voice.wake", created_at: new Date().toISOString(), payload: {} });
    expect(useSystemStore.getState().nodeActivity.voice_interface).toBeTypeOf("number");

    apply({ id: "evt-5", type: "chat.stream", created_at: new Date().toISOString(), payload: { delta: "Hi" } });
    expect(useSystemStore.getState().nodeActivity.api_orchestrator).toBeTypeOf("number");
    // chat.stream lights a stave but never lands in the activity feed.
    expect(useSystemStore.getState().activity.every((item) => item.id !== "evt-5")).toBe(true);

    apply({ id: "evt-6", type: "system.metrics", created_at: new Date().toISOString(), payload: { cpu_percent: 1 } });
    expect(useSystemStore.getState().nodeActivity.system_heartbeat).toBeTypeOf("number");
  });

  it("decays branch intensity from full to dark", () => {
    const now = Date.now();
    expect(branchIntensity(now, now)).toBe(1);
    expect(branchIntensity(now - 1800, now)).toBeCloseTo(Math.exp(-1), 5);
    expect(branchIntensity(now - 10000, now)).toBe(0);
    expect(branchIntensity(undefined, now)).toBe(0);
  });

  it("keeps the voice stave lit while Odin speaks", () => {
    const now = Date.now();
    const staves = buildStaveIntensities({}, "speaking", now);
    expect(staves).toHaveLength(8);
    expect(staves[STAVE_SUBSYSTEMS.indexOf("voice_interface")]).toBe(1);
    expect(staves[STAVE_SUBSYSTEMS.indexOf("reasoning_engine")]).toBe(0);
  });

  it("formats bytes, rates, and uptime for the HUD", () => {
    expect(formatBytes(96 * 2 ** 40)).toBe("96.0 TB");
    expect(formatRate(1.5e9 / 8)).toBe("1.5 Gbps");
    expect(formatUptime(47 * 86400 + 12 * 3600 + 35 * 60)).toBe("47d 12h 35m");
  });
});
