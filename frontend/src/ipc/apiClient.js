const API_BASE_URL =
  globalThis.jarvisDesktop?.apiBaseUrl ||
  import.meta.env.VITE_API_BASE_URL ||
  "http://127.0.0.1:8000";

export function resolveApiUrl(path) {
  return new URL(path, API_BASE_URL).toString();
}

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

export function fetchStartupHealth() {
  return request("/api/v1/health/startup");
}

export function fetchVoiceStatus() {
  return request("/api/v1/voice/status");
}

export function transcribeVoiceAudio({ audioBase64, audioSuffix = ".webm" }) {
  return request("/api/v1/voice/transcribe", {
    method: "POST",
    body: JSON.stringify({
      audio_base64: audioBase64,
      audio_suffix: audioSuffix,
    }),
  });
}

export function synthesizeVoice({ text, voiceName = null }) {
  return request("/api/v1/voice/synthesize", {
    method: "POST",
    body: JSON.stringify({
      text,
      voice_name: voiceName,
    }),
  });
}

export function updateSettings(patch) {
  return request("/api/v1/settings", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

export function fetchModels() {
  return request("/api/v1/models");
}

export function checkRecoveryIntegrity() {
  return request("/api/v1/recovery/integrity");
}

export function fetchMemoryStatus() {
  return request("/api/v1/memory/status");
}

export function createRecoveryBackup() {
  return request("/api/v1/recovery/backups", {
    method: "POST",
  });
}

export function fetchRecoveryBackups() {
  return request("/api/v1/recovery/backups");
}

export function fetchBackupSchedule() {
  return request("/api/v1/recovery/schedule");
}

export function restoreRecoveryBackup(filename) {
  return request("/api/v1/recovery/restore", {
    method: "POST",
    body: JSON.stringify({ filename }),
  });
}

export function fetchPermissionRequests() {
  return request("/api/v1/permissions/requests");
}

export function resolvePermissionRequest(requestId, decision) {
  return request(`/api/v1/permissions/requests/${requestId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}

export function fetchConversations(username = "local-user") {
  return request(`/api/v1/conversations?username=${encodeURIComponent(username)}`);
}

export function fetchConversationMessages(conversationId, username = "local-user") {
  return request(
    `/api/v1/conversations/${conversationId}/messages?username=${encodeURIComponent(username)}`,
  );
}

export function exportConversation(conversationId, username = "local-user") {
  return request(
    `/api/v1/conversations/${conversationId}/export?username=${encodeURIComponent(username)}`,
  );
}

export function deleteConversation(conversationId, username = "local-user") {
  return request(
    `/api/v1/conversations/${conversationId}?username=${encodeURIComponent(username)}`,
    { method: "DELETE" },
  );
}

export function fetchMemoryDocuments(username = "local-user") {
  return request(`/api/v1/memory/documents?username=${encodeURIComponent(username)}`);
}

export function deleteMemoryDocument(documentId, username = "local-user") {
  return request(
    `/api/v1/memory/documents/${encodeURIComponent(documentId)}?username=${encodeURIComponent(username)}`,
    { method: "DELETE" },
  );
}

export function fetchAuditEvents(limit = 100) {
  return request(`/api/v1/audit/events?limit=${limit}`);
}

export function fetchReflections(conversationId, username = "local-user") {
  return request(
    `/api/v1/conversations/${conversationId}/reflections?username=${encodeURIComponent(username)}`,
  );
}

export function createReflection(conversationId, username = "local-user") {
  return request(`/api/v1/conversations/${conversationId}/reflections`, {
    method: "POST",
    body: JSON.stringify({ username }),
  });
}

export function fetchTasks(username = "local-user") {
  return request(`/api/v1/tasks?username=${encodeURIComponent(username)}`);
}

export function createTask({ name, description = "", username = "local-user" }) {
  return request("/api/v1/tasks", {
    method: "POST",
    body: JSON.stringify({
      description: description.trim() || null,
      name,
      username,
    }),
  });
}

export function updateTask({ taskId, name, description, status, username = "local-user" }) {
  return request(`/api/v1/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify({
      description,
      name,
      status,
      username,
    }),
  });
}

export function deleteTask(taskId, username = "local-user") {
  return request(`/api/v1/tasks/${taskId}?username=${encodeURIComponent(username)}`, {
    method: "DELETE",
  });
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
