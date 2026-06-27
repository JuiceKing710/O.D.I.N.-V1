from __future__ import annotations

import asyncio
import base64
import binascii
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from jarvis.backend.api.models import (
    BackupResponse,
    BackupScheduleResponse,
    BotExecRequest,
    BotExecResponse,
    ChatRequest,
    ChatResponse,
    ConversationMessageResponse,
    ConversationExportResponse,
    ConversationSummaryResponse,
    DeleteResponse,
    DocumentResponse,
    EmergencyStopRequest,
    EventResponse,
    IdentityResponse,
    IdentityUpdateRequest,
    ImageGenerateRequest,
    ImageGenerateResponse,
    ImageStatusResponse,
    IntegrityResponse,
    MemoryBlocksResponse,
    MemoryBlockUpdateRequest,
    MemoryItem,
    MemoryQueryRequest,
    MemoryQueryResponse,
    MemoryStatusResponse,
    ModelLoadRequest,
    ModelsResponse,
    PermissionRequestResponse,
    PermissionResolveRequest,
    PermissionResolveResponse,
    ResearchAgentRequest,
    ResearchRunResponse,
    SafetyStatusResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    StartupHealthResponse,
    SystemOverviewResponse,
    ReflectionRequest,
    ReflectionResponse,
    RestoreRequest,
    RestoreResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
    VisionAnalyzeRequest,
    VisionAnalyzeResponse,
    VisionStatusResponse,
    VoiceStateRequest,
    VoiceStatusResponse,
    VoiceSynthesizeRequest,
    VoiceSynthesizeResponse,
    VoiceSetupResponse,
    VoiceTranscribeRequest,
    VoiceTranscribeResponse,
)
from jarvis.backend.core.app_factory import (
    get_agent_manager,
    get_backup_scheduler,
    get_audit_logger,
    get_core,
    get_event_bus,
    get_identity_manager,
    get_image_manager,
    get_permission_manager,
    get_recovery_manager,
    get_memory_consolidator,
    get_safety_switch,
    get_settings_store,
    get_system_monitor,
    get_vision_manager,
    get_voice_manager,
    get_wake_word_listener,
)
from jarvis.backend.core.agent_manager import DeepResearchAgent
from jarvis.backend.core.memory_consolidator import MemoryConsolidator
from jarvis.backend.core.wake_word import WakeWordListener
from jarvis.backend.core.backup_scheduler import BackupScheduler
from jarvis.backend.core.bot_manager import BotMessage
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.image_manager import ImageManager
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.identity_manager import IdentityManager
from jarvis.backend.core.recovery_manager import RecoveryManager
from jarvis.backend.core.safety_switch import SafetySwitch
from jarvis.backend.core.settings_store import SettingsStore
from jarvis.backend.core.system_monitor import SystemMonitor
from jarvis.backend.core.vision_manager import VisionManager
from jarvis.backend.core.voice_manager import VoiceManager, VoiceState
from jarvis.backend.utils.reflection import ReflectionEngine
from jarvis.backend.utils.audit_logging import AuditLogger
from jarvis.backend.utils.permissions import PermissionDecision, PermissionManager

router = APIRouter(prefix="/api/v1")
WHISPER_MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
)


def _settings_response(
    settings: SettingsStore, permission_manager: PermissionManager
) -> SettingsResponse:
    data = settings.read()
    stored_permissions = data.get("permissions") or {}
    permission_manager.update_decisions(stored_permissions)
    data["permissions"] = permission_manager.as_settings()
    data["gemini_api_key_set"] = bool(str(data.get("gemini_api_key") or "").strip())
    data.pop("gemini_api_key", None)
    return SettingsResponse(**data)


@router.get("/health/startup", response_model=StartupHealthResponse)
async def startup_health(
    core: JarvisCore = Depends(get_core),
    voice_manager: VoiceManager = Depends(get_voice_manager),
    vision_manager: VisionManager = Depends(get_vision_manager),
    recovery_manager: RecoveryManager = Depends(get_recovery_manager),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
) -> StartupHealthResponse:
    provider = await core.lm_provider.status()
    voice = voice_manager.status()
    vision = vision_manager.status()
    recovery = recovery_manager.check_integrity()
    services = {
        "backend": {"ok": True, "detail": "API online"},
        "model": {
            "ok": provider.available,
            "detail": provider.selected_model or provider.error or provider.provider,
        },
        "voice": {
            "ok": voice.stt_configured and voice.tts_configured,
            "detail": {
                "stt_adapter": voice.stt_adapter,
                "stt_configured": voice.stt_configured,
                "tts_adapter": voice.tts_adapter,
                "tts_configured": voice.tts_configured,
            },
        },
        "vision": {
            "ok": vision.configured,
            "detail": {"adapter": vision.adapter, "configured": vision.configured},
        },
        "memory": {"ok": recovery.sqlite_ok, "detail": core.memory.vector_store.health()},
        "backups": {
            "ok": recovery.details.get("encryption") == "configured",
            "detail": scheduler.status().to_api(),
        },
    }
    return StartupHealthResponse(
        ready=services["backend"]["ok"] and services["memory"]["ok"],
        services=services,
    )


