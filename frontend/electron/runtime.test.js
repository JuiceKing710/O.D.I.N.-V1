import { describe, expect, it, vi } from "vitest";
import { createBackendController } from "./runtime.js";

describe("Electron backend lifecycle", () => {
  it("starts one backend process and stops the owned process", () => {
    const process = {
      kill: vi.fn(),
      killed: false,
      once: vi.fn(),
    };
    const spawnProcess = vi.fn(() => process);
    const controller = createBackendController({
      backendUrl: "http://127.0.0.1:8123",
      projectRoot: "/project",
      existsSync: () => true,
      spawnProcess,
    });

    controller.start();
    controller.start();
    controller.stop();

    expect(spawnProcess).toHaveBeenCalledTimes(1);
    expect(spawnProcess.mock.calls[0][1]).toContain("8123");
    expect(process.kill).toHaveBeenCalledWith("SIGTERM");
  });

  it("reports readiness after the health endpoint responds", async () => {
    const controller = createBackendController({
      backendUrl: "http://127.0.0.1:8123",
      projectRoot: "/project",
      fetchHealth: vi.fn().mockResolvedValue({ ok: true }),
    });

    await expect(controller.waitUntilReady(100)).resolves.toBe(true);
  });
});
