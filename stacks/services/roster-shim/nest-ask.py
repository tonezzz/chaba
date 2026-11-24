#!/usr/bin/env python3
"""nest-ask — chat entry for the roster 'nest' lane (card
roster-devin-nest-shims).

Fronts the Nest orchestrator for the roster-shim exec backend. Resolution
order:

  1. NEST_ORCHESTRATOR_URL — POST {"text": ...} JSON; the reply is read
     from reply_text|text|reply|response (first string found). Point this
     at the real orchestrator chat entry when one exists — the shim and
     roster contact need no change.
  2. LiteLLM `chat-local` lane (qwen2.5:7b on idc02 ollama) with the Nest
     persona — the free/local fallback, same credentials file
     litellm_chat.py uses (~/.config/secrets/mddb-gemini.env).

Prints the reply text to stdout; roster-shim streams it back over the
lane ws as assistant_transcript_delta frames. Nonzero exit + stderr
message becomes the shim's error reply.

Env:
    NEST_ORCHESTRATOR_URL   orchestrator chat endpoint (optional)
    NEST_ORCHESTRATOR_KEY   bearer token for it (optional)
    LITELLM_URL / LITELLM_KEY   gateway override (else secrets file)
    LITELLM_ENV_FILE        secrets file path override
    NEST_ASK_MODEL          litellm model alias (default chat-local)
    NEST_ASK_TIMEOUT        seconds (default 90)
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

SYSTEM = (
    "You are Nest — the Chaba orchestrator persona on the Agents roster. "
    "You speak for the Nest: the fleet of lanes, dispatches, nest workers "
    "and the kanban board that coordinates them. Answer concisely in "
    "plain text. You cannot run tools from this chat; for live state "
    "point the user at the chaba-nest dashboard or board."
)

REPLY_KEYS = ("reply_text", "text", "reply", "response", "answer", "content")


def _env_file(path: str) -> dict:
    env = {}
    try:
        for line in open(os.path.expanduser(path)):
            m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _post_json(url: str, payload: dict, timeout: float,
               headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _orchestrator(text: str) -> str | None:
    url = os.environ.get("NEST_ORCHESTRATOR_URL", "").strip()
    if not url:
        return None
    headers = {}
    key = os.environ.get("NEST_ORCHESTRATOR_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = _post_json(url, {"text": text, "lane": "nest"},
                      float(os.environ.get("NEST_ASK_TIMEOUT", "90")),
                      headers)
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for k in REPLY_KEYS:
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v
        # last resort: stringify a small dict
        if len(json.dumps(data)) < 2000:
            return json.dumps(data, ensure_ascii=False)
    return None


def _litellm(text: str) -> str:
    env = _env_file(os.environ.get(
        "LITELLM_ENV_FILE",
        os.path.expanduser("~/.config/secrets/mddb-gemini.env")))
    base = (os.environ.get("LITELLM_URL") or env.get("LITELLM_URL", "")
            ).rstrip("/")
    key = os.environ.get("LITELLM_KEY") or env.get("LITELLM_KEY")
    if not base or not key:
        raise SystemExit(
            "nest-ask: no LITELLM_URL/KEY and none in secrets file; "
            "set NEST_ORCHESTRATOR_URL to front a real chat entry")
    model = os.environ.get("NEST_ASK_MODEL", "chat-local")
    timeout = float(os.environ.get("NEST_ASK_TIMEOUT", "90"))
    data = _post_json(
        f"{base}/chat/completions",
        {"model": model, "temperature": 0.3, "max_tokens": 600,
         "messages": [{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": text}]},
        timeout, {"Authorization": f"Bearer {key}"})
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise SystemExit(f"nest-ask: unexpected litellm reply: "
                         f"{str(data)[:300]}")


def main() -> int:
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        print("usage: nest-ask.py <text>", file=sys.stderr)
        return 2
    try:
        reply = _orchestrator(text)
        if reply is None:
            reply = _litellm(text)
    except SystemExit:
        raise
    except Exception as e:
        print(f"nest-ask: {e}", file=sys.stderr)
        return 1
    if not reply:
        print("nest-ask: empty reply", file=sys.stderr)
        return 1
    print(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
