import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("jarvisDesktop", {
  platform: process.platform,
});

