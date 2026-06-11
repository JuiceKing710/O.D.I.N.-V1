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
    EventResponse,
    IntegrityResponse,
    MemoryItem,
    MemoryQueryRequest,
    MemoryQueryResponse,
    MemoryStatusResponse,
    ModelLoadRequest,
    ModelsResponse,
    PermissionRequestResponse,
    PermissionResolveRequest,
    PermissionResolveResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    StartupHealthResponse,
    ReflectionRequest,
    ReflectionResponse,
    RestoreRequest,
    RestoreResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
    VoiceStateRequest,
    VoiceStatusResponse,
    VoiceSynthesizeRequest,
    VoiceSynthesizeResponse,
    VoiceSetupResponse,
    VoiceTranscribeRequest,
    VoiceTranscribeResponse,
)
from jarvis.backend.core.app_factory import (
    get_backup_scheduler,
    get_audit_logger,
    get_core,
    get_event_bus,
    get_permission_manager,
    get_recovery_manager,
    get_settings_store,
    get_voice_manager,
)
from jarvis.backend.core.backup_scheduler import BackupScheduler
from jarvis.backend.core.bot_manager import BotMessage
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.jarvis_core import JarvisCore
from jarvis.backend.core.recovery_manager import RecoveryManager
from jarvis.backend.core.settings_store import SettingsStore
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
    return SettingsResponse(**data)


@router.get("/health/startup", response_model=StartupHealthResponse)
async def startup_health(
    core: JarvisCore = Depends(get_core),
    voice_manager: VoiceManager = Depends(get_voice_manager),
    recovery_manager: RecoveryManager = Depends(get_recovery_manager),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
) -> StartupHealthResponse:
    provider = await core.lm_provider.status()
    voice = voice_manager.status()
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
) -> SettingsResponse:
    patch = request.model_dump(exclude_none=True)
    try:
        if "permissions" in patch:
            permission_manager.update_decisions(patch["permissions"])
        settings.update(patch)
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
