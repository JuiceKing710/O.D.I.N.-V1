const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep the status-only message when the server does not return JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

export function sendChatMessage({ message, username = "local-user", conversationId = null }) {
  return request("/api/v1/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      username,
      conversation_id: conversationId,
    }),
  });
}

export function fetchSettings() {
  return request("/api/v1/settings");
}

export function fetchModels() {
  return request("/api/v1/models");
}

export function fetchTasks(username = "local-user") {
  return request(`/api/v1/tasks?username=${encodeURIComponent(username)}`);
}

export function loadModel(modelName) {
  return request("/api/v1/models/load", {
    method: "POST",
    body: JSON.stringify({ model_name: modelName }),
  });
}

export function connectEvents(onEvent) {
  const url = new URL(API_BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/api/v1/events";
  const socket = new WebSocket(url);
  socket.addEventListener("message", (event) => {
    onEvent(JSON.parse(event.data));
  });
  return () => socket.close();
}
