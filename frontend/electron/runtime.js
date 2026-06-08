import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export function createBackendController({
  backendUrl,
  projectRoot,
  env = process.env,
  existsSync = fs.existsSync,
  fetchHealth = fetch,
  spawnProcess = spawn,
}) {
  let backendProcess = null;
  const parsedUrl = new URL(backendUrl);
  const port = parsedUrl.port || "8000";

  function pythonExecutable() {
    const virtualEnvPython = path.join(projectRoot, ".venv", "bin", "python");
    return existsSync(virtualEnvPython) ? virtualEnvPython : "python3";
  }

  function start() {
    if (backendProcess) {
      return backendProcess;
    }
    backendProcess = spawnProcess(
      pythonExecutable(),
      [
        "-m",
        "uvicorn",
        "jarvis.backend.api.main:app",
        "--host",
        parsedUrl.hostname,
        "--port",
        port,
      ],
      {
        cwd: projectRoot,
        env: { ...env, PYTHONUNBUFFERED: "1" },
        stdio: "inherit",
      },
    );
    backendProcess.once("exit", () => {
      backendProcess = null;
    });
    return backendProcess;
  }

  async function waitUntilReady(timeoutMs = 20000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const response = await fetchHealth(`${backendUrl}/api/v1/health/startup`);
        if (response.ok) {
          return true;
        }
      } catch {
        // Backend is still starting.
      }
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
    return false;
  }

  function stop() {
    if (backendProcess && !backendProcess.killed) {
      backendProcess.kill("SIGTERM");
    }
    backendProcess = null;
  }

  return { start, stop, waitUntilReady };
}
