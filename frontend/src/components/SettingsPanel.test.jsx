import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel.jsx";
import { AppStateProvider } from "../state/appContext.jsx";
import * as api from "../ipc/apiClient.js";

vi.mock("../ipc/apiClient.js", () => ({
  checkRecoveryIntegrity: vi.fn(),
  createRecoveryBackup: vi.fn(),
  fetchBackupSchedule: vi.fn(),
  fetchMemoryStatus: vi.fn(),
  fetchModels: vi.fn(),
  fetchPermissionRequests: vi.fn(),
  fetchRecoveryBackups: vi.fn(),
  fetchSettings: vi.fn(),
  fetchVoiceStatus: vi.fn(),
  getAuthToken: vi.fn(() => ""),
  loadModel: vi.fn(),
  resolveApiUrl: vi.fn((path) => path),
  resolvePermissionRequest: vi.fn(),
  restoreRecoveryBackup: vi.fn(),
  synthesizeVoice: vi.fn(),
  setAuthToken: vi.fn(),
  setupVoiceModel: vi.fn(),
  updateSettings: vi.fn(),
}));

describe("SettingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchSettings.mockResolvedValue({
      model_name: "local-default",
      permissions: { read_files: "prompt" },
      theme: "dark",
      voice_mode: "push_to_talk",
    });
    api.fetchModels.mockResolvedValue({
      models: [{ id: "llama3.1:8b", loaded: true }],
      provider: { available: true, provider: "ollama", selected_model: "llama3.1:8b" },
    });
    api.fetchVoiceStatus.mockResolvedValue({
      state: "idle",
      stt_adapter: "browser",
      stt_configured: true,
      tts_adapter: "macos-say",
      tts_configured: true,
    });
    api.fetchMemoryStatus.mockResolvedValue({ vector: { enabled: false, provider: "null" } });
    api.checkRecoveryIntegrity.mockResolvedValue({
      ok: true,
      sqlite_ok: true,
      vector_ok: true,
      details: { encryption: "configured" },
    });
    api.fetchRecoveryBackups.mockResolvedValue([]);
    api.fetchBackupSchedule.mockResolvedValue({ enabled: true, hour: 4, retention: 30 });
    api.fetchPermissionRequests.mockResolvedValue([
      {
        request_id: "approval-1",
        permission: "read_files",
        reason: "Read file: notes.txt",
        metadata: { action: "read", bot: "file" },
      },
    ]);
  });

  it("renders voice, recovery, and planned approval state", async () => {
    render(<SettingsPanel />, { wrapper: AppStateProvider });

    expect(await screen.findByText(/macos-say/)).toBeInTheDocument();
    expect(screen.getByText("Read file: notes.txt")).toBeInTheDocument();
    expect(screen.getByText("Planned action: file.read")).toBeInTheDocument();
    expect(screen.getByText("4:00 local time")).toBeInTheDocument();
  });
});
