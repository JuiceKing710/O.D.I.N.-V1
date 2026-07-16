import { beforeEach, describe, expect, it } from "vitest";
import { useSecurityStore } from "./securityStore.js";

describe("securityStore", () => {
  beforeEach(() => {
    useSecurityStore.setState({ status: null, alerts: [] });
  });

  it("prepends a live security.alert and dedupes by alert_id", () => {
    const apply = useSecurityStore.getState().applyEvent;
    apply({
      type: "security.alert",
      payload: { alert_id: "a1", camera: "Front", at: "2026-07-16T00:00:00Z", summary: "a person" },
    });
    apply({
      type: "security.alert",
      payload: { alert_id: "a2", camera: "Drive", at: "2026-07-16T00:01:00Z", summary: "a car" },
    });
    // Duplicate id is ignored.
    apply({
      type: "security.alert",
      payload: { alert_id: "a1", camera: "Front", at: "2026-07-16T00:00:00Z", summary: "a person" },
    });

    const alerts = useSecurityStore.getState().alerts;
    expect(alerts).toHaveLength(2);
    expect(alerts[0].alert_id).toBe("a2"); // newest first
  });

  it("ignores unrelated events", () => {
    useSecurityStore.getState().applyEvent({ type: "chat.message", payload: {} });
    expect(useSecurityStore.getState().alerts).toHaveLength(0);
  });

  it("merges fetched alerts without duplicating existing ones", () => {
    const { setAlerts } = useSecurityStore.getState();
    setAlerts([{ alert_id: "a1", camera: "Front", at: "t", summary: "x" }]);
    setAlerts([
      { alert_id: "a1", camera: "Front", at: "t", summary: "x" },
      { alert_id: "a2", camera: "Yard", at: "t2", summary: "y" },
    ]);
    expect(useSecurityStore.getState().alerts).toHaveLength(2);
  });
});
