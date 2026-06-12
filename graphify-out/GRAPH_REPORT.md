# Graph Report - .  (2026-06-12)

## Corpus Check
- 79 files · ~84,526 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1004 nodes · 6500 edges · 45 communities (35 shown, 10 thin omitted)
- Extraction: 33% EXTRACTED · 67% INFERRED · 0% AMBIGUOUS · INFERRED: 4368 edges (avg confidence: 0.5)
- Token cost: 157,300 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_API Models & Routes|API Models & Routes]]
- [[_COMMUNITY_Bot Framework|Bot Framework]]
- [[_COMMUNITY_Memory Manager & Migrations|Memory Manager & Migrations]]
- [[_COMMUNITY_Backup & Core Tests|Backup & Core Tests]]
- [[_COMMUNITY_Core Orchestrator|Core Orchestrator]]
- [[_COMMUNITY_Functional Bots|Functional Bots]]
- [[_COMMUNITY_API Endpoint Tests|API Endpoint Tests]]
- [[_COMMUNITY_Backup Scheduler & Recovery|Backup Scheduler & Recovery]]
- [[_COMMUNITY_Frontend Settings & Data Panels|Frontend Settings & Data Panels]]
- [[_COMMUNITY_Vector Store Operations|Vector Store Operations]]
- [[_COMMUNITY_LLM Provider Implementations|LLM Provider Implementations]]
- [[_COMMUNITY_Vector Store Variants|Vector Store Variants]]
- [[_COMMUNITY_Desktop Mockup Design|Desktop Mockup Design]]
- [[_COMMUNITY_LLM Provider Status & Models|LLM Provider Status & Models]]
- [[_COMMUNITY_App Factory & Wiring|App Factory & Wiring]]
- [[_COMMUNITY_Frontend Dependencies|Frontend Dependencies]]
- [[_COMMUNITY_Chat Dock & Voice Hook|Chat Dock & Voice Hook]]
- [[_COMMUNITY_App Shell & Dashboard|App Shell & Dashboard]]
- [[_COMMUNITY_SQLite Vector Store|SQLite Vector Store]]
- [[_COMMUNITY_Voice Manager & Adapters|Voice Manager & Adapters]]
- [[_COMMUNITY_Odin Stage & Rune Reactor|Odin Stage & Rune Reactor]]
- [[_COMMUNITY_Telemetry UI Rails|Telemetry UI Rails]]
- [[_COMMUNITY_System Monitor Telemetry|System Monitor Telemetry]]
- [[_COMMUNITY_Mobile Mockup Design|Mobile Mockup Design]]
- [[_COMMUNITY_README Architecture Concepts|README Architecture Concepts]]
- [[_COMMUNITY_Event Bus|Event Bus]]
- [[_COMMUNITY_Electron Backend Controller|Electron Backend Controller]]
- [[_COMMUNITY_Startup Health UI|Startup Health UI]]
- [[_COMMUNITY_Odin Visual Identity|Odin Visual Identity]]
- [[_COMMUNITY_Manage Script|Manage Script]]
- [[_COMMUNITY_Settings Store|Settings Store]]
- [[_COMMUNITY_Wake Word Loop Binding|Wake Word Loop Binding]]
- [[_COMMUNITY_API Package Init|API Package Init]]
- [[_COMMUNITY_Backend Package Init|Backend Package Init]]
- [[_COMMUNITY_Core Package Init|Core Package Init]]
- [[_COMMUNITY_Wake Word Listener|Wake Word Listener]]
- [[_COMMUNITY_Bots & Permissions Docs|Bots & Permissions Docs]]
- [[_COMMUNITY_Wake Word & Whisper Docs|Wake Word & Whisper Docs]]
- [[_COMMUNITY_Utils Package Init|Utils Package Init]]

## God Nodes (most connected - your core abstractions)
1. `EventBus` - 155 edges
2. `RecoveryManager` - 122 edges
3. `AuditLogger` - 121 edges
4. `PermissionManager` - 121 edges
5. `MemoryManager` - 110 edges
6. `MemoryConsolidator` - 106 edges
7. `BackupScheduler` - 105 edges
8. `JarvisCore` - 105 edges
9. `SettingsStore` - 104 edges
10. `VoiceManager` - 103 edges

## Surprising Connections (you probably didn't know these)
- `Path` --uses--> `MemoryManager`  [INFERRED]
  scripts/manage.py → jarvis/backend/core/memory_manager.py
- `BrokenVectorStore` --uses--> `BotRequest`  [INFERRED]
  tests/test_core.py → jarvis/backend/bots/base.py
