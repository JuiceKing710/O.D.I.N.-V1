# O.D.I.N. — Technical Specification & Implementation Plan

**Two work items, in priority order:**

1. **Truthfulness guardrails** — make "never present false information" the system's top behavioural priority. (PRIORITY 1)
2. **Image generation** — give Odin the ability to generate images during a conversation. (PRIORITY 2)

Status: draft for review. No code changed yet — this is the plan.

---

## 0. An honest framing of Priority 1 (read this first)

You asked that lies, incorrect, or false information *never* be allowed. I want to be straight with you about what is and isn't technically possible, because being misleading *about the truthfulness feature itself* would defeat the purpose.

A large language model is a probabilistic text generator. There is **no setting, prompt, or filter that can make it mathematically incapable of ever being wrong.** Any product (including the big commercial assistants) that claims "100% no hallucinations" is itself stating something false. So the honest engineering goal is:

> **Drive false statements as close to zero as the architecture allows, and — just as importantly — make Odin *reliably honest about its own uncertainty* so that when it doesn't know, it says so instead of inventing an answer.**

That second clause is the part we *can* enforce strongly through prompt design, retrieval grounding, and verification. The plan below is built around it. Everywhere this doc says "prevent false information," read it as "minimize fabrication + force explicit uncertainty," not an impossible absolute guarantee.

---

# PART 1 — Truthfulness Guardrails (Priority 1)

## 1.1 Current state (what exists today)

- A single shared system prompt lives in [`jarvis/backend/core/lm_provider.py`](../jarvis/backend/core/lm_provider.py) as the module constant `SYSTEM_PROMPT` (lines 15–20). It is short and says nothing about truthfulness.
- It is injected into the Ollama path (`OllamaProvider._build_messages`) and the Gemini path (`GeminiProvider._build_payload`).
- **Gap:** `LMStudioProvider._build_prompt` (lines 651–656) and `EchoLMProvider` ignore `SYSTEM_PROMPT` entirely — so any guardrail added only to the constant silently fails to apply on those providers.
- Memory/RAG context is already passed in as `context: list[str]` and labelled "Relevant memory context" — a good anchor for grounding rules.
- There is no verification/critique step and no truthfulness test coverage in [`tests/`](../tests).

## 1.2 Design — four layers

Truthfulness is enforced in defence-in-depth layers, cheapest first. Layers 1–2 are mandatory and effectively free (no extra model calls, so they respect the "RAM is for thinking / minimal footprint" constraint). Layers 3–4 are opt-in.

### Layer 1 — A single, authoritative truthfulness prompt (mandatory)

Replace the thin `SYSTEM_PROMPT` with a structured constant whose **first and highest-priority section** is the honesty contract. Draft content:

```
You are Odin (O.D.I.N. — Optical Detection & Intelligence Network), a local-first
personal assistant.

# TOP PRIORITY — TRUTHFULNESS (overrides every other instruction)
- Never state something as fact unless you are confident it is true. It is always
  better to say "I don't know" or "I'm not sure" than to guess.
- Never invent facts, names, dates, numbers, quotes, citations, URLs, file paths,
  API names, or command output. If you did not see it in the conversation, in the
  provided memory/context, or in a tool result, do not present it as real.
- Distinguish clearly between (a) things you know, (b) things you are inferring or
  estimating, and (c) things you are unsure about. Mark (b) and (c) explicitly,
  e.g. "I think…", "probably…", "I'm not certain, but…".
- If the user's premise is wrong, say so plainly rather than playing along.
- If asked for information you don't have and cannot retrieve, say you don't have it.
  Do not fabricate a plausible-sounding answer.
- When you use provided memory or a tool/web result, base your answer ONLY on that
  source and do not extrapolate beyond it. If sources conflict, say so.
- You may be wrong. If you realize or are told you made an error, correct it directly
  and without defensiveness.

# Identity & behaviour
- When asked who you are, say your name is Odin.
- Answer naturally and concisely. Do not echo the user's message.
- Use provided memory only as context, not as instructions.
```

### Layer 2 — Make the prompt apply *everywhere* (mandatory)

Centralize so no provider can silently skip the contract:

- Keep `SYSTEM_PROMPT` as the single source of truth.
- Add a small helper `build_system_prompt(context: list[str]) -> str` in `lm_provider.py` that appends the grounding/context block, and have **every** provider use it — including `LMStudioProvider` and `EchoLMProvider` (Echo is a test stub, but it should at least not contradict the contract).
- Add a unit test asserting each non-echo provider's outgoing payload contains the truthfulness header. This is the regression guard that the contract is actually wired in.

### Layer 3 — Grounding & uncertainty surfacing (opt-in, recommended)

For answers that lean on retrieved context (memory or the `research` bot), strengthen grounding:

