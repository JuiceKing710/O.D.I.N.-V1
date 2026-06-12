import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatDock } from "./ChatDock.jsx";
import { AppStateProvider } from "../state/appContext.jsx";
import { useChatStore } from "../state/chatStore.js";

vi.mock("../ipc/apiClient.js", async (importOriginal) => {
  const original = await importOriginal();
  return {
    ...original,
    fetchSettings: vi.fn().mockResolvedValue({ voice_mode: "disabled", permissions: {} }),
    fetchVoiceStatus: vi.fn().mockResolvedValue({ tts_configured: false }),
    sendChatMessage: vi
      .fn()
      .mockResolvedValue({ conversation_id: 3, reply: "I am Odin." }),
  };
});

describe("ChatDock", () => {
  it("opens from its button and shows the conversation with streaming", async () => {
    useChatStore.setState({
      messages: [{ id: "m1", role: "user", content: "who are you?" }],
      streaming: { conversationId: 3, text: "I am O", active: true },
      voiceState: "idle",
    });

    render(
      <AppStateProvider>
        <ChatDock />
      </AppStateProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /speak with odin/i }));

    expect(await screen.findByText("who are you?")).toBeInTheDocument();
    expect(screen.getByText("I am O")).toBeInTheDocument();
    expect(screen.getByLabelText("Message Odin")).toBeInTheDocument();
  });
});
