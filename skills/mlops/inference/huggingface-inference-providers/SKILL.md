---
name: huggingface-inference-providers
description: "HuggingFace Inference Providers: route to 20+ open models via router.huggingface.co."
version: 1.0.0
author: Nous Research
license: MIT
tags: [huggingface, hf, inference, open-models, GLM, MiniMax, Kimi, Qwen, DeepSeek, MiMo, mlops]
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [HuggingFace, Inference-Providers, Open-Models, Qwen, DeepSeek, Kimi, MiniMax, GLM, MiMo, URL-first]
    related_skills: [huggingface-hub, vllm, llama-cpp]
---

# Hugging Face Inference Providers

Use this skill when the user wants to run open models (Qwen, DeepSeek, Kimi, MiniMax,
GLM, MiMo, …) through the HuggingFace router, configure hermes-agent to use HF as its
inference backend, or point Claude Code at HF instead of Anthropic.

## What it is

`router.huggingface.co/v1` is a unified OpenAI-compatible endpoint that sits in front
of multiple compute backends (Cerebras, Together AI, Fireworks, SambaNova, Replicate, …).
You pick a model by its Hub ID; the router dispatches to the cheapest available backend
that hosts it. You pay provider rates with no markup, billed to your HF credits.

Key properties:
- **OpenAI-compatible** — standard `/v1/chat/completions` and `/v1/models` endpoints
- **No markup** — you pay exactly what the compute provider charges
- **20+ models** — Qwen, DeepSeek, Kimi, MiniMax, GLM, MiMo, and more
- **Free tier included** — small monthly credit for low-volume usage

## When to use

- Run open models without managing infrastructure
- Use Claude Code workflows (hermes-agent or the CLI) on open models instead of Anthropic
- Compare multiple open models against the same prompt
- Keep costs predictable via HF's unified billing
- Access the latest open-weight frontier models the moment they're added to the router

## Setup

### 1. Get an HF token

1. Go to huggingface.co/settings/tokens
2. Create a **Fine-grained** token (or use an existing one)
3. Enable the **"Make calls to Inference Providers"** permission
4. Copy the token — it starts with `hf_`

### 2. Configure hermes-agent

Add to `~/.hermes/.env` (or export in your shell):

```bash
HF_TOKEN=hf_YOUR_TOKEN_HERE
```

That's it. The hermes-agent `huggingface` provider is auto-discovered and wired to
`router.huggingface.co/v1`. No other config is required.

To override the router URL (e.g. a private HF Enterprise gateway):

```bash
HF_BASE_URL=https://your-enterprise-gateway.huggingface.co/v1
```

### 3. Pick a model and run

```bash
# List models available on the router (requires HF_TOKEN)
hermes /model huggingface

# Run with a specific model
hermes --provider huggingface --model moonshotai/Kimi-K2.5

# Or set as the default provider
hermes /provider huggingface
hermes /model Qwen/Qwen3.5-397B-A17B
```

## Available models (current router catalog)

All model IDs use their full HuggingFace Hub path.

| Model | Notes |
|-------|-------|
| `moonshotai/Kimi-K2.5` | Kimi latest; strong coding + reasoning |
| `moonshotai/Kimi-K2.6` | Kimi updated variant |
| `moonshotai/Kimi-K2-Thinking` | Kimi extended thinking / chain-of-thought |
| `Qwen/Qwen3.5-397B-A17B` | Qwen MoE flagship |
| `Qwen/Qwen3.5-35B-A3B` | Qwen MoE mid-tier |
| `deepseek-ai/DeepSeek-V3.2` | DeepSeek latest MoE |
| `MiniMaxAI/MiniMax-M2.5` | MiniMax flagship |
| `zai-org/GLM-5` | Zhipu GLM-5 |
| `XiaomiMiMo/MiMo-V2-Flash` | Xiaomi MiMo fast variant |

The live catalog may include additional models. Run `hermes /model huggingface` to see
what's currently available (queries `router.huggingface.co/v1/models` with your token).

## Using HF Inference Providers with Claude Code

Claude Code (the Anthropic CLI) respects `ANTHROPIC_BASE_URL` to redirect its API
calls. Point it at the HF router to run Claude Code's agent loop on open models:

```bash
export ANTHROPIC_BASE_URL=https://router.huggingface.co/v1
export ANTHROPIC_API_KEY=hf_YOUR_TOKEN_HERE
claude  # now uses HF inference providers instead of Anthropic
```

What happens under the hood:
1. Claude Code constructs its normal request payload
2. Instead of sending to `api.anthropic.com`, it sends to `router.huggingface.co/v1`
3. The HF router dispatches to whichever backend hosts your chosen model
4. Responses come back in the same format Claude Code expects

This is useful when you want Claude Code's full workflow (file editing, tool use,
multi-turn sessions) but want it running on open models, billed through HF credits.

## Checking health

```bash
hermes /doctor huggingface
```

This hits `router.huggingface.co/v1/models` with your token and reports whether
the endpoint is reachable and the token has the correct permissions.

## HF Hub operations from within hermes-agent

For Hub operations (model search, uploads, dataset management, evaluations), load
the `huggingface-hub` skill — it covers the `hf` CLI which is separate from
the inference router:

```
/skill huggingface-hub
```

That skill handles `hf download`, `hf upload`, `hf datasets`, `hf models`, and the
full Hub API surface. The inference providers router covered here is only the
`/v1/chat/completions` inference path.
