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
  let stopping = false;
  let restartTimer = null;
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
    const process = spawnProcess(
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
    backendProcess = process;
    process.once("exit", () => {
      if (backendProcess !== process) {
        return;
      }
      backendProcess = null;
      if (!stopping && !restartTimer) {
        restartTimer = setTimeout(() => {
          restartTimer = null;
          start();
        }, 1000);
      }
    });
    return process;
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
    stopping = true;
    if (restartTimer) {
      clearTimeout(restartTimer);
      restartTimer = null;
    }
    if (backendProcess && !backendProcess.killed) {
      backendProcess.kill("SIGTERM");
    }
    backendProcess = null;
  }

  function restart() {
    stopping = false;
    if (backendProcess && !backendProcess.killed) {
      backendProcess.kill("SIGTERM");
      backendProcess = null;
    }
    return start();
  }

  return { restart, start, stop, waitUntilReady };
}
