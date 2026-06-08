import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatView } from "./ChatView.jsx";

const chatState = {
  addMessage: vi.fn(),
  clearMessages: vi.fn(),
  messages: [],
  setMessages: vi.fn(),
  setVoiceState: vi.fn(),
  voiceState: "idle",
};
let appSettings = { voice_mode: "push_to_talk" };

vi.mock("../state/appContext.jsx", () => ({
  useAppState: () => ({
    conversationId: null,
    currentUser: { username: "local-user" },
    settings: appSettings,
    setConversationId: vi.fn(),
    startNewConversation: vi.fn(),
  }),
}));
vi.mock("../state/chatStore.js", () => ({
  useChatStore: (selector) => selector(chatState),
}));
vi.mock("../hooks/useSpeechSynthesis.js", () => ({
  useSpeechSynthesis: () => ({
    available: false,
    speaking: false,
    stop: vi.fn(),
    warmUp: vi.fn(),
  }),
}));
vi.mock("../ipc/apiClient.js", () => ({
  createReflection: vi.fn(),
  fetchConversationMessages: vi.fn(),
  fetchConversations: vi.fn().mockResolvedValue([]),
  fetchModels: vi.fn().mockResolvedValue({
    models: [],
    provider: { available: true, provider: "echo", selected_model: "echo-local" },
  }),
  fetchReflections: vi.fn(),
  fetchVoiceStatus: vi.fn().mockResolvedValue({ tts_configured: true }),
  resolveApiUrl: vi.fn((path) => path),
  sendChatMessage: vi.fn(),
  synthesizeVoice: vi.fn(),
  transcribeVoiceAudio: vi.fn(),
}));

describe("ChatView microphone", () => {
  beforeEach(() => {
    appSettings = { voice_mode: "push_to_talk" };
    globalThis.jarvisDesktop = { requestMicrophone: vi.fn().mockResolvedValue(true) };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        enumerateDevices: vi.fn().mockResolvedValue([]),
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    });
    globalThis.MediaRecorder = class {
      constructor() {
        this.mimeType = "audio/webm";
      }
      start() {}
      stop() {}
    };
  });

  afterEach(() => {
    cleanup();
    delete globalThis.jarvisDesktop;
    delete globalThis.MediaRecorder;
  });

  it("uses one permission-aware microphone control", async () => {
    render(<ChatView onOpenCoreFocus={vi.fn()} />);

    expect(screen.queryByText("Backend Mic")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mic" }));

    await waitFor(() => expect(globalThis.jarvisDesktop.requestMicrophone).toHaveBeenCalled());
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send Voice" })).toBeInTheDocument();
  });

  it("starts the local microphone path for always-listening mode", async () => {
    appSettings = { voice_mode: "always_listening" };

    render(<ChatView onOpenCoreFocus={vi.fn()} />);

    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Send Voice" })).toBeInTheDocument();
  });
});