@router.get("/system/overview", response_model=SystemOverviewResponse)
async def system_overview(
    username: str = "local-user",
    core: JarvisCore = Depends(get_core),
    voice_manager: VoiceManager = Depends(get_voice_manager),
    vision_manager: VisionManager = Depends(get_vision_manager),
    monitor: SystemMonitor = Depends(get_system_monitor),
    permission_manager: PermissionManager = Depends(get_permission_manager),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
    safety: SafetySwitch = Depends(get_safety_switch),
) -> SystemOverviewResponse:
    provider = await core.lm_provider.status()
    voice = voice_manager.status()
    vision = vision_manager.status()
    user = core.memory.get_or_create_user(username)
    tasks = core.memory.list_tasks(user.user_id)
    documents = core.memory.list_documents(user.user_id)
    conversations = core.memory.list_conversations(user.user_id, limit=100)
    pending_approvals = permission_manager.pending_requests()
    halted = safety.is_engaged()
    nodes = {
        "reasoning_engine": {
            "ok": provider.available,
            "label": provider.selected_model or provider.error or provider.provider,
            "provider": provider.provider,
        },
        "memory_layer": {
            "ok": True,
            "label": f"{len(documents)} document(s)",
            "documents": len(documents),
            "conversations": len(conversations),
            "vector": core.memory.vector_store.health(),
        },
        "voice_interface": {
            "ok": voice.stt_configured and voice.tts_configured,
            "label": voice.state.value,
            "stt_adapter": voice.stt_adapter,
            "tts_adapter": voice.tts_adapter,
        },
        "vision_interface": {
            "ok": vision.configured,
            "label": vision.adapter if vision.configured else "offline",
            "adapter": vision.adapter,
            "configured": vision.configured,
        },
        "security_mesh": {
            "ok": not halted,
            "label": "HALTED — emergency stop"
            if halted
            else f"{len(pending_approvals)} pending approval(s)",
            "pending_approvals": len(pending_approvals),
            "emergency_stop": halted,
        },
        "automation_hub": {
            "ok": True,
            "label": f"{sum(1 for task in tasks if task.status != 'complete')} open task(s)",
            "tasks_open": sum(1 for task in tasks if task.status != "complete"),
            "tasks_total": len(tasks),
        },
        "recovery_core": {
            "ok": scheduler.status().last_error is None,
            "label": scheduler.status().last_backup
            or (f"daily @ {scheduler.hour:02d}:00" if scheduler.enabled else "disabled"),
        },
        "api_orchestrator": {
            "ok": True,
            "label": "connected",
        },
    }
    return SystemOverviewResponse(metrics=monitor.snapshot(), nodes=nodes)


@router.get("/system/safety", response_model=SafetyStatusResponse)
def safety_status(
    safety: SafetySwitch = Depends(get_safety_switch),
) -> SafetyStatusResponse:
    return SafetyStatusResponse(**safety.status())


@router.post("/system/emergency-stop", response_model=SafetyStatusResponse)
def emergency_stop(
    request: EmergencyStopRequest = EmergencyStopRequest(),
    safety: SafetySwitch = Depends(get_safety_switch),
) -> SafetyStatusResponse:
    # The body is optional so a bare POST (a panic button, a curl with no
    # payload) still halts Odin instead of 422-ing.
    return SafetyStatusResponse(**safety.engage(reason=request.reason))


@router.post("/system/resume", response_model=SafetyStatusResponse)
def resume_from_stop(
    safety: SafetySwitch = Depends(get_safety_switch),
) -> SafetyStatusResponse:
    return SafetyStatusResponse(**safety.release())


@router.get("/identity", response_model=IdentityResponse)
def get_identity(
    identity: IdentityManager = Depends(get_identity_manager),
) -> IdentityResponse:
    return IdentityResponse(**identity.get())


