import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CoreFocusView } from "./CoreFocusView.jsx";
import { AppStateProvider } from "../state/appContext.jsx";
import { useChatStore } from "../state/chatStore.js";

vi.mock("../ipc/apiClient.js", async (importOriginal) => {
  const original = await importOriginal();
  return {
    ...original,
    fetchSettings: vi.fn().mockResolvedValue({ voice_mode: "disabled", permissions: {} }),
    fetchVoiceStatus: vi.fn().mockResolvedValue({ tts_configured: false }),
  };
});

describe("CoreFocusView", () => {
  it("shows the compass state, exit control, and chat toggle", () => {
    useChatStore.setState({ messages: [], streaming: null, voiceState: "idle" });

    render(
      <AppStateProvider>
        <CoreFocusView messages={[]} onExit={() => {}} state="idle" />
      </AppStateProvider>,
    );

    expect(screen.getByRole("button", { name: "Exit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /speak with odin/i })).toBeInTheDocument();
    expect(screen.getByLabelText("O.D.I.N. is idle")).toBeInTheDocument();
  });
});
