import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SecurityPanel } from "./SecurityPanel.jsx";
import { useSecurityStore } from "../state/securityStore.js";

const api = {
  fetchSecurityStatus: vi.fn(),
  fetchSecurityAlerts: vi.fn(),
  runSecurityScan: vi.fn(),
};

vi.mock("../ipc/apiClient.js", () => ({
  fetchSecurityStatus: (...args) => api.fetchSecurityStatus(...args),
  fetchSecurityAlerts: (...args) => api.fetchSecurityAlerts(...args),
  runSecurityScan: (...args) => api.runSecurityScan(...args),
  resolveMediaUrl: (path) => path,
}));

const STATUS = {
  enabled: true,
  running: true,
  interval_seconds: 30,
  cooldown_seconds: 180,
  watch_for: ["a person", "a package"],
  notifier: "ntfy",
  push_enabled: true,
  cameras: [
    { name: "Front Door", configured: true, last_error: null, last_scanned_at: null },
    { name: "Garage", configured: false, last_error: "ffmpeg not installed", last_scanned_at: null },
  ],
  alert_count: 0,
  last_alert_at: null,
  last_error: null,
};

describe("SecurityPanel", () => {
  beforeEach(() => {
    useSecurityStore.setState({ status: null, alerts: [] });
    api.fetchSecurityStatus.mockResolvedValue(STATUS);
    api.fetchSecurityAlerts.mockResolvedValue([]);
    api.runSecurityScan.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders monitor status, cameras, and watch list", async () => {
    render(<SecurityPanel />);

    expect(await screen.findByText("Monitoring live")).toBeInTheDocument();
    expect(screen.getByText("Front Door")).toBeInTheDocument();
    expect(screen.getByText("ffmpeg not installed")).toBeInTheDocument();
    expect(screen.getByText("a person")).toBeInTheDocument();
    expect(screen.getByText("a package")).toBeInTheDocument();
  });

  it("shows a disabled hint when the monitor is off", async () => {
    api.fetchSecurityStatus.mockResolvedValue({ ...STATUS, enabled: false, running: false });
    render(<SecurityPanel />);

    expect(await screen.findByText("Disabled")).toBeInTheDocument();
    expect(screen.getByText(/JARVIS_SECURITY_MONITOR=enabled/)).toBeInTheDocument();
  });

  it("renders alerts with a snapshot thumbnail", async () => {
    api.fetchSecurityAlerts.mockResolvedValue([
      {
        alert_id: "a1",
        camera: "Front Door",
        at: "2026-07-16T12:00:00Z",
        summary: "a stranger on the porch",
        image_url: "/api/v1/security/capture/front-1.jpg",
      },
    ]);
    render(<SecurityPanel />);

    const img = await screen.findByRole("img", { name: /Front Door: a stranger on the porch/i });
    expect(img).toHaveAttribute("src", "/api/v1/security/capture/front-1.jpg");
    expect(screen.getByText("a stranger on the porch")).toBeInTheDocument();
  });

  it("runs an on-demand scan and reports the outcome", async () => {
    api.runSecurityScan.mockResolvedValue([
      { alert_id: "s1", camera: "Front Door", at: "t", summary: "motion", image_url: null },
    ]);
    render(<SecurityPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Scan now" }));

    await waitFor(() => expect(api.runSecurityScan).toHaveBeenCalled());
    expect(await screen.findByText(/Scan flagged 1 camera/)).toBeInTheDocument();
  });
});
