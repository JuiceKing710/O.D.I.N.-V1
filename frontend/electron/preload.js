import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("jarvisDesktop", {
  apiBaseUrl: process.env.JARVIS_BACKEND_URL || "http://127.0.0.1:8000",
  platform: process.platform,
});
