import { create } from "zustand";

export const useChatStore = create((set) => ({
  messages: [],
  voiceState: "idle",
  addMessage: (message) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: crypto.randomUUID(),
          ...message,
        },
      ],
    })),
  setVoiceState: (voiceState) => set({ voiceState }),
}));

