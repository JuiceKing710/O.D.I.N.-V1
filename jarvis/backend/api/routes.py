from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from jarvis.backend.api.models import (
    BackupResponse,
    BotExecRequest,
    BotExecResponse,
    ChatRequest,
    ChatResponse,
    ConversationMessageResponse,
    ConversationSummaryResponse,
    EventResponse,
    IntegrityResponse,
    MemoryItem,
    MemoryQueryRequest,
    MemoryQueryResponse,
    ModelLoadRequest,
    ModelsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
)
from jarvis.backend.core.app_factory import (
    get_core,
    get_event_bus,
    get_recovery_manager,
    get_settings_store,
)
from jarvis.backend.core.bot_manager import BotMessage
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.recovery_manager import RecoveryManager
from jarvis.backend.core.settings_store import SettingsStore

router = APIRouter(prefix="/api/v1")


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, core: JarvisCore = Depends(get_core)) -> ChatResponse:
    try:
        result = await core.handle_message(
            message=request.message,
            username=request.username,
            conversation_id=request.conversation_id,
            metadata=request.metadata,
        )
    except ValueError as exc:
        status_code = 404 if "Conversation not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Language model provider unavailable: {exc}",
        ) from exc
    return ChatResponse(**result)


@router.post("/memory/query", response_model=MemoryQueryResponse)
def query_memory(
    request: MemoryQueryRequest, core: JarvisCore = Depends(get_core)
) -> MemoryQueryResponse:
    user = core.memory.get_or_create_user(request.username)
    rows = core.memory.query_messages(user.user_id, request.query, request.limit)
    return MemoryQueryResponse(results=[MemoryItem(**row.to_api()) for row in rows])


@router.get("/conversations", response_model=list[ConversationSummaryResponse])
def list_conversations(
    username: str = "local-user",
    limit: int = 25,
    core: JarvisCore = Depends(get_core),
) -> list[ConversationSummaryResponse]:
    user = core.memory.get_or_create_user(username)
    conversations = core.memory.list_conversations(user.user_id, limit)
    return [ConversationSummaryResponse(**conversation.to_api()) for conversation in conversations]


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ConversationMessageResponse],
)
def list_conversation_messages(
    conversation_id: int,
    username: str = "local-user",
    core: JarvisCore = Depends(get_core),
) -> list[ConversationMessageResponse]:
    user = core.memory.get_or_create_user(username)
    try:
        core.memory.get_conversation(conversation_id, user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rows = core.memory.list_conversation_messages(conversation_id)
    return [ConversationMessageResponse(**row.to_api()) for row in rows]


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
    request: TaskCreateRequest,
    core: JarvisCore = Depends(get_core),
    event_bus: EventBus = Depends(get_event_bus),
) -> TaskResponse:
    user = core.memory.get_or_create_user(request.username)
    task = core.memory.create_task(user.user_id, request.name, request.description)
    event_bus.publish("task.updated", {"task": task.to_api(), "action": "created"})
    return TaskResponse(**task.to_api())


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    request: TaskUpdateRequest,
    core: JarvisCore = Depends(get_core),
    event_bus: EventBus = Depends(get_event_bus),
) -> TaskResponse:
    user = core.memory.get_or_create_user(request.username)
    try:
        task = core.memory.update_task(
            user.user_id,
            task_id,
            description=request.description,
            name=request.name,
            status=request.status,
        )
    except ValueError as exc:
        status_code = 404 if "Task not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    event_bus.publish("task.updated", {"task": task.to_api(), "action": "updated"})
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
    status = await core.lm_provider.status()
    return ModelsResponse(
        models=[asdict(model) for model in models],
        provider=asdict(status),
    )


@router.post("/models/load", response_model=ModelsResponse)
async def load_model(
    request: ModelLoadRequest, core: JarvisCore = Depends(get_core)
) -> ModelsResponse:
    try:
        await core.lm_provider.load_model(request.model_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    models = await core.lm_provider.list_models()
    status = await core.lm_provider.status()
    return ModelsResponse(
        models=[asdict(model) for model in models],
        provider=asdict(status),
    )


@router.get("/events/history", response_model=list[EventResponse])
def event_history(event_bus: EventBus = Depends(get_event_bus)) -> list[EventResponse]:
    return [EventResponse(**event.to_api()) for event in event_bus.history()]


@router.websocket("/events")
async def events_socket(websocket: WebSocket, event_bus: EventBus = Depends(get_event_bus)) -> None:
    await websocket.accept()
    for event in event_bus.history():
        await websocket.send_json(event.to_api())
    queue = await event_bus.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event.to_api())
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)


@router.get("/recovery/integrity", response_model=IntegrityResponse)
def recovery_integrity(
    recovery_manager: RecoveryManager = Depends(get_recovery_manager),
) -> IntegrityResponse:
    report = recovery_manager.check_integrity()
    return IntegrityResponse(
        ok=report.ok,
        sqlite_ok=report.sqlite_ok,
        vector_ok=report.vector_ok,
        details=report.details,
    )


@router.post("/recovery/backups", response_model=BackupResponse)
def create_backup(
    recovery_manager: RecoveryManager = Depends(get_recovery_manager),
) -> BackupResponse:
    try:
        snapshot = recovery_manager.create_sqlite_backup()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BackupResponse(
        path=str(snapshot.path),
        created_at=snapshot.created_at,
        encrypted=snapshot.encrypted,
    )