- `CoreTests` --uses--> `BotRequest`  [INFERRED]
  tests/test_core.py → jarvis/backend/bots/base.py
- `FakeSpeechToTextAdapter` --uses--> `BotRequest`  [INFERRED]
  tests/test_core.py → jarvis/backend/bots/base.py
- `FakeStreamResponse` --uses--> `BotRequest`  [INFERRED]
  tests/test_core.py → jarvis/backend/bots/base.py

## Import Cycles
- 1-file cycle: `jarvis/backend/api/main.py -> jarvis/backend/api/main.py`
- 1-file cycle: `jarvis/backend/core/backup_scheduler.py -> jarvis/backend/core/backup_scheduler.py`
- 1-file cycle: `jarvis/backend/core/memory_manager.py -> jarvis/backend/core/memory_manager.py`
- 1-file cycle: `jarvis/backend/core/recovery_manager.py -> jarvis/backend/core/recovery_manager.py`

## Hyperedges (group relationships)
- **Voice Pipeline (wake word → STT → TTS)** — readme_wake_word, readme_whisper_stt, readme_piper_voice [EXTRACTED 0.90]
- **Memory Subsystem (vector recall, core blocks, consolidation, alternative backend)** — readme_semantic_memory, readme_core_memory_blocks, readme_sleep_time_consolidation, readme_chromadb_backend [EXTRACTED 0.90]
- **Software Layer Module Ring around AI Core** — design_desktop_mockup_reasoning_engine, design_desktop_mockup_memory_layer, design_desktop_mockup_automation_hub, design_desktop_mockup_vision_stack, design_desktop_mockup_api_orchestrator, design_desktop_mockup_voice_interface, design_desktop_mockup_security_mesh, design_desktop_mockup_analytics_core, design_desktop_mockup_odin_centerpiece [EXTRACTED 1.00]
- **Hardware Layer Root System feeding the AI Core** — design_desktop_mockup_sensors, design_desktop_mockup_edge_devices, design_desktop_mockup_gpu_cluster, design_desktop_mockup_local_storage, design_desktop_mockup_device_bus, design_desktop_mockup_cameras, design_desktop_mockup_microphones, design_desktop_mockup_power_systems, design_desktop_mockup_odin_centerpiece [EXTRACTED 1.00]
- **Right Rail Telemetry Dashboard** — design_desktop_mockup_ai_core_metrics_panel, design_desktop_mockup_activity_stream_panel, design_desktop_mockup_resource_utilization_panel, design_desktop_mockup_system_temperature_panel [EXTRACTED 1.00]
- **Four Status Badges Ringing the Odin Avatar** — design_mobile_mockup_reasoning_engine_badge, design_mobile_mockup_api_orchestrator_badge, design_mobile_mockup_memory_layer_badge, design_mobile_mockup_security_mesh_badge, design_mobile_mockup_odin_avatar [EXTRACTED 1.00]
- **Mobile Dashboard Vertical Layout Flow** — design_mobile_mockup_nexus_ai_header, design_mobile_mockup_connect_phone_button, design_mobile_mockup_odin_avatar, design_mobile_mockup_telemetry_bar, design_mobile_mockup_action_row, design_mobile_mockup_bottom_nav [EXTRACTED 1.00]
- **O.D.I.N. Visual Identity** — assets_odin_head_odin_head_image, assets_odin_head_norse_god_odin_portrait, assets_odin_head_blue_circuit_aesthetic, assets_odin_head_odin_branding [INFERRED 0.85]

## Communities (45 total, 10 thin omitted)

### Community 0 - "API Models & Routes"
Cohesion: 0.24
Nodes (148): BackupResponse, BackupScheduleResponse, BotExecRequest, BotExecResponse, ChatRequest, ChatResponse, ConversationExportResponse, ConversationMessageResponse (+140 more)

### Community 1 - "Bot Framework"
Cohesion: 0.07
Nodes (31): ABC, Bot, BotRequest, BotResponse, Any, AuditLogger, PermissionError, PermissionManager (+23 more)

### Community 2 - "Memory Manager & Migrations"
Cohesion: 0.06
Nodes (16): ConversationRecord, ConversationSummaryRecord, DocumentRecord, MessageRecord, ReflectionRecord, TaskRecord, TTLCache, UserRecord (+8 more)

### Community 3 - "Backup & Core Tests"
Cohesion: 0.07
Nodes (11): FileBot, BackupScheduler, OllamaProvider, InterruptionConfig, CoreTests, MockHttpResponse, BotRequest, BotResponse (+3 more)

