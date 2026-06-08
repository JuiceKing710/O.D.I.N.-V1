import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StartupHealth } from "./StartupHealth.jsx";
import { fetchStartupHealth } from "../ipc/apiClient.js";

vi.mock("../ipc/apiClient.js", () => ({
  fetchStartupHealth: vi.fn(),
}));

describe("StartupHealth", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("stays out of the way when every service is ready", async () => {
    fetchStartupHealth.mockResolvedValue({
      ready: true,
      services: {
        backend: { ok: true },
        model: { ok: true },
        voice: { ok: true },
        memory: { ok: true },
        backups: { ok: true },
      },
    });

    const { container } = render(<StartupHealth />);
    await waitFor(() => expect(fetchStartupHealth).toHaveBeenCalled());

    expect(container).toBeEmptyDOMElement();
  });

  it("shows actionable status for an unavailable optional service", async () => {
    fetchStartupHealth.mockResolvedValue({
      ready: true,
      services: {
        backend: { ok: true },
        model: { ok: false },
        voice: { ok: true },
        memory: { ok: true },
        backups: { ok: true },
      },
    });

    render(<StartupHealth />);

    expect(await screen.findByText("Jarvis needs attention")).toBeInTheDocument();
    expect(screen.getByText("Ollama model: check settings")).toBeInTheDocument();
  });
});
