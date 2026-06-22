#!/usr/bin/env python3
"""HF Inference Providers smoke test.

Verifies the full path: token validity -> inference permission -> live chat
completion through router.huggingface.co. Each layer reports PASS/FAIL with the
real HTTP error body so failures are unambiguous.

Usage:
    python3 scripts/hf_smoke_test.py hf_yourtoken
    HF_TOKEN=hf_yourtoken python3 scripts/hf_smoke_test.py
    python3 scripts/hf_smoke_test.py            # will prompt (input hidden)

Optional second arg overrides the model:
    python3 scripts/hf_smoke_test.py hf_yourtoken zai-org/GLM-5
"""

import json
import os
import sys
import urllib.error
import urllib.request

ROUTER = "https://router.huggingface.co/v1"
WHOAMI = "https://huggingface.co/api/whoami-v2"
DEFAULT_MODEL = "moonshotai/Kimi-K2.5"


def _get(url: str, token: str, timeout: float = 20.0):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "hermes-hf-smoke/1.0")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def _post(url: str, token: str, body: dict, timeout: float = 60.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "hermes-hf-smoke/1.0")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def _resolve_token() -> str:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    env = os.environ.get("HF_TOKEN", "").strip()
    if env:
        return env
    try:
        import getpass
        return getpass.getpass("Paste HF token (hidden): ").strip()
    except Exception:
        return ""


def main() -> int:
    token = _resolve_token()
    model = sys.argv[2].strip() if len(sys.argv) > 2 else DEFAULT_MODEL

    # ── Layer 0: token shape ──────────────────────────────────────────
    print(f"token: loaded={bool(token)} length={len(token)} starts={token[:6]!r}")
    if not token:
        print("FAIL: no token provided. Pass it as the first argument.")
        return 1
    if token == "hf_YOUR_NEW_TOKEN" or "YOUR" in token.upper():
        print("FAIL: that's the placeholder, not a real token.")
        return 1
    if not token.startswith("hf_"):
        print("WARN: token does not start with 'hf_' — double-check it.")
    if len(token) < 30:
        print(f"WARN: token is only {len(token)} chars; real HF tokens are ~37.")

    # ── Layer 1: token validity (whoami) ──────────────────────────────
    print("\n[1/3] whoami (is the token valid at all?)")
    try:
        _, me = _get(WHOAMI, token)
        print(f"  PASS  user={me.get('name')!r} type={me.get('type')!r}")
        perms = (me.get("auth", {}) or {}).get("accessToken", {}) or {}
        if perms:
            print(f"  token role/perms: {perms.get('role') or perms.get('fineGrained') or perms}")
    except urllib.error.HTTPError as e:
        print(f"  FAIL  HTTP {e.code}: {e.read().decode()[:300]}")
        print("  -> Token is invalid or revoked. Make a fresh one at")
        print("     https://huggingface.co/settings/tokens")
        return 1
    except Exception as e:
        print(f"  FAIL  network/other: {e}")
        return 1

    # ── Layer 2: inference catalog (does the token have inference?) ────
    print("\n[2/3] GET /v1/models (does the token have Inference Providers perm?)")
    try:
        _, data = _get(f"{ROUTER}/models", token)
        models = data.get("data", data) if isinstance(data, dict) else data
        ids = [m.get("id", m) if isinstance(m, dict) else m for m in models]
        print(f"  PASS  {len(ids)} models reachable")
        for mid in ids[:8]:
            mark = "  -> requested" if mid == model else ""
            print(f"        {mid}{mark}")
        if model not in ids:
            print(f"  NOTE  {model!r} not in catalog; the chat call may 404.")
    except urllib.error.HTTPError as e:
        print(f"  FAIL  HTTP {e.code}: {e.read().decode()[:300]}")
        if e.code in (401, 403):
            print("  -> Token is valid but lacks the 'Make calls to Inference")
            print("     Providers' permission. Regenerate it as a fine-grained")
            print("     token with that box checked.")
        return 1
    except Exception as e:
        print(f"  FAIL  network/other: {e}")
        return 1

    # ── Layer 3: live chat completion ─────────────────────────────────
    print(f"\n[3/3] POST /v1/chat/completions  model={model}")
    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Write a haiku about open-source models."}
        ],
        "max_tokens": 100,
    }
    try:
        _, out = _post(f"{ROUTER}/chat/completions", token, body)
        content = out["choices"][0]["message"]["content"]
        print("  PASS  model responded:\n")
        for line in content.strip().splitlines():
            print(f"    {line}")
        usage = out.get("usage", {})
        if usage:
            print(f"\n  tokens: {usage}")
        print("\nALL GREEN — HF Inference Providers is working end to end.")
        return 0
    except urllib.error.HTTPError as e:
        print(f"  FAIL  HTTP {e.code}: {e.read().decode()[:400]}")
        if e.code == 404:
            print(f"  -> Model {model!r} not served. Pick one from the [2/3] list,")
            print("     e.g. python3 scripts/hf_smoke_test.py <token> <model-id>")
        return 1
    except Exception as e:
        print(f"  FAIL  network/other: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