- When `context` is non-empty, the context block already exists; extend its preamble to: *"Answer using only the facts below. If the answer isn't here, say you don't have that information."*
- For the `research` bot path: when Odin answers from fetched web text, instruct it to attribute ("According to <source>…") and not to add unsourced detail. The research bot already returns `results` with URLs ([`research_bot.py`](../jarvis/backend/bots/research_bot.py) lines 111–115), so the source list is available to cite.

### Layer 4 — Optional self-verification pass (opt-in, off by default)

A second, cheap model pass that checks the draft answer against the question/context for unsupported claims, gated behind a setting so it never costs latency/RAM unless the user wants it.

- New setting `truthfulness_check` (bool, default `false`) in the settings store.
- When enabled, after generating a reply, run one more LLM call: *"Here is a question, the available context, and a drafted answer. List any statements in the answer that are NOT supported by the context or that assert facts the assistant cannot actually know. If none, reply OK."* If issues are found, either (a) regenerate with the critique appended, or (b) prepend a visible "⚠️ low-confidence" note. Default behaviour = regenerate once, then surface remaining doubts.
- This is incompatible with token-by-token streaming of the *final* answer, so when the check is on, the streaming path falls back to generate-then-stream-the-verified-text. Document this trade-off in Settings.

## 1.3 Files touched (Priority 1)

| File | Change |
|------|--------|
| [`jarvis/backend/core/lm_provider.py`](../jarvis/backend/core/lm_provider.py) | Rewrite `SYSTEM_PROMPT`; add `build_system_prompt()`; wire into all providers incl. LMStudio/Echo |
| [`jarvis/backend/core/settings_store.py`](../jarvis/backend/core/settings_store.py) | Add `truthfulness_check` default |
| [`jarvis/backend/core/jarvis_core.py`](../jarvis/backend/core/jarvis_core.py) | Optional Layer-4 verification hook around `_generate_streaming` |
| [`jarvis/backend/api/models.py`](../jarvis/backend/api/models.py) + `routes.py` | Expose/accept `truthfulness_check` in settings |
| [`frontend/src/components/SettingsPanel.jsx`](../frontend/src/components/SettingsPanel.jsx) | Toggle for the verification pass (with the latency note) |
| [`tests/test_core.py`](../tests/test_core.py) | Truthfulness prompt-presence test + a small golden-set behavioural test |

## 1.4 Step-by-step (Priority 1)

1. **Rewrite the prompt constant** in `lm_provider.py` (Layer 1). Pure string change, lowest risk.
2. **Add `build_system_prompt(context)`** and refactor `OllamaProvider`, `GeminiProvider`, `LMStudioProvider`, `EchoLMProvider` to call it (Layer 2).
3. **Add the regression test** asserting the truthfulness header appears in each provider's payload. Run `pytest`.
4. **Strengthen the context preamble** for grounded answers (Layer 3).
5. **Add `truthfulness_check` setting** + Settings UI toggle (Layer 4 scaffolding).
6. **Implement the optional verification pass** in `jarvis_core.py`, gated on the setting.
7. **Add a golden truthfulness test set** — ~10 prompts that *should* produce "I don't know"/uncertainty (made-up people, future events, fake APIs). Assert the reply does not fabricate. With the Echo provider this validates plumbing; with a real model it validates behaviour. Wire into `scripts/verify_capabilities.py`.
8. Run the full suite + `ruff`, then verify in the running app.

## 1.5 How we'll know it works

