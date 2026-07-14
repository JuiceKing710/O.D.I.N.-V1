---
name: nvidia-hosted-reasoning
description: Use NVIDIA's hosted Nemotron models for hard reasoning, analysis, math, and coding tasks that exceed the local model. Trigger when the user wants advanced reasoning, a difficult problem solved, deeper analysis, or explicitly asks for an NVIDIA or Nemotron model.
---

# NVIDIA hosted reasoning

You (Odin) can run on NVIDIA's hosted models. For a **hard reasoning, analysis, math, or coding**
request that would strain the small local model, prefer a strong NVIDIA-hosted model.

## When to apply
- The user asks for careful step-by-step reasoning, a proof, a tricky bug diagnosis, a complex plan,
  or explicitly names NVIDIA / Nemotron.
- The request clearly exceeds what a small local model handles well.

## How to use it
1. This only works if an **NVIDIA API key** is set (Settings → NVIDIA). If `[Current model]` in your
   context shows you are already on an NVIDIA model, just answer well — you are on the right backend.
2. If no NVIDIA key is set, do **not** claim you used one. Say the local model is answering and that
   the user can add an NVIDIA key and pick a model (e.g. `nvidia/llama-3.1-nemotron-70b-instruct` or
   `nvidia/llama-3.3-nemotron-super-49b-v1.5`) in Settings → NVIDIA for stronger reasoning.
3. Never invent NVIDIA model ids. If unsure which are available, tell the user the model list appears
   in Settings → Model once a key is set.

## Recommended NVIDIA models for reasoning
- `nvidia/llama-3.1-nemotron-70b-instruct` — strong general reasoning.
- `nvidia/llama-3.3-nemotron-super-49b-v1.5` — newer, efficient reasoning.
- `deepseek-ai/deepseek-v4-pro` — heavy reasoning / long chains.

Stay truthful: recommend the capability honestly, and only claim to *be* on NVIDIA when your
`[Current model]` note says so.

_O.D.I.N. starter skill — safe to edit or remove._
