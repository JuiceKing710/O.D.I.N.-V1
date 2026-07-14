from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    username: str = Field(default="local-user", min_length=1)
    conversation_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    bot: str | None = None
    created_at: datetime
    image_url: str | None = None


class MemoryQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    username: str = Field(default="local-user", min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class MemoryItem(BaseModel):
    msg_id: int
    convo_id: int
    role: str
    content: str
    created_at: datetime


class MemoryQueryResponse(BaseModel):
    results: list[MemoryItem]


class MemoryStatusResponse(BaseModel):
    vector: dict[str, Any]


class DocumentResponse(BaseModel):
    document_id: str
    user_id: int
    source: str
    content: str
    created_at: datetime


class DeleteResponse(BaseModel):
    deleted: bool
    id: str


class ConversationExportResponse(BaseModel):
    conversation: ConversationSummaryResponse
    messages: list[ConversationMessageResponse]


class StartupHealthResponse(BaseModel):
    ready: bool
    services: dict[str, dict[str, Any]]


class SystemOverviewResponse(BaseModel):
    metrics: dict[str, Any]
    nodes: dict[str, dict[str, Any]]


class SafetyStatusResponse(BaseModel):
    engaged: bool
    since: str | None = None
    reason: str | None = None
    blocked_bots: list[str] = Field(default_factory=list)


class EmergencyStopRequest(BaseModel):
    reason: str | None = None


class IdentityResponse(BaseModel):
    traits: list[str] = Field(default_factory=list)
    narrative: str = ""
    mood: str = ""
    interests: list[str] = Field(default_factory=list)


class IdentityUpdateRequest(BaseModel):
    traits: list[str] | None = None
    narrative: str | None = None
    mood: str | None = None
    interests: list[str] | None = None


class HeartbeatStatusResponse(BaseModel):
    enabled: bool
    running: bool
    interval_seconds: float
    tick_count: int
    last_tick_at: str | None = None
    last_error: str | None = None
    halted: bool = False


class GoalResponse(BaseModel):
    goal_id: int
    user_id: int
    text: str
    status: str
    created_at: datetime


class GoalCreateRequest(BaseModel):
    text: str
    username: str = "local-user"


class GoalUpdateRequest(BaseModel):
    username: str = "local-user"
    text: str | None = None
    status: str | None = None


class ProposalResponse(BaseModel):
    proposal_id: int
    kind: str
    target: str
    current_value: str | None = None
    proposed_value: str
    rationale: str | None = None
    status: str
    created_at: datetime
    decided_at: datetime | None = None


class ProposalCreateRequest(BaseModel):
    kind: str
    target: str
    proposed_value: str | None = None
    rationale: str | None = None


class MemoryBlocksResponse(BaseModel):
    blocks: dict[str, str]


class MemoryBlockUpdateRequest(BaseModel):
    content: str = ""


class ConversationSummaryResponse(BaseModel):
    convo_id: int
    user_id: int
    started_at: datetime
    title: str | None
    message_count: int
    last_activity_at: datetime


class ConversationMessageResponse(BaseModel):
    msg_id: int
    convo_id: int
    role: str
    content: str
    created_at: datetime


class BotExecRequest(BaseModel):
    action: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    sender: str = Field(default="user", min_length=1)


class BotExecResponse(BaseModel):
    bot: str
    action: str
    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class TaskCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    username: str = Field(default="local-user", min_length=1)


class TaskUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: Literal["pending", "in_progress", "complete"] | None = None
    username: str = Field(default="local-user", min_length=1)


class TaskResponse(BaseModel):
    task_id: int
    user_id: int
    name: str
    description: str | None
    status: Literal["pending", "in_progress", "complete"]
    created_at: datetime


class SettingsResponse(BaseModel):
    voice_mode: str = "push_to_talk"
    model_name: str = "local-default"
    active_model: str = ""
    theme: str = "system"
    permissions: dict[str, str] = Field(default_factory=dict)
    turbo_mode: bool = False
    gemini_api_key_set: bool = False
    openrouter_api_key_set: bool = False
    nvidia_api_key_set: bool = False
    wake_word: bool = False
    truthfulness_check: bool = False
    skills_enabled: bool = True
    whisper_model: str = ""


class SettingsUpdateRequest(BaseModel):
    voice_mode: Literal["push_to_talk", "always_listening", "disabled"] | None = None
    model_name: str | None = None
    active_model: str | None = None
    theme: Literal["system", "dark", "light"] | None = None
    permissions: dict[str, Literal["allowed", "denied", "prompt"]] | None = None
    turbo_mode: bool | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    nvidia_api_key: str | None = None
    wake_word: bool | None = None
    truthfulness_check: bool | None = None
    skills_enabled: bool | None = None


class PermissionRequestResponse(BaseModel):
    request_id: str
    permission: str
    actor: str
    reason: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class PermissionResolveRequest(BaseModel):
    decision: Literal["allowed", "denied"]


class PermissionResolveResponse(BaseModel):
    request: PermissionRequestResponse
    decision: Literal["allowed", "denied"]
    result: BotExecResponse | None = None


class ModelInfo(BaseModel):
    id: str
    provider: str
    loaded: bool = False


class ProviderStatusResponse(BaseModel):
    provider: str
    base_url: str | None = None
    available: bool
    selected_model: str | None = None
    error: str | None = None


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    provider: ProviderStatusResponse | None = None


class ModelLoadRequest(BaseModel):
    model_name: str = Field(min_length=1)


class SkillInfoResponse(BaseModel):
    name: str
    description: str
    path: str


class SkillsResponse(BaseModel):
    skills: list[SkillInfoResponse]
    enabled: bool = True


class EventResponse(BaseModel):
    id: str
    type: str
    payload: dict[str, Any]
    created_at: str


class VoiceStateRequest(BaseModel):
    state: Literal["idle", "listening", "thinking", "speaking"]


class VoiceStatusResponse(BaseModel):
    state: Literal["idle", "listening", "thinking", "speaking"]
    stt_adapter: str
    stt_configured: bool
    tts_adapter: str
    tts_configured: bool
    stt_detail: str | None = None


class VoiceTranscribeRequest(BaseModel):
    audio_path: str | None = None
    audio_base64: str | None = Field(default=None, max_length=20_000_000)
    audio_suffix: str = ".webm"


class VoiceTranscribeResponse(BaseModel):
    transcript: str
    state: Literal["idle", "listening", "thinking", "speaking"]


class VoiceSetupResponse(BaseModel):
    configured: bool
    model_path: str


class VoiceModelInfo(BaseModel):
    name: str
    size_bytes: int
    active: bool


class VoiceModelsResponse(BaseModel):
    models: list[VoiceModelInfo]
    active: str | None = None
    gpu_enabled: bool | None = None


class VoiceSynthesizeRequest(BaseModel):
    text: str = Field(min_length=1)
    voice_name: str | None = None


class VoiceSynthesizeResponse(BaseModel):
    audio_path: str
    audio_url: str
    state: Literal["idle", "listening", "thinking", "speaking"]


class VisionStatusResponse(BaseModel):
    state: Literal["idle", "analyzing"]
    adapter: str
    configured: bool


class VisionAnalyzeRequest(BaseModel):
    image_path: str | None = None
    image_base64: str | None = Field(default=None, max_length=30_000_000)
    image_suffix: str = ".jpg"
    prompt: str | None = None


class VisionScreenRequest(BaseModel):
    prompt: str | None = None


class VisionAnalyzeResponse(BaseModel):
    description: str
    state: Literal["idle", "analyzing"]


class ImageStatusResponse(BaseModel):
    state: Literal["idle", "generating"]
    adapter: str
    configured: bool
    network: bool


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    sender: str = Field(default="user", min_length=1)


class ImageGenerateResponse(BaseModel):
    image_url: str
    prompt: str
    state: Literal["idle", "generating"]


class ResearchAgentRequest(BaseModel):
    goal: str = Field(min_length=1)
    username: str = Field(default="local-user", min_length=1)


class ResearchAgentSource(BaseModel):
    title: str
    url: str


class ResearchAgentStep(BaseModel):
    kind: str
    label: str
    status: str
    detail: str = ""


class ResearchRunResponse(BaseModel):
    run_id: str
    goal: str
    status: Literal["running", "complete", "error"]
    task_id: int | None = None
    queries: list[str] = Field(default_factory=list)
    steps: list[ResearchAgentStep] = Field(default_factory=list)
    report: str = ""
    sources: list[ResearchAgentSource] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str


class IntegrityResponse(BaseModel):
    ok: bool
    sqlite_ok: bool
    vector_ok: bool
    details: dict[str, Any] = Field(default_factory=dict)


class BackupResponse(BaseModel):
    filename: str
    path: str
    created_at: datetime
    encrypted: bool


class RestoreRequest(BaseModel):
    filename: str = Field(min_length=1)


class RestoreResponse(BaseModel):
    path: str
    restored_from: str
    safety_backup: str | None
    created_at: datetime
    encrypted: bool


class BackupScheduleResponse(BaseModel):
    enabled: bool
    hour: int
    retention: int
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_backup: str | None
    last_error: str | None


class ReflectionRequest(BaseModel):
    username: str = Field(default="local-user", min_length=1)


class ReflectionResponse(BaseModel):
    reflection_id: int
    convo_id: int
    summary: str
    topics: str | None = None
    sentiment: str | None = None
    created_at: datetime
