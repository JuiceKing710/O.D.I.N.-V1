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
const analyzeVisionImage = vi.fn().mockResolvedValue({ description: "a person waving", state: "idle" });

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
  fetchVisionStatus: vi.fn().mockResolvedValue({ configured: true, adapter: "ollama-vision" }),
  analyzeScreen: vi.fn().mockResolvedValue({ description: "a code editor", state: "idle" }),
  analyzeVisionImage: (...args) => analyzeVisionImage(...args),
  resolveMediaUrl: vi.fn((path) => path),
  sendChatMessage: vi.fn().mockResolvedValue({ conversation_id: 1, reply: "I see you." }),
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

  it("opens the mic automatically when hands-free conversation is enabled", async () => {
    render(<ChatView onOpenCoreFocus={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Converse" })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Converse" }));

    expect(screen.getByRole("button", { name: "Conversation On" })).toBeInTheDocument();
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled(), {
      timeout: 2000,
    });
  });
});

describe("ChatView generated images", () => {
  beforeEach(() => {
    appSettings = { voice_mode: "push_to_talk" };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { enumerateDevices: vi.fn().mockResolvedValue([]) },
    });
  });

  afterEach(() => {
    cleanup();
    chatState.messages = [];
  });

  it("renders an image when an assistant message carries an image_url", async () => {
    chatState.messages = [
      {
        id: "img-1",
        role: "assistant",
        content: "Here's an AI-generated image of: a red bicycle",
        imageUrl: "/api/v1/image/file/abc123.png",
      },
    ];

    render(<ChatView onOpenCoreFocus={vi.fn()} />);

    const image = await screen.findByRole("img", { name: /AI-generated image of: a red bicycle/i });
    expect(image).toHaveAttribute("src", "/api/v1/image/file/abc123.png");
    expect(screen.getByRole("button", { name: "Save image" })).toBeInTheDocument();
  });

  it("renders no image for a plain text message", () => {
    chatState.messages = [{ id: "txt-1", role: "assistant", content: "just text" }];

    render(<ChatView onOpenCoreFocus={vi.fn()} />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("ChatView camera", () => {
  let fakeStream;

  beforeEach(() => {
    appSettings = { voice_mode: "push_to_talk" };
    analyzeVisionImage.mockClear();
    fakeStream = { getTracks: () => [{ stop: vi.fn() }] };
    globalThis.jarvisDesktop = { requestCamera: vi.fn().mockResolvedValue(true) };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        enumerateDevices: vi.fn().mockResolvedValue([]),
        getUserMedia: vi.fn().mockResolvedValue(fakeStream),
      },
    });
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({ drawImage: vi.fn() }));
    HTMLCanvasElement.prototype.toDataURL = vi.fn(() => "data:image/jpeg;base64,QUJD");
  });

  afterEach(() => {
    cleanup();
    delete globalThis.jarvisDesktop;
  });

  it("requests the camera and attaches the stream to the mounted preview", async () => {
    render(<ChatView onOpenCoreFocus={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Camera" }));

    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith(
      expect.objectContaining({ video: expect.anything() }),
    );
    expect(screen.getByRole("button", { name: "Camera On" })).toBeInTheDocument();
    const preview = screen.getByLabelText("Camera preview");
    const video = preview.querySelector("video");
    expect(video).toBeTruthy();
    await waitFor(() => expect(video.srcObject).toBe(fakeStream));
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });

  it("captures a frame and routes the vision result into the conversation", async () => {
    render(<ChatView onOpenCoreFocus={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Camera" }));
    await waitFor(() => screen.getByRole("button", { name: "Camera On" }));

    fireEvent.click(screen.getByRole("button", { name: "Look" }));

    await waitFor(() => expect(analyzeVisionImage).toHaveBeenCalled());
    expect(analyzeVisionImage).toHaveBeenCalledWith(
      expect.objectContaining({ imageBase64: "QUJD", imageSuffix: ".jpg" }),
    );
  });
});
