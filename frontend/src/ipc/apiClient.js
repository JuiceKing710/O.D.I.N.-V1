// Dev runs the UI on Vite (5173/4173) with the backend on a separate port, so
// fall back to 127.0.0.1:8000 there. When the backend serves the built UI
// itself (e.g. over Tailscale on the phone) the API is same-origin.
const DEV_PORTS = new Set(["5173", "4173"]);

function defaultApiBaseUrl() {
  if (globalThis.jarvisDesktop?.apiBaseUrl) {
    return globalThis.jarvisDesktop.apiBaseUrl;
  }
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL;
  }
  const origin = globalThis.location?.origin;
  if (origin?.startsWith("http") && !DEV_PORTS.has(globalThis.location.port)) {
    return origin;
  }
  return "http://127.0.0.1:8000";
}

const API_BASE_URL = defaultApiBaseUrl();
const TOKEN_STORAGE_KEY = "odin_token";

// Media that the browser loads itself — <img src>, <audio src>, and direct
// fetches for download — can't attach the Authorization header. When remote
// auth is on, the token therefore rides in the query string, the same escape
// hatch the WebSocket uses (see connectEvents). With auth off there is no token
// and this is a plain base-URL join.
export function resolveMediaUrl(path) {
  const url = new URL(path, API_BASE_URL);
  const token = getAuthToken();
  if (token) {
    url.searchParams.set("token", token);
  }
  return url.toString();
}

export function getAuthToken() {
  if (globalThis.jarvisDesktop?.apiToken) {
    return globalThis.jarvisDesktop.apiToken;
  }
  try {
    return globalThis.localStorage?.getItem(TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function setAuthToken(token) {
  try {
    globalThis.localStorage?.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // localStorage may be unavailable (private mode); the token is then per-call only.
  }
}

export function clearAuthToken() {
  try {
    globalThis.localStorage?.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // Nothing to clear if storage is unavailable.
  }
}

function authHeaders() {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
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
    const error = new Error(
      typeof detail === "string" ? detail : detail?.message || `Request failed: ${response.status}`,
    );
    error.status = response.status;
    error.detail = detail;
    throw error;
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

export function fetchSystemOverview() {
  return request("/api/v1/system/overview");
}

export function fetchVoiceStatus() {
  return request("/api/v1/voice/status");
}

export function setupVoiceModel() {
  return request("/api/v1/voice/setup", { method: "POST" });
}

export function fetchVoiceModels() {
  return request("/api/v1/voice/models");
}

export function loadVoiceModel(modelName) {
  return request("/api/v1/voice/models/load", {
    method: "POST",
    body: JSON.stringify({ model_name: modelName }),
  });
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

export function fetchVisionStatus() {
  return request("/api/v1/vision/status");
}

export function analyzeScreen(prompt = null) {
  return request("/api/v1/vision/screen", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export function analyzeVisionImage({ imageBase64, imageSuffix = ".jpg", prompt = null }) {
  return request("/api/v1/vision/analyze", {
    method: "POST",
    body: JSON.stringify({
      image_base64: imageBase64,
      image_suffix: imageSuffix,
      prompt,
    }),
  });
}

export function fetchImageStatus() {
  return request("/api/v1/image/status");
}

export function generateImage({ prompt, sender = "local-user" }) {
  return request("/api/v1/image/generate", {
    method: "POST",
    body: JSON.stringify({ prompt, sender }),
  });
}

export function fetchSecurityStatus() {
  return request("/api/v1/security/status");
}

export function fetchSecurityAlerts(limit = 25) {
  return request(`/api/v1/security/alerts?limit=${encodeURIComponent(limit)}`);
}

export function runSecurityScan() {
  return request("/api/v1/security/scan", { method: "POST" });
}

// Fire-and-poll: starts an unattended deep-research run and resolves
// immediately with the run snapshot (run_id, status "running"). Progress
// arrives via agent.* WebSocket events; the final report is read by polling
// fetchResearchRun(run_id) until status is "complete" or "error".
export function runResearchAgent({ goal, username = "local-user" }) {
  return request("/api/v1/agent/research", {
    method: "POST",
    body: JSON.stringify({ goal, username }),
  });
}

export function fetchResearchRun(runId) {
  return request(`/api/v1/agent/research/${encodeURIComponent(runId)}`);
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

export function fetchSkills() {
  return request("/api/v1/skills");
}

export function reloadSkills() {
  return request("/api/v1/skills/reload", { method: "POST" });
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

export function fetchMemoryBlocks() {
  return request("/api/v1/memory/blocks");
}

export function updateMemoryBlock(label, content) {
  return request(`/api/v1/memory/blocks/${encodeURIComponent(label)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
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
  // Browsers can't set headers on a WebSocket, so the token rides in the query.
  const token = getAuthToken();
  if (token) {
    url.searchParams.set("token", token);
  }
  let socket = null;
  let closed = false;
  let retryDelay = 1000;
  let retryTimer = null;

  function open() {
    if (closed) {
      return;
    }
    socket = new WebSocket(url);
    socket.addEventListener("message", (event) => {
      onEvent(JSON.parse(event.data));
    });
    socket.addEventListener("open", () => {
      retryDelay = 1000;
    });
    socket.addEventListener("close", () => {
      if (!closed) {
        retryTimer = setTimeout(open, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      }
    });
  }

  open();
  return () => {
    closed = true;
    clearTimeout(retryTimer);
    socket?.close();
  };
}