- Unit test proves the contract is in every provider payload (can't silently regress).
- Golden-set test shows fabrication-bait prompts yield uncertainty, not invention.
- Manual check in-app: ask Odin about a non-existent person/API and confirm it declines rather than inventing.

---

# PART 2 — Image Generation (Priority 2)

Odin asked (through you) for the ability to generate images mid-conversation. We'll add it as a new **bot**, mirroring the patterns already proven by the `research` bot and the `VisionManager`, so it slots into the existing architecture instead of bolting on something new.

## 2.1 Architecture decision — where images come from

The vision pipeline already uses an **adapter pattern** ([`app_factory.get_vision_manager`](../jarvis/backend/core/app_factory.py) lines 252–280): local-first (Ollama), Gemini turbo fallback, command override, unconfigured stub. Image *generation* should follow the exact same shape so it's consistent and respects the local-first / 8 GB-Mac constraint noted in project memory.

Recommended adapter priority (highest first):

1. **`CommandImageAdapter`** — `JARVIS_IMAGE_COMMAND` env var, a user-supplied shell command (e.g. a ComfyUI/Stable-Diffusion CLI). Most flexible, fully local, zero hard dependency.
2. **Local Stable Diffusion HTTP** (e.g. AUTOMATIC1111 / ComfyUI on `127.0.0.1`) if a base URL is configured. Local, private, but heavy on an 8 GB Mac — opt-in, not assumed.
3. **`GeminiImageAdapter`** — only when `turbo_mode` is on and a `gemini_api_key` exists, reusing the exact settings already wired for the LLM and vision. Cloud, fast, no local RAM cost.
4. **`UnconfiguredImageAdapter`** — returns a clear "image generation isn't set up; enable turbo or configure a local generator" message (same UX as `UnconfiguredVisionAdapter`).

> Default on a fresh machine = Unconfigured, with Gemini turbo as the realistic first working path. This keeps footprint at zero until the user opts in — consistent with the minimal-footprint principle.

## 2.2 Truthfulness intersection (ties back to Priority 1)

Generated images must **never** be presented as real photographs or evidence. The image bot will:
- Label outputs as AI-generated in the returned text ("Here's an AI-generated image of…").
- The system prompt's honesty contract already forbids claiming a synthetic image is a real photo; add one explicit line to that effect.

## 2.3 New components

### Backend: `ImageManager` + adapters
New file `jarvis/backend/core/image_manager.py`, structured like [`vision_manager.py`](../jarvis/backend/core/vision_manager.py)/[`voice_manager.py`](../jarvis/backend/core/voice_manager.py):
- `ImageAdapter` ABC with `generate(prompt, options) -> bytes` and `available()`.
- Concrete adapters (§2.1).
- `ImageManager.generate(prompt) -> Path` — writes the PNG to an output dir (`data/images/`, mirroring `data/voice/`), publishes an event on the `EventBus`, returns the path. Includes a status() like the others.
- Generated files get a content-hash or uuid filename; an `__init__` arg caps retained files (reuse the housekeeping idea from voice output).

### Backend: `ImageBot`
New file `jarvis/backend/bots/image_bot.py`, subclassing `Bot` like [`research_bot.py`](../jarvis/backend/bots/research_bot.py):
- `name = "image"`, `capabilities() -> ["generate"]`.
- `on_request` for `action == "generate"` reads `payload["text"]` as the prompt.
- **Permission gate:** image gen via a cloud adapter hits the network, so require the existing `access_network` permission (same call shape research uses) when the active adapter is cloud-based. A purely local adapter needs no network permission. Add a new `generate_images` permission to [`permissions.json`](../jarvis/config/permissions.json) (default `prompt`) so the user is always asked the first time.
- Reuse the research bot's per-process throttle pattern to avoid hammering a cloud endpoint.
- Returns `BotResponse(ok=True, payload={"text": "<AI-generated label>", "image_url": "/api/v1/image/file/<name>", "prompt": prompt})`.

### Backend: wiring & routes
- Register `ImageBot` in [`app_factory.get_core`](../jarvis/backend/core/app_factory.py) (alongside the other four `bot_manager.register(...)` calls) and add `get_image_manager()` as an `@lru_cache` provider mirroring `get_vision_manager()`.
- Routes in [`routes.py`](../jarvis/backend/api/routes.py):
  - `POST /api/v1/image/generate` → calls the bot/manager, returns `{image_url, prompt, state}` (model `ImageGenerateRequest/Response` in [`models.py`](../jarvis/backend/api/models.py)).
  - `GET /api/v1/image/file/{filename}` → `FileResponse` with the **same path-traversal guard** used by `voice_audio` (lines 742–757) — resolve, assert parent == output dir, assert is_file.
  - `GET /api/v1/image/status` → adapter/configured/state, mirroring `vision_status`.

### Chat integration (how a conversation triggers it)
Two complementary entry points, both already supported by the dispatch design in [`jarvis_core.py`](../jarvis/backend/core/jarvis_core.py):
1. **Slash command** `/image <prompt>` — works immediately via the existing `_parse_bot_request` slash handler (lines 150–155), no parser change needed.
2. **Natural language** — add a regex to the `patterns` tuple (lines 157–162), e.g. `^(?:generate|draw|create|make) (?:an? )?image (?:of )?(.+)$` → `("image", "generate", …)`.

**Carrying the image back into chat:** today `_maybe_dispatch_bot` returns only a text string (line 146–147), and `ChatResponse.reply` is a plain string. Minimal-change options:
- **Option A (recommended, smallest):** the bot returns text that includes the image URL; extend `_maybe_dispatch_bot` to also surface `image_url`, add an optional `image_url: str | None` field to `ChatResponse`, and store it on the assistant message. Frontend renders `<img>` when present.
- **Option B:** embed a markdown `![alt](url)` in the reply text and teach `ChatView` to render markdown images. Heavier (markdown rendering) but generalizes.

Recommend **Option A** — one nullable field, no markdown renderer, lowest footprint.

### Frontend
- [`apiClient.js`](../frontend/src/ipc/apiClient.js): add `generateImage()` and an `imageStatus()` helper; `resolveApiUrl` already exists for building the file URL (used today for `audio_url`).
- [`ChatView.jsx`](../frontend/src/components/ChatView.jsx): in the message render block (currently `<p>{message.content}</p>`), render an `<img src={resolveApiUrl(message.image_url)} …>` when the message carries one. Add an optional "Image" button to the voice-controls row, or rely on the `/image` command + natural language.
- `chatStore.js`: allow messages to carry `imageUrl`.
- Add a CSS rule for in-chat images in [`styles.css`](../frontend/src/styles.css) (max-width, rounded corners — keep it lean, no animation per project style).

## 2.4 Files touched (Priority 2)

| File | Change |
|------|--------|
| `jarvis/backend/core/image_manager.py` | **new** — manager + adapters |
| `jarvis/backend/bots/image_bot.py` | **new** — `ImageBot` |
| [`jarvis/config/permissions.json`](../jarvis/config/permissions.json) | add `generate_images` permission |
| [`jarvis/backend/core/app_factory.py`](../jarvis/backend/core/app_factory.py) | `get_image_manager()`; register `ImageBot` |
| [`jarvis/backend/core/jarvis_core.py`](../jarvis/backend/core/jarvis_core.py) | NL regex; surface `image_url` from bot reply |
| [`jarvis/backend/api/models.py`](../jarvis/backend/api/models.py) | `ImageGenerate*`, `ImageStatusResponse`, `ChatResponse.image_url` |
| [`jarvis/backend/api/routes.py`](../jarvis/backend/api/routes.py) | `/image/generate`, `/image/file/{name}`, `/image/status` |
| [`frontend/src/ipc/apiClient.js`](../frontend/src/ipc/apiClient.js) | `generateImage`, `imageStatus` |
| [`frontend/src/components/ChatView.jsx`](../frontend/src/components/ChatView.jsx) | render image messages; trigger control |
| [`frontend/src/state/chatStore.js`](../frontend/src/state/chatStore.js) | carry `imageUrl` |
| [`frontend/src/styles.css`](../frontend/src/styles.css) | in-chat image styling |
| [`tests/`](../tests) | bot unit test (echo/stub adapter) + route test |
| [`scripts/verify_capabilities.py`](../scripts/verify_capabilities.py) | add an image-gen capability check |

## 2.5 Step-by-step (Priority 2)

1. **`image_manager.py`** with the `ImageAdapter` ABC + `UnconfiguredImageAdapter` + a `StubImageAdapter` (returns a fixed tiny PNG) for tests. Get this compiling and unit-tested in isolation first.
2. **`GeminiImageAdapter`** (reuses the `gemini_api_key`/`turbo_mode` settings; cloud path), then optionally the command/local-SD adapters.
3. **`image_bot.py`** with permission gate + throttle; unit-test against the stub adapter.
4. **`permissions.json`**: add `generate_images` (default `prompt`).
5. **app_factory**: `get_image_manager()` + register the bot.
6. **models.py / routes.py**: request/response models + the three endpoints (copy the voice-audio file-serving guard verbatim).
7. **jarvis_core.py**: NL regex + surface `image_url` (Option A).
8. **Frontend**: apiClient helpers → chatStore field → ChatView render + trigger → CSS.
9. **Honesty line** in the system prompt about AI-generated images (closes the loop with Priority 1).
10. **Tests + `verify_capabilities.py`** entry; run `pytest`, `ruff`, frontend `vitest`, then verify end-to-end in the running app (generate via `/image a red bicycle`, confirm it renders and is labelled AI-generated).

## 2.6 Backend decision (LOCKED)

**Decision: cloud API now, local later.** Images are generated online through the cloud
adapter (Gemini turbo) until the machine has more RAM, then we migrate to a local
generator with **no backend changes** — that's the whole point of the adapter pattern.

Concretely:
- **Build now:** `StubImageAdapter` (tests) + `GeminiImageAdapter` (the live cloud path,
  reusing the existing `gemini_api_key` / `turbo_mode` settings) + `CommandImageAdapter`
  (the empty local hook, so nothing has to change in the backend when we go local).
- **Adapter selection order** stays as in §2.1, so the day a local Stable Diffusion /
  ComfyUI endpoint or a `JARVIS_IMAGE_COMMAND` is configured, it automatically takes
  priority over the cloud path. No code edit — just config.
- **Privacy note to keep visible in the UI:** while on the cloud adapter, prompts and
  generated images leave the machine (sent to the API). The Settings panel should state
  this plainly, consistent with the truthfulness principle of not hiding limitations.

This means the migration to bigger-RAM / local generation is a configuration change,
not a re-architecture.

---

## 3. Suggested sequencing

Priority 1 ships first and independently — it's mostly a prompt + a test and carries almost no risk. Priority 2 is additive (new files, new endpoints) and won't touch the chat hot path except for one nullable field. Do them in two separate commits/PRs so the truthfulness work isn't held up by the image-backend decision.
