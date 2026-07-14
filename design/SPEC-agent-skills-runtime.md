# O.D.I.N. — Agent Skills Runtime (Scoping & Design)

Status: **scoping draft for review. No code changed yet.** This is the "scope it first" write-up
for giving Odin the ability to use NVIDIA-Verified Agent Skills (and Agent Skills generally).

---

## 0. Honest framing (read first)

NVIDIA's "skills" ([docs.nvidia.com/skills](https://docs.nvidia.com/skills)) are **Agent Skills** —
portable `SKILL.md` instruction sets built on the open Agent Skills spec, installed with
`npx skills add nvidia/skills`, meant to run inside *skills-aware agent clients* (Claude Code,
Codex, Aider, …). Two facts shape everything below:

1. **Claude Code already has this catalog.** The ~200 `cuopt-*`, `nemo-*`, `deepstream-*`,
   `jetson-*`, `tao-*`, `vss-*` skills available to the assistant *are* NVIDIA's verified skills.
   For helping build/operate NVIDIA tech in this repo, they are already usable on the assistant side.

2. **Odin has no skills runtime, and this Mac has no NVIDIA GPU.** Odin's capabilities are its
   permission-gated **bots** ([`jarvis/backend/bots/`](../jarvis/backend/bots/)), not an Agent-Skills
   loader. And the M2 (Metal, ~5 GiB VRAM, no CUDA) cannot run the GPU/Linux tooling most of these
   skills operate. So the *executable* value of NVIDIA skills on this machine is small and overlaps
   heavily with the hosted-model API already integrated (`NvidiaProvider`).

**Conclusion up front:** a Skills runtime is worth building mainly as a **general Odin capability**
(any Agent Skill, from any publisher), not specifically to unlock NVIDIA's GPU skills on a Mac.
The NVIDIA subset it would realistically execute here is the *hosted-API* workflows — which mostly
reduce to "call build.nvidia.com," something Odin can already do.

---

## 1. Which NVIDIA skills are actually runnable here?

| Bucket | Runs on your Mac? | Examples | Notes |
|---|---|---|---|
| **Hosted-API / CPU** | ✅ Yes | `nemo-evaluator`, `nemo-retriever`, `data-designer`, `rag-eval`, `skill-creator`, `find-skills` | Drive build.nvidia.com NIM endpoints or are pure-Python/meta. Real fit, but small set. |
| **Cloud-GPU orchestration** | ⚠️ Only with a remote GPU | `tao-run-on-brev`, `tao-run-on-kubernetes`, `tao-run-on-slurm`, `aiq-deploy`, `dynamo-*`, `rag-blueprint` | Command runs *from* the Mac but provisions/targets a GPU box you don't have. |
| **Local GPU / Linux required** | ❌ No | all `jetson-*`, `tao-train-*`, `deepstream-*`, `holoscan-*`, `mcore-*`, `cupynumeric-*`, `tilegym-*`, `omniverse-*`, `physicsnemo-*`, most `nemo-*`/`nemotron-*` training | Need CUDA/Jetson hardware. Would load as instructions but cannot execute locally. |

So of ~200 skills, only a handful in bucket 1 are directly executable on this hardware, and they
largely mirror the NVIDIA model API already wired in.

---

## 2. Proposed design — an Odin Skills subsystem

Fits Odin's existing manager/adapter + DI pattern and reuses its embedder, vector store, bots, and
permission/audit machinery.

### 2.1 Skill store
- A `skills/` directory (configurable via `JARVIS_SKILLS_DIR`). Each skill = a folder with a
  `SKILL.md` (YAML frontmatter `name`/`description`, markdown body of instructions) plus optional
  bundled scripts/resources — i.e. Agent-Skills-spec compatible, so `npx skills add nvidia/skills`
  output drops straight in.

### 2.2 `SkillManager` (new, wired in [`app_factory.py`](../jarvis/backend/core/app_factory.py))
- On startup, scan the dir and parse frontmatter into a registry of `SkillInfo(name, description,
  path)`. Missing dir / bad frontmatter → skipped with a warning (matches the `Unconfigured*`
  no-op fallback convention).

### 2.3 Matching (progressive disclosure)
- **Explicit:** `/skill <name> <task>` or "use the <name> skill to …".
- **Automatic:** embed each skill's `description` (reuse `OllamaEmbedder` + `VectorStore`) and,
  per message, retrieve the top-matching skill(s); inject only the matched `SKILL.md` **body** into
  context (kept out of context until relevant, to control token cost). Bundled resource files load
  on demand through the existing `file` bot.

### 2.4 Execution & safety (the important part)
- A skill's instructions become model context; when a skill says "run X" / "write file Y", it routes
  through Odin's existing `system`/`file`/`code` bots — which are already **permission-gated and
  audit-logged** ([`utils/permissions.py`](../jarvis/backend/utils/permissions.py),
  [`utils/audit_logging.py`](../jarvis/backend/utils/audit_logging.py)). Skills inherit that safety
  model; nothing high-impact auto-runs.
- **Trust boundary:** skill text is instructions the *user opted into installing*, but a third-party
  skill is still untrusted content that can request side effects. Gate skill-initiated actions behind
  a new `use_skills` permission (default `prompt`), and prefer NVIDIA's signed/scanned skills.

### 2.5 API + UI
- `GET /api/v1/skills` (list + enabled state), `POST /api/v1/skills/reload`, enable/disable.
- A Skills panel (Settings or Data Map) listing installed skills, source, and a toggle; surface
  "skill X engaged" on the event stream so it's visible when a skill fires.

### 2.6 Make Odin aware
- Extend `SYSTEM_PROMPT` so Odin knows it can consult installed skills, and inject a short
  `[Skills available]` context note (like the existing `[Current model]` note) when skills match.

---

## 3. Suggested phases
1. **Phase 1 (core):** `SkillManager` + store + explicit `/skill` invocation + execution via bots
   under a `use_skills` permission. Download `nvidia/skills` into `skills/`.
2. **Phase 2:** automatic embedding-based matching + progressive disclosure + event-stream surfacing.
3. **Phase 3:** Settings/Data Map UI, enable/disable, skill cards.

## 4. Open decisions (need your call)
- **Auto-match vs explicit-only** to start? (Auto is nicer but riskier and costs tokens.)
- **Which skills to install** — the whole NVIDIA catalog, or just the Mac-runnable bucket-1 subset?
- **General vs NVIDIA-only** — build the runtime as a general Agent-Skills capability (recommended,
  more durable) or scope it narrowly to NVIDIA?
- **Trust posture** — restrict to NVIDIA's signed skills at first, or allow any Agent Skill?

## 5. Recommendation
Build the runtime as a **general Agent-Skills capability** (Phase 1 first), install **only the
bucket-1 Mac-runnable NVIDIA skills** to start, keep everything behind the `use_skills` permission,
and lean on the NVIDIA hosted-model API (already integrated) for the actual "advanced AI" compute.
Treat GPU/Jetson skills as reference-only unless you add a cloud GPU later, at which point the
cloud-GPU-orchestration bucket becomes live too.
