import { create } from "zustand";

export const useChatStore = create((set) => ({
  messages: [],
  tasks: [],
  voiceState: "idle",
  addMessage: (message) =>
    set((state) => ({
      messages: state.messages.some(
        (current) => current.role === message.role && current.content === message.content,
      )
        ? state.messages
        : [
            ...state.messages,
            {
              id: message.id || crypto.randomUUID(),
              ...message,
            },
          ],
    })),
  setVoiceState: (voiceState) => set({ voiceState }),
  setTasks: (tasks) => set({ tasks }),
  applyEvent: (event) =>
    set((state) => {
      if (event.type === "voice.state") {
        return { voiceState: event.payload.state || "idle" };
      }
      if (event.type === "task.updated") {
        const task = event.payload.task;
        const tasks = state.tasks.some((current) => current.task_id === task.task_id)
          ? state.tasks.map((current) => (current.task_id === task.task_id ? task : current))
          : [task, ...state.tasks];
        return { tasks };
      }
      if (event.type === "chat.message") {
        const message = {
          id: event.id,
          role: event.payload.role,
          content: event.payload.content,
          conversationId: event.payload.conversation_id,
        };
        if (
          state.messages.some(
            (current) => current.role === message.role && current.content === message.content,
          )
        ) {
          return {};
        }
        return { messages: [...state.messages, message] };
      }
      return {};
    }),
}));
