# O.D.I.N. skills directory

This directory holds **Agent Skills** — portable `SKILL.md` instruction sets that Odin auto-matches
to a request and follows. Each skill is a subfolder:

```
skills/
  my-skill/
    SKILL.md      # YAML frontmatter (name, description) + markdown instructions
    (optional bundled scripts / reference files)
```

Odin (`SkillManager` in `jarvis/backend/core/skill_manager.py`) scans this folder at startup,
lexically matches installed skills to each message, and injects the matched skill's guidance into the
model's context (marked `[Installed skill: …]`). Matching is controlled by the **skills_enabled**
setting (Settings → Skills); `/skills` in chat lists what's installed.

## Adding skills

- **Hand-authored:** drop a folder with a `SKILL.md` here.
- **From a registry** (Agent Skills spec, e.g. NVIDIA's verified skills):
  ```bash
  npx skills add nvidia/skills        # installs the catalog
  ```
  Point Odin at the install location with `JARVIS_SKILLS_DIR`, or copy the folders you want here.

## A note on this Mac

Most of NVIDIA's skills operate CUDA/Linux GPU tooling (training, DeepStream, Jetson) that **cannot
execute on this Apple-silicon machine** — they load as reference only. The skills that are genuinely
runnable here are the ones that drive NVIDIA's **hosted** models/APIs (which Odin already integrates).
Keep that in mind when choosing what to install.

## Safety

Skill text is user-installed reference material injected into context. It never bypasses Odin's
permission-gated bots — any command/file/network action a skill describes still goes through the
normal approval + audit flow. Only install skills you trust; turn matching off with **skills_enabled**.
