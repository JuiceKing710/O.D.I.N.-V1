import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/testSetup.js",
    // node_modules is a symlink to node_modules.nosync (kept out of iCloud),
    // which vitest's default node_modules exclude does not match.
    exclude: ["**/node_modules/**", "**/node_modules.nosync/**", "**/dist/**"],
  },
});