### Community 4 - "Core Orchestrator"
Cohesion: 0.10
Nodes (28): BotManager, BotManager, EventBus, JarvisCore, LMProviderInterface, MemoryConsolidator, Sleep-time memory: distills recent conversations into durable memory     documen, MemoryManager (+20 more)

### Community 5 - "Functional Bots"
Cohesion: 0.16
Nodes (30): Bot, CodeBot, ResearchBot, SystemBot, get_voice_manager(), ChromaVectorStore, OllamaEmbedder, Generates embeddings through a local Ollama embedding model. (+22 more)

### Community 7 - "Backup Scheduler & Recovery"
Cohesion: 0.09
Nodes (12): BackupScheduleStatus, BackupSnapshot, IntegrityReport, RecoveryManager, RestoreSnapshot, datetime, EventBus, RecoveryManager (+4 more)

### Community 8 - "Frontend Settings & Data Panels"
Cohesion: 0.12
Nodes (36): BLOCK_LABELS, PERMISSION_DECISIONS, THEME_OPTIONS, VOICE_MODE_OPTIONS, checkRecoveryIntegrity(), createRecoveryBackup(), createReflection(), createTask() (+28 more)

### Community 9 - "Vector Store Operations"
Cohesion: 0.08
Nodes (6): _cosine_similarity(), _pack_vector(), _unpack_vector(), VectorSearchResult, Any, Connection

### Community 10 - "LLM Provider Implementations"
Cohesion: 0.11
Nodes (8): _gemini_error_detail(), LMStudioProvider, Bridge a blocking urllib streaming response into async line iteration., _stream_response_lines(), HistoryTurn, HTTPError, Any, Request

### Community 11 - "Vector Store Variants"
Cohesion: 0.11
Nodes (9): _ollama_timeout_seconds(), InMemoryVectorStore, NullVectorStore, VectorStoreInterface, Path, RLock, VectorStoreInterface, FakeStreamResponse (+1 more)

### Community 12 - "Desktop Mockup Design"
Cohesion: 0.10
Nodes (28): Desktop Mockup (Nexus AI Core System), Activity Stream Panel, AI Core Metrics Panel, Analytics Core Module, API Orchestrator Module, Automation Hub Module, Cameras Hardware Node, Device Bus Hardware Node (+20 more)

### Community 13 - "LLM Provider Status & Models"
Cohesion: 0.10
Nodes (7): EchoLMProvider, GeminiProvider, ModelInfo, ProviderStatus, Google Gemini cloud provider used for turbo mode., Routes to Gemini when turbo mode is enabled, with offline fallback to the local, TurboSwitchProvider

### Community 14 - "App Factory & Wiring"
Cohesion: 0.27
Nodes (21): _allowed_origins(), create_app(), _backup_key(), _default_db_path(), _env_int(), get_audit_logger(), get_backup_scheduler(), get_core() (+13 more)

### Community 15 - "Frontend Dependencies"
Cohesion: 0.08
Nodes (23): dependencies, react, react-dom, vite, @vitejs/plugin-react, zustand, devDependencies, electron (+15 more)

### Community 16 - "Chat Dock & Voice Hook"
Cohesion: 0.19
Nodes (12): ChatDock(), ChatView(), appSettings, chatState, useOdinVoice(), useSpeechSynthesis(), resolveApiUrl(), sendChatMessage() (+4 more)

### Community 17 - "App Shell & Dashboard"
Cohesion: 0.19
Nodes (15): DataPanel(), ProjectDashboard(), TASK_STATUS_OPTIONS, SettingsPanel(), Frontend Entry Page (O.D.I.N. Core System), connectEvents(), fetchSystemOverview(), Legacy Public Entry Page (Jarvis V1.1) (+7 more)

### Community 18 - "SQLite Vector Store"
Cohesion: 0.17
Nodes (7): Semantic memory stored in SQLite with local embeddings — no external services, SqliteVectorStore, Path, RLock, BrokenVectorStore, Any, VectorStoreInterface

### Community 19 - "Voice Manager & Adapters"
Cohesion: 0.14
Nodes (7): SpeechToTextAdapter, TextToSpeechAdapter, VoiceManager, VoiceStatus, EventBus, Protocol, FakeSpeechToTextAdapter

### Community 20 - "Odin Stage & Rune Reactor"
Cohesion: 0.17
Nodes (9): CoreFocusView(), HARDWARE_NODES, SOFTWARE_NODES, RuneCore(), drawRuneReactor(), ELDER_FUTHARK, ringColor(), RINGS (+1 more)

