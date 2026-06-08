import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("jarvisDesktop", {
  apiBaseUrl: process.env.JARVIS_BACKEND_URL || "http://127.0.0.1:8000",
  microphoneStatus: () => ipcRenderer.invoke("jarvis:microphone-status"),
  openMicrophoneSettings: () => ipcRenderer.invoke("jarvis:open-microphone-settings"),
  platform: process.platform,
  requestMicrophone: () => ipcRenderer.invoke("jarvis:request-microphone"),
  restartBackend: () => ipcRenderer.invoke("jarvis:restart-backend"),
});
