import { beforeEach, describe, expect, it } from "vitest";
import { useChatStore } from "./chatStore.js";

describe("chatStore chat.message", () => {
  beforeEach(() => {
    useChatStore.setState({ messages: [], streaming: null });
  });

  it("carries a generated image_url onto the applied message", () => {
    useChatStore.getState().applyEvent({
      id: "evt-1",
      type: "chat.message",
      payload: {
        conversation_id: 3,
        role: "assistant",
        content: "Here's an AI-generated image of: a fox",
        image_url: "/api/v1/image/file/fox.png",
      },
    });

    const [message] = useChatStore.getState().messages;
    expect(message.imageUrl).toBe("/api/v1/image/file/fox.png");
  });

  it("leaves imageUrl null for a plain text message", () => {
    useChatStore.getState().applyEvent({
      id: "evt-2",
      type: "chat.message",
      payload: { conversation_id: 3, role: "assistant", content: "just text" },
    });

    expect(useChatStore.getState().messages[0].imageUrl).toBeNull();
  });
});
