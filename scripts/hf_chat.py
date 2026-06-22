#!/usr/bin/env python3
"""Chat with any model on the HF Inference Providers router.

One-off:
    python3 scripts/hf_chat.py <token> <model> "your prompt here"
    HF_TOKEN=hf_... python3 scripts/hf_chat.py <model> "prompt"
    echo "long prompt..." | python3 scripts/hf_chat.py <token> <model>

Interactive (multi-turn, remembers the conversation):
    python3 scripts/hf_chat.py <token> <model>
    python3 scripts/hf_chat.py <token> <model> --chat
    (type your message, Enter to send; 'exit' or Ctrl-D to quit)

Examples:
    python3 scripts/hf_chat.py hf_xxx zai-org/GLM-5.2 "Explain RAFT simply."
    python3 scripts/hf_chat.py hf_xxx moonshotai/Kimi-K2.7-Code   # interactive
"""

import json
import os
import sys
import urllib.error
import urllib.request

ROUTER = "https://router.huggingface.co/v1/chat/completions"
MAX_TOKENS = 20000


def _send(token: str, model: str, messages: list) -> dict:
    body = {"model": model, "messages": messages,
            "max_tokens": MAX_TOKENS, "stream": False}
    req = urllib.request.Request(ROUTER, data=json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "hermes-hf-chat/1.1")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def _extract(out: dict) -> tuple[str, str, str, dict]:
    choice = out["choices"][0]
    msg = choice.get("message", {})
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
    return content, reasoning, choice.get("finish_reason"), out.get("usage", {})


def _print_reply(content: str, reasoning: str, finish: str, usage: dict) -> None:
    if content:
        print(content)
    elif reasoning:
        print("[reasoning only — raise MAX_TOKENS for a final answer]\n")
        print(reasoning)
    else:
        print("[empty response]")
    if finish == "length":
        print("\n[truncated: hit max_tokens]", file=sys.stderr)
    if usage:
        print(f"\n[tokens: {usage.get('total_tokens')} "
              f"| cost: ${usage.get('estimated_cost', 0):.5f}]", file=sys.stderr)


def _repl(token: str, model: str) -> int:
    print(f"Chatting with {model} — type 'exit' or Ctrl-D to quit.\n")
    history: list = []
    while True:
        try:
            user = input("you> ").strip()
        except EOFError:
            print()
            break
        if not user:
            continue
        if user.lower() in ("exit", "quit", ":q"):
            break
        history.append({"role": "user", "content": user})
        try:
            out = _send(token, model, history)
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
            history.pop()  # drop the failed turn so the next try is clean
            continue
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            history.pop()
            continue
        content, reasoning, finish, usage = _extract(out)
        print(f"\n{model.split('/')[-1]}>")
        _print_reply(content, reasoning, finish, usage)
        print()
        # Keep the visible answer in history so the model has context.
        history.append({"role": "assistant", "content": content or reasoning})
    return 0


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

    force_chat = "--chat" in args
    args = [a for a in args if a != "--chat"]

    # Prompt: remaining args joined, else stdin (piped) or interactive REPL.
    prompt = " ".join(args).strip()
    if not prompt and not force_chat:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()

    # No prompt + a real terminal -> interactive multi-turn chat.
    if not prompt:
        if sys.stdin.isatty():
            return _repl(token, model)
        print("FAIL: empty prompt.", file=sys.stderr)
        return 1

    # One-off mode.
    try:
        out = _send(token, model, [{"role": "user", "content": prompt}])
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _print_reply(*_extract(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