### Community 21 - "Telemetry UI Rails"
Cohesion: 0.28
Nodes (9): MetricsRail(), OdinStage(), TopStrip(), ACTIVITY_LABELS, formatAgo(), formatBytes(), formatRate(), formatUptime() (+1 more)

### Community 22 - "System Monitor Telemetry"
Cohesion: 0.22
Nodes (4): Samples host telemetry and streams it over the event bus., SystemMonitor, Any, EventBus

### Community 23 - "Mobile Mockup Design"
Cohesion: 0.21
Nodes (13): Mobile Mockup (Nexus AI / O.D.I.N. Phone UI), Action Row (System Scan, Rune Reactor, AI Stats), API Orchestrator Status Badge (Connected), Bottom Navigation Bar (Home, Modules, Odin, Logs, Settings), Connect Phone Button, Dark Neon Cyan/Violet Theme, Memory Layer Status Badge (72%), Nexus AI Core System Header (+5 more)

### Community 24 - "README Architecture Concepts"
Cohesion: 0.15
Nodes (13): ChromaDB Alternative Vector Backend, Core Memory Blocks (Persona + User Profile), Electron Desktop Wrapper, Encrypted Full-State Backup & Restore, FastAPI Backend (jarvis.backend.api.main:app), O.D.I.N. (Optical Detection & Intelligence Network), Ollama Local LLM Provider, Piper Neural Voice (TTS) (+5 more)

### Community 25 - "Event Bus"
Cohesion: 0.29
Nodes (4): Event, _jsonable(), Any, Queue

### Community 26 - "Electron Backend Controller"
Cohesion: 0.32
Nodes (4): backend, __dirname, projectRoot, createBackendController()

### Community 27 - "Startup Health UI"
Cohesion: 0.60
Nodes (3): LABELS, StartupHealth(), fetchStartupHealth()

### Community 28 - "Odin Visual Identity"
Cohesion: 0.83
Nodes (4): Blue Energy / Tech-Mythology Aesthetic (electric arcs, circuit-like halo), Norse God Odin Portrait (glowing blue eyes, winged helm, braided beard), O.D.I.N. Assistant Branding, Odin Head Image

### Community 29 - "Manage Script"
Cohesion: 0.67
Nodes (3): init_db(), main(), Path

## Ambiguous Edges - Review These
- `Nexus AI Core System Header` → `O.D.I.N. Allfather of Intelligence Identity`  [AMBIGUOUS]
  design/mobile-mockup.jpg · relation: conceptually_related_to

## Knowledge Gaps
- **70 isolated node(s):** `__dirname`, `projectRoot`, `backend`, `name`, `version` (+65 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Nexus AI Core System Header` and `O.D.I.N. Allfather of Intelligence Identity`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `MemoryManager` connect `Core Orchestrator` to `API Models & Routes`, `Memory Manager & Migrations`, `Backup & Core Tests`, `Functional Bots`, `API Endpoint Tests`, `Vector Store Variants`, `App Factory & Wiring`, `SQLite Vector Store`, `Voice Manager & Adapters`, `Manage Script`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Why does `RecoveryManager` connect `Backup Scheduler & Recovery` to `API Models & Routes`, `Backup & Core Tests`, `Core Orchestrator`, `Functional Bots`, `API Endpoint Tests`, `Vector Store Variants`, `App Factory & Wiring`, `SQLite Vector Store`, `Voice Manager & Adapters`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Why does `EventBus` connect `Core Orchestrator` to `API Models & Routes`, `Bot Framework`, `Backup & Core Tests`, `Wake Word Listener`, `Functional Bots`, `API Endpoint Tests`, `Backup Scheduler & Recovery`, `Vector Store Variants`, `App Factory & Wiring`, `SQLite Vector Store`, `Voice Manager & Adapters`, `System Monitor Telemetry`, `Event Bus`, `Wake Word Loop Binding`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Are the 133 inferred relationships involving `EventBus` (e.g. with `AbstractEventLoop` and `BackupResponse`) actually correct?**
  _`EventBus` has 133 INFERRED edges - model-reasoned connections that need verification._
- **Are the 92 inferred relationships involving `RecoveryManager` (e.g. with `BackupResponse` and `BackupScheduleResponse`) actually correct?**
  _`RecoveryManager` has 92 INFERRED edges - model-reasoned connections that need verification._
- **Are the 108 inferred relationships involving `AuditLogger` (e.g. with `BackupResponse` and `BackupScheduleResponse`) actually correct?**
  _`AuditLogger` has 108 INFERRED edges - model-reasoned connections that need verification._