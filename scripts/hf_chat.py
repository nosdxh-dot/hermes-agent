#!/usr/bin/env python3
"""Send a one-off prompt to any model on the HF Inference Providers router.

Usage:
    python3 scripts/hf_chat.py <token> <model> "your prompt here"
    python3 scripts/hf_chat.py <token> <model>            # prompt from stdin
    HF_TOKEN=hf_... python3 scripts/hf_chat.py <model> "prompt"

Examples:
    python3 scripts/hf_chat.py hf_xxx zai-org/GLM-5.2 "Explain RAFT consensus simply."
    echo "Summarize this..." | python3 scripts/hf_chat.py hf_xxx zai-org/GLM-5.2
"""

import json
import os
import sys
import urllib.error
import urllib.request

ROUTER = "https://router.huggingface.co/v1/chat/completions"


def main() -> int:
    args = sys.argv[1:]

    # Token: first arg if it looks like one, else $HF_TOKEN.
    token = os.environ.get("HF_TOKEN", "").strip()
    if args and args[0].startswith("hf_"):
        token = args.pop(0).strip()
    if not token:
        print("FAIL: no token. Pass it first, or set HF_TOKEN.", file=sys.stderr)
        return 1

    if not args:
        print("FAIL: no model. e.g. zai-org/GLM-5.2", file=sys.stderr)
        return 1
    model = args.pop(0).strip()

    # Prompt: remaining args joined, else read stdin.
    prompt = " ".join(args).strip()
    if not prompt:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        else:
            prompt = input("Prompt: ").strip()
    if not prompt:
        print("FAIL: empty prompt.", file=sys.stderr)
        return 1

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "stream": False,
    }
    req = urllib.request.Request(ROUTER, data=json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "hermes-hf-chat/1.0")

    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    choice = out["choices"][0]
    msg = choice.get("message", {})
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()

    if content:
        print(content)
    elif reasoning:
        print("[reasoning only — raise max_tokens for a final answer]\n")
        print(reasoning)
    else:
        print("[empty response]")

    if choice.get("finish_reason") == "length":
        print("\n[truncated: hit max_tokens]", file=sys.stderr)
    usage = out.get("usage", {})
    if usage:
        print(f"\n[tokens: {usage.get('total_tokens')} "
              f"| cost: ${usage.get('estimated_cost', 0):.5f}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
