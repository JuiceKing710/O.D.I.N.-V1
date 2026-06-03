from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from jarvis.backend.api.models import (
    BotExecRequest,
    BotExecResponse,
    ChatRequest,
    ChatResponse,
    MemoryItem,
    MemoryQueryRequest,
    MemoryQueryResponse,
    ModelsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    TaskCreateRequest,
    TaskResponse,
)
from jarvis.backend.core.app_factory import get_core, get_settings_store
from jarvis.backend.core.bot_manager import BotMessage
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.settings_store import SettingsStore

router = APIRouter(prefix="/api/v1")


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, core: JarvisCore = Depends(get_core)) -> ChatResponse:
    result = await core.handle_message(
        message=request.message,
        username=request.username,
        conversation_id=request.conversation_id,
        metadata=request.metadata,
    )
    return ChatResponse(**result)


@router.post("/memory/query", response_model=MemoryQueryResponse)
def query_memory(
    request: MemoryQueryRequest, core: JarvisCore = Depends(get_core)
) -> MemoryQueryResponse:
    user = core.memory.get_or_create_user(request.username)
    rows = core.memory.query_messages(user.user_id, request.query, request.limit)
    return MemoryQueryResponse(results=[MemoryItem(**row.to_api()) for row in rows])


@router.post("/bot/{bot_name}/exec", response_model=BotExecResponse)
async def execute_bot(
    bot_name: str, request: BotExecRequest, core: JarvisCore = Depends(get_core)
) -> BotExecResponse:
    message = BotMessage(
        sender=request.sender,
        recipient=bot_name,
        action=request.action,
        payload=request.payload,
    )
    response = await core.bot_manager.dispatch(message)
    if response is None:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_name}")
    return BotExecResponse(
        bot=bot_name,
        action=request.action,
        ok=response.ok,
        payload=response.payload,
        error=response.error,
    )


@router.get("/tasks", response_model=list[TaskResponse])
def list_tasks(username: str = "local-user", core: JarvisCore = Depends(get_core)) -> list[TaskResponse]:
    user = core.memory.get_or_create_user(username)
    return [TaskResponse(**task.to_api()) for task in core.memory.list_tasks(user.user_id)]


@router.post("/tasks", response_model=TaskResponse)
def create_task(
    request: TaskCreateRequest, core: JarvisCore = Depends(get_core)
) -> TaskResponse:
    user = core.memory.get_or_create_user(request.username)
    task = core.memory.create_task(user.user_id, request.name, request.description)
    return TaskResponse(**task.to_api())


@router.get("/settings", response_model=SettingsResponse)
def get_settings(settings: SettingsStore = Depends(get_settings_store)) -> SettingsResponse:
    return SettingsResponse(**settings.read())


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    request: SettingsUpdateRequest, settings: SettingsStore = Depends(get_settings_store)
) -> SettingsResponse:
    return SettingsResponse(**settings.update(request.model_dump(exclude_none=True)))


@router.get("/models", response_model=ModelsResponse)
async def list_models(core: JarvisCore = Depends(get_core)) -> ModelsResponse:
    models = await core.lm_provider.list_models()
    return ModelsResponse(models=[asdict(model) for model in models])
