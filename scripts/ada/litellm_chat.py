#!/usr/bin/env python3
"""Shared OpenAI-style chat caller for the chaba batch chain's local/free
lane (card chat-local-free-lane).

The LiteLLM gateway on idc03 owns routing: callers ask for a job-class
alias (default `chat-local` -> qwen2.5:7b-instruct on idc02 ollama, with
ollama-llama3.2 / colab-gemma3 fallbacks) and the gateway picks the
upstream. Anything here is free/local — good for EN summarize/classify
work; Thai-facing output stays on gemini (gemini_rest.py).

Credentials resolve in order:
  1. LITELLM_URL + LITELLM_KEY env
  2. ~/.config/secrets/mddb-gemini.env (same file news-digest embeds via)
  3. LITELLM_ENV_FILE env -> path to a KEY=VALUE file

All functions return None on any failure — callers keep a non-LLM
fallback path, matching the nest's "AI narrates, program ranks" posture.

Routing table / budgets: docs/ssot/infrastructure/ssot.llm-gateway.yml.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

DEFAULT_MODEL = "chat-local"
DEFAULT_ENV_FILE = os.path.expanduser("~/.config/secrets/mddb-gemini.env")


def _load_env_file(path):
    env = {}
    try:
        for line in open(path):
            m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def gateway(env_file: str | None = None) -> tuple[str | None, str | None]:
    """(base_url, key) for the gateway — env first, secrets file second."""
    url = os.environ.get("LITELLM_URL")
    key = os.environ.get("LITELLM_KEY")
    if url and key:
        return url.rstrip("/"), key
    env = _load_env_file(env_file or os.environ.get("LITELLM_ENV_FILE")
                         or DEFAULT_ENV_FILE)
    return (url or env.get("LITELLM_URL", "")).rstrip("/") or None, \
        key or env.get("LITELLM_KEY")


def chat(prompt: str | None = None, *, messages: list | None = None,
         model: str = DEFAULT_MODEL, temperature: float = 0.2,
         max_tokens: int = 1024, timeout: int = 90,
         url: str | None = None, key: str | None = None,
         env_file: str | None = None, label: str = "litellm",
         tags: str | list | None = None,
         litellm_metadata: dict | None = None) -> str | None:
    """One /chat/completions call -> assistant text or None.

    tags/litellm_metadata stamp SpendLogs rows via the proxy's
    x-litellm-* headers (same contract ada gemini_pool uses) — e.g.
    tags="service=news-digest,job=wp-news-digest,route=en_synth"."""
    if messages is None:
        messages = [{"role": "user", "content": prompt or ""}]
    if not (url and key):
        url, key = gateway(env_file)
    if not (url and key):
        print(f"{label}: LITELLM_URL/LITELLM_KEY unresolved — skipped",
              file=sys.stderr)
        return None
    data = json.dumps({"model": model, "messages": messages,
                       "temperature": temperature,
                       "max_tokens": max_tokens}).encode()
    headers = {"Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    if tags:
        headers["x-litellm-tags"] = (
            tags if isinstance(tags, str)
            else ",".join(str(t) for t in tags))
    if litellm_metadata:
        headers["x-litellm-metadata"] = json.dumps(litellm_metadata)
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/chat/completions", data=data,
            headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        return (d["choices"][0]["message"].get("content") or "").strip() or None
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read()[:200].decode("utf-8", "replace")
        except Exception:
            pass
        print(f"{label} HTTP {exc.code}: {detail}", file=sys.stderr)
    except Exception as exc:
        print(f"{label} failed: {exc}", file=sys.stderr)
    return None


def chat_json(prompt: str, **kw) -> dict | None:
    """chat() + best-effort JSON object extraction — code fences and
    surrounding prose stripped; None when nothing parses."""
    text = chat(prompt, **kw)
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None
