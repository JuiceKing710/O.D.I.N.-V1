import { app, BrowserWindow, ipcMain, session, shell, systemPreferences } from "electron";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createBackendController } from "./runtime.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const isDev = process.env.VITE_DEV_SERVER_URL;
const projectRoot = path.resolve(__dirname, "..", "..");
const backendUrl = process.env.JARVIS_BACKEND_URL || "http://127.0.0.1:8000";
const backend = createBackendController({ backendUrl, projectRoot });

async function createWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 620,
    title: "O.D.I.N. Core System",
    backgroundColor: "#11151c",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  window.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    window.loadURL(isDev);
  } else {
    await backend.waitUntilReady();
    window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

app.whenReady().then(() => {
  session.defaultSession.setPermissionCheckHandler((_webContents, permission, _origin, details) => {
    return permission === "media" && (details.mediaType === "audio" || details.mediaType === "video");
  });
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback, details) => {
    const audioVideoOnly =
      permission === "media" &&
      Array.isArray(details.mediaTypes) &&
      details.mediaTypes.length > 0 &&
      details.mediaTypes.every((type) => type === "audio" || type === "video");
    callback(audioVideoOnly);
  });
  ipcMain.handle("jarvis:microphone-status", () =>
    process.platform === "darwin"
      ? systemPreferences.getMediaAccessStatus("microphone")
      : "unknown",
  );
  ipcMain.handle("jarvis:request-microphone", async () =>
    process.platform === "darwin"
      ? systemPreferences.askForMediaAccess("microphone")
      : true,
  );
  ipcMain.handle("jarvis:open-microphone-settings", () =>
    shell.openExternal(
      "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    ),
  );
  ipcMain.handle("jarvis:camera-status", () =>
    process.platform === "darwin"
      ? systemPreferences.getMediaAccessStatus("camera")
      : "unknown",
  );
  ipcMain.handle("jarvis:request-camera", async () =>
    process.platform === "darwin"
      ? systemPreferences.askForMediaAccess("camera")
      : true,
  );
  ipcMain.handle("jarvis:open-camera-settings", () =>
    shell.openExternal(
      "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
    ),
  );
  ipcMain.handle("jarvis:restart-backend", async () => {
    backend.restart();
    return backend.waitUntilReady();
  });
  backend.start();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", backend.stop);
