import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("jarvisDesktop", {
  apiBaseUrl: process.env.JARVIS_BACKEND_URL || "http://127.0.0.1:8000",
  cameraStatus: () => ipcRenderer.invoke("jarvis:camera-status"),
  microphoneStatus: () => ipcRenderer.invoke("jarvis:microphone-status"),
  openCameraSettings: () => ipcRenderer.invoke("jarvis:open-camera-settings"),
  openMicrophoneSettings: () => ipcRenderer.invoke("jarvis:open-microphone-settings"),
  platform: process.platform,
  requestCamera: () => ipcRenderer.invoke("jarvis:request-camera"),
  requestMicrophone: () => ipcRenderer.invoke("jarvis:request-microphone"),
  restartBackend: () => ipcRenderer.invoke("jarvis:restart-backend"),
});
