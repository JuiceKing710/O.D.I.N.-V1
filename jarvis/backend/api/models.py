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
    theme: str = "system"
    permissions: dict[str, str] = Field(default_factory=dict)


class SettingsUpdateRequest(BaseModel):
    voice_mode: str | None = None
    model_name: str | None = None
    theme: str | None = None
    permissions: dict[str, str] | None = None


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


class EventResponse(BaseModel):
    id: str
    type: str
    payload: dict[str, Any]
    created_at: str


class IntegrityResponse(BaseModel):
    ok: bool
    sqlite_ok: bool
    vector_ok: bool
    details: dict[str, Any] = Field(default_factory=dict)


class BackupResponse(BaseModel):
    path: str
    created_at: datetime
    encrypted: bool