@router.put("/identity", response_model=IdentityResponse)
def update_identity(
    request: IdentityUpdateRequest,
    identity: IdentityManager = Depends(get_identity_manager),
) -> IdentityResponse:
    patch = request.model_dump(exclude_none=True)
    return IdentityResponse(**identity.update(patch))


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


@router.get("/memory/status", response_model=MemoryStatusResponse)
def memory_status(core: JarvisCore = Depends(get_core)) -> MemoryStatusResponse:
    return MemoryStatusResponse(vector=core.memory.vector_store.health())


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


@router.get(
    "/conversations/{conversation_id}/export",
    response_model=ConversationExportResponse,
)
def export_conversation(
    conversation_id: int,
    username: str = "local-user",
    core: JarvisCore = Depends(get_core),
) -> ConversationExportResponse:
    user = core.memory.get_or_create_user(username)
    core.memory.get_conversation(conversation_id, user.user_id)
    summary = next(
        item
        for item in core.memory.list_conversations(user.user_id, limit=1000)
        if item.convo_id == conversation_id
    )
    return ConversationExportResponse(
        conversation=ConversationSummaryResponse(**summary.to_api()),
        messages=[
            ConversationMessageResponse(**row.to_api())
            for row in core.memory.list_conversation_messages(conversation_id)
        ],
    )


