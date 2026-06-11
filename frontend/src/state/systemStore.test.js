import { beforeEach, describe, expect, it } from "vitest";
import { formatBytes, formatRate, formatUptime, useSystemStore } from "./systemStore.js";

describe("systemStore", () => {
  beforeEach(() => {
    useSystemStore.setState({ metrics: null, nodes: {}, activity: [] });
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

  it("formats bytes, rates, and uptime for the HUD", () => {
    expect(formatBytes(96 * 2 ** 40)).toBe("96.0 TB");
    expect(formatRate(1.5e9 / 8)).toBe("1.5 Gbps");
    expect(formatUptime(47 * 86400 + 12 * 3600 + 35 * 60)).toBe("47d 12h 35m");
  });
});