@router.delete("/conversations/{conversation_id}", response_model=DeleteResponse)
def delete_conversation(
    conversation_id: int,
    username: str = "local-user",
    core: JarvisCore = Depends(get_core),
) -> DeleteResponse:
    user = core.memory.get_or_create_user(username)
    try:
        core.memory.delete_conversation(user.user_id, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeleteResponse(deleted=True, id=str(conversation_id))


@router.get("/memory/blocks", response_model=MemoryBlocksResponse)
def get_memory_blocks(core: JarvisCore = Depends(get_core)) -> MemoryBlocksResponse:
    return MemoryBlocksResponse(blocks=core.memory.get_memory_blocks())


@router.put("/memory/blocks/{label}", response_model=MemoryBlocksResponse)
def update_memory_block(
    label: str,
    request: MemoryBlockUpdateRequest,
    core: JarvisCore = Depends(get_core),
) -> MemoryBlocksResponse:
    try:
        blocks = core.memory.update_memory_block(label, request.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MemoryBlocksResponse(blocks=blocks)


@router.post("/memory/consolidate", response_model=dict)
async def consolidate_memory(
    username: str = "local-user",
    consolidator: MemoryConsolidator = Depends(get_memory_consolidator),
) -> dict:
    try:
        return await consolidator.consolidate(username)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/memory/documents", response_model=list[DocumentResponse])
def list_memory_documents(
    username: str = "local-user",
    core: JarvisCore = Depends(get_core),
) -> list[DocumentResponse]:
    user = core.memory.get_or_create_user(username)
    return [DocumentResponse(**document.to_api()) for document in core.memory.list_documents(user.user_id)]


@router.delete("/memory/documents/{document_id}", response_model=DeleteResponse)
def delete_memory_document(
    document_id: str,
    username: str = "local-user",
    core: JarvisCore = Depends(get_core),
) -> DeleteResponse:
    user = core.memory.get_or_create_user(username)
    try:
        core.memory.delete_document(user.user_id, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeleteResponse(deleted=True, id=document_id)


@router.get(
    "/conversations/{conversation_id}/reflections",
    response_model=list[ReflectionResponse],
)
def list_reflections(
    conversation_id: int,
    username: str = "local-user",
    core: JarvisCore = Depends(get_core),
) -> list[ReflectionResponse]:
    user = core.memory.get_or_create_user(username)
    try:
        core.memory.get_conversation(conversation_id, user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        ReflectionResponse(**reflection.to_api())
        for reflection in core.memory.list_reflection_summaries(conversation_id)
    ]


@router.post(
    "/conversations/{conversation_id}/reflections",
    response_model=ReflectionResponse,
)
async def create_reflection(
    conversation_id: int,
    request: ReflectionRequest,
    core: JarvisCore = Depends(get_core),
) -> ReflectionResponse:
    user = core.memory.get_or_create_user(request.username)
    try:
        await ReflectionEngine(core.memory, core.lm_provider).summarize_conversation(
            user.user_id,
            conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Reflection provider unavailable: {exc}") from exc
    record = core.memory.list_reflection_summaries(conversation_id)[0]
    return ReflectionResponse(**record.to_api())


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


@router.delete("/tasks/{task_id}", response_model=DeleteResponse)
def delete_task(
    task_id: int,
    username: str = "local-user",
    core: JarvisCore = Depends(get_core),
) -> DeleteResponse:
    user = core.memory.get_or_create_user(username)
    try:
        core.memory.delete_task(user.user_id, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeleteResponse(deleted=True, id=str(task_id))


@router.get("/settings", response_model=SettingsResponse)
def get_settings(
    settings: SettingsStore = Depends(get_settings_store),
    permission_manager: PermissionManager = Depends(get_permission_manager),
) -> SettingsResponse:
    try:
        return _settings_response(settings, permission_manager)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    request: SettingsUpdateRequest,
    settings: SettingsStore = Depends(get_settings_store),
    permission_manager: PermissionManager = Depends(get_permission_manager),
    wake_listener: WakeWordListener = Depends(get_wake_word_listener),
) -> SettingsResponse:
    patch = request.model_dump(exclude_none=True)
    try:
        if "permissions" in patch:
            permission_manager.update_decisions(patch["permissions"])
        settings.update(patch)
        if patch.get("wake_word") is True:
            wake_listener.start()
        elif patch.get("wake_word") is False:
            wake_listener.stop()
        return _settings_response(settings, permission_manager)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/permissions/requests", response_model=list[PermissionRequestResponse])
def list_permission_requests(
    permission_manager: PermissionManager = Depends(get_permission_manager),
) -> list[PermissionRequestResponse]:
    return [
        PermissionRequestResponse(**request.to_api())
        for request in permission_manager.pending_requests()
    ]


@router.post(
    "/permissions/requests/{request_id}/resolve",
    response_model=PermissionResolveResponse,
)
async def resolve_permission_request(
    request_id: str,
    request: PermissionResolveRequest,
    permission_manager: PermissionManager = Depends(get_permission_manager),
    event_bus: EventBus = Depends(get_event_bus),
    core: JarvisCore = Depends(get_core),
) -> PermissionResolveResponse:
    try:
        resolved = permission_manager.resolve_request(
            request_id,
            PermissionDecision(request.decision),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    response = PermissionRequestResponse(**resolved.to_api())
    result = None
    retry = resolved.metadata
    if request.decision == PermissionDecision.ALLOWED and retry.get("bot"):
        bot_response = await core.bot_manager.dispatch(
            BotMessage(
                sender=str(retry.get("sender") or resolved.actor),
                recipient=str(retry["bot"]),
                action=str(retry.get("action") or ""),
                payload=retry.get("payload") if isinstance(retry.get("payload"), dict) else {},
            )
        )
        if bot_response is not None:
            result = BotExecResponse(
                bot=str(retry["bot"]),
                action=str(retry.get("action") or ""),
                ok=bot_response.ok,
                payload=bot_response.payload,
                error=bot_response.error,
            )
    event_bus.publish(
        "permission.resolved",
        {
            "request": response.model_dump(mode="json"),
            "decision": request.decision,
            "result": result.model_dump(mode="json") if result else None,
        },
    )
    return PermissionResolveResponse(
        request=response,
        decision=request.decision,
        result=result,
    )


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
    request: ModelLoadRequest,
    core: JarvisCore = Depends(get_core),
    settings: SettingsStore = Depends(get_settings_store),
) -> ModelsResponse:
    try:
        loaded = await core.lm_provider.load_model(request.model_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    settings.update({"model_name": loaded.id})
    models = await core.lm_provider.list_models()
    status = await core.lm_provider.status()
    return ModelsResponse(
        models=[asdict(model) for model in models],
        provider=asdict(status),
    )


@router.get("/events/history", response_model=list[EventResponse])
def event_history(event_bus: EventBus = Depends(get_event_bus)) -> list[EventResponse]:
    return [EventResponse(**event.to_api()) for event in event_bus.history()]


@router.get("/audit/events", response_model=list[dict])
def audit_events(
    limit: int = 100,
    audit_logger: AuditLogger = Depends(get_audit_logger),
) -> list[dict]:
    return audit_logger.list_events(min(max(limit, 1), 500))


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
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        event_bus.unsubscribe(queue)


@router.get("/voice/status", response_model=VoiceStatusResponse)
def voice_status(voice_manager: VoiceManager = Depends(get_voice_manager)) -> VoiceStatusResponse:
    status = voice_manager.status()
    return VoiceStatusResponse(
        state=status.state.value,
        stt_adapter=status.stt_adapter,
        stt_configured=status.stt_configured,
        tts_adapter=status.tts_adapter,
        tts_configured=status.tts_configured,
        stt_detail=(
            str(voice_manager.stt_adapter.model_path)
            if getattr(voice_manager.stt_adapter, "model_path", None)
            else None
        ),
    )


@router.post("/voice/setup", response_model=VoiceSetupResponse)
def setup_voice_model(voice_manager: VoiceManager = Depends(get_voice_manager)) -> VoiceSetupResponse:
    model_path = getattr(voice_manager.stt_adapter, "model_path", None)
    if model_path is None:
        raise HTTPException(status_code=503, detail="Local whisper-cli is not installed")
    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=model_path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            with urllib.request.urlopen(WHISPER_MODEL_URL, timeout=300) as response:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
        if temporary_path.stat().st_size <= 1_000_000:
            raise RuntimeError("Downloaded Whisper model is invalid")
        os.replace(temporary_path, model_path)
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        raise HTTPException(status_code=503, detail=f"Whisper model setup failed: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return VoiceSetupResponse(configured=True, model_path=str(model_path))


@router.post("/voice/state", response_model=VoiceStatusResponse)
def update_voice_state(
    request: VoiceStateRequest,
    voice_manager: VoiceManager = Depends(get_voice_manager),
) -> VoiceStatusResponse:
    voice_manager.transition(VoiceState(request.state))
    return voice_status(voice_manager)


@router.post("/voice/transcribe", response_model=VoiceTranscribeResponse)
def transcribe_voice(
    request: VoiceTranscribeRequest,
    voice_manager: VoiceManager = Depends(get_voice_manager),
) -> VoiceTranscribeResponse:
    try:
        if request.audio_base64:
            try:
                audio = base64.b64decode(request.audio_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(status_code=400, detail="Invalid base64 audio data") from exc
            if len(audio) > 15_000_000:
                raise HTTPException(status_code=413, detail="Audio upload exceeds 15 MB")
            transcript = voice_manager.transcribe_audio(audio, request.audio_suffix)
        elif request.audio_path:
            transcript = voice_manager.transcribe(request.audio_path)
        else:
            raise HTTPException(status_code=400, detail="audio_base64 or audio_path is required")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return VoiceTranscribeResponse(
        transcript=transcript,
        state=voice_manager.status().state.value,
    )


@router.post("/voice/synthesize", response_model=VoiceSynthesizeResponse)
def synthesize_voice(
    request: VoiceSynthesizeRequest,
    voice_manager: VoiceManager = Depends(get_voice_manager),
) -> VoiceSynthesizeResponse:
    try:
        audio_path = voice_manager.synthesize(request.text, request.voice_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return VoiceSynthesizeResponse(
        audio_path=str(audio_path),
        audio_url=f"/api/v1/voice/audio/{audio_path.name}",
        state=voice_manager.status().state.value,
    )


@router.get("/voice/audio/{filename}")
def voice_audio(
    filename: str,
    voice_manager: VoiceManager = Depends(get_voice_manager),
) -> FileResponse:
    status = voice_manager.status()
    if not status.tts_configured:
        raise HTTPException(status_code=404, detail="Text-to-speech adapter is not configured")
    tts_adapter = voice_manager.tts_adapter
    output_dir = getattr(tts_adapter, "output_dir", None)
    if output_dir is None:
        raise HTTPException(status_code=404, detail="Voice audio output is not configured")
    audio_path = (Path(output_dir) / filename).resolve()
    if audio_path.parent != Path(output_dir).resolve() or not audio_path.is_file():
        raise HTTPException(status_code=404, detail=f"Voice audio not found: {filename}")
    return FileResponse(audio_path)


@router.get("/vision/status", response_model=VisionStatusResponse)
def vision_status(
    vision_manager: VisionManager = Depends(get_vision_manager),
) -> VisionStatusResponse:
    status = vision_manager.status()
    return VisionStatusResponse(
        state=status.state.value,
        adapter=status.adapter,
        configured=status.configured,
    )


@router.post("/vision/analyze", response_model=VisionAnalyzeResponse)
def analyze_vision(
    request: VisionAnalyzeRequest,
    vision_manager: VisionManager = Depends(get_vision_manager),
) -> VisionAnalyzeResponse:
    try:
        if request.image_base64:
            try:
                image = base64.b64decode(request.image_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(status_code=400, detail="Invalid base64 image data") from exc
            if len(image) > 20_000_000:
                raise HTTPException(status_code=413, detail="Image upload exceeds 20 MB")
            description = vision_manager.analyze_image(image, request.image_suffix, request.prompt)
        elif request.image_path:
            description = vision_manager.analyze(request.image_path, request.prompt)
        else:
            raise HTTPException(status_code=400, detail="image_base64 or image_path is required")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return VisionAnalyzeResponse(
        description=description,
        state=vision_manager.status().state.value,
    )


@router.get("/image/status", response_model=ImageStatusResponse)
def image_status(
    image_manager: ImageManager = Depends(get_image_manager),
) -> ImageStatusResponse:
    status = image_manager.status()
    return ImageStatusResponse(
        state=status.state.value,
        adapter=status.adapter,
        configured=status.configured,
        network=status.network,
    )


@router.post("/image/generate", response_model=ImageGenerateResponse)
async def generate_image(
    request: ImageGenerateRequest,
    core: JarvisCore = Depends(get_core),
    image_manager: ImageManager = Depends(get_image_manager),
) -> ImageGenerateResponse:
    # Route through the bot so generation is permission-gated, throttled, and
    # audited the same way a chat-triggered "/image ..." request would be.
    response = await core.bot_manager.dispatch(
        BotMessage(
            sender=request.sender,
            recipient="image",
            action="generate",
            payload={"text": request.prompt},
        )
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Image bot not found")
    if not response.ok:
        pending = (response.payload or {}).get("permission_request")
        if isinstance(pending, dict):
            raise HTTPException(
                status_code=403,
                detail=response.error or "Image generation requires approval",
            )
        raise HTTPException(
            status_code=503, detail=response.error or "Image generation failed"
        )
    return ImageGenerateResponse(
        image_url=response.payload["image_url"],
        prompt=response.payload.get("prompt", request.prompt),
        state=image_manager.status().state.value,
    )


@router.get("/image/file/{filename}")
def image_file(
    filename: str,
    image_manager: ImageManager = Depends(get_image_manager),
) -> FileResponse:
    output_dir = Path(image_manager.output_dir).resolve()
    image_path = (output_dir / filename).resolve()
    if image_path.parent != output_dir or not image_path.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found: {filename}")
    return FileResponse(image_path)


@router.post("/agent/research", response_model=ResearchRunResponse, status_code=202)
async def start_research_agent(
    request: ResearchAgentRequest,
    agent: DeepResearchAgent = Depends(get_agent_manager),
) -> ResearchRunResponse:
    # Fire-and-poll: the run starts in the background and returns its run_id
    # immediately, so a long research run never holds the HTTP request open.
    # Full-autonomy-in-a-scope: the agent opens a pre-approved permission scope
    # internally and runs the whole plan unattended, streaming agent.* events.
    # Poll GET /agent/research/{run_id} (or listen to agent.* events) for results.
    try:
        result = agent.start_research(request.goal, request.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ResearchRunResponse(**result)


@router.get("/agent/research/{run_id}", response_model=ResearchRunResponse)
def get_research_agent_run(
    run_id: str,
    agent: DeepResearchAgent = Depends(get_agent_manager),
) -> ResearchRunResponse:
    result = agent.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Research run not found: {run_id}")
    return ResearchRunResponse(**result)


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
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return BackupResponse(
        filename=snapshot.path.name,
        path=str(snapshot.path),
        created_at=snapshot.created_at,
        encrypted=snapshot.encrypted,
    )


@router.get("/recovery/backups", response_model=list[BackupResponse])
def list_backups(
    recovery_manager: RecoveryManager = Depends(get_recovery_manager),
) -> list[BackupResponse]:
    return [
        BackupResponse(
            filename=snapshot.path.name,
            path=str(snapshot.path),
            created_at=snapshot.created_at,
            encrypted=snapshot.encrypted,
        )
        for snapshot in recovery_manager.list_backups()
    ]


@router.get("/recovery/schedule", response_model=BackupScheduleResponse)
def backup_schedule(
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
) -> BackupScheduleResponse:
    return BackupScheduleResponse(**scheduler.status().to_api())


@router.post("/recovery/restore", response_model=RestoreResponse)
def restore_backup(
    request: RestoreRequest,
    recovery_manager: RecoveryManager = Depends(get_recovery_manager),
) -> RestoreResponse:
    try:
        snapshot = recovery_manager.restore_sqlite_backup(request.filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RestoreResponse(
        path=str(snapshot.path),
        restored_from=str(snapshot.restored_from),
        safety_backup=str(snapshot.safety_backup) if snapshot.safety_backup else None,
        created_at=snapshot.created_at,
        encrypted=snapshot.encrypted,
    )
