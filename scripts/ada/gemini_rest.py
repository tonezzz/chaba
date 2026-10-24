#!/usr/bin/env python3
"""Shared Gemini generateContent caller for the chaba batch chain
(report/extract/distill scripts).

Default is a direct call to Google. Opting the whole chain onto the
LiteLLM gateway on idc03 is a pure env change — no code:

  GEMINI_BASE_URL  default https://generativelanguage.googleapis.com
                   set to the gateway base (http://100.102.134.91:4000)
                   or the routed path (.../v1beta) — both normalize the
                   same. Model-name aliases, ordered fallbacks, and the
                   per-key spend ledger then apply.
  GEMINI_API_KEY   Google AI key for direct calls; a LITELLM_KEY_*
                   virtual key (e.g. LITELLM_KEY_CHABA) when BASE_URL
                   points at the gateway.

Routing table / budgets: docs/ssot/infrastructure/ssot.llm-gateway.yml.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DIRECT_BASE = "https://generativelanguage.googleapis.com"


def base_url() -> str:
    return os.environ.get("GEMINI_BASE_URL", DIRECT_BASE).rstrip("/")


def via_gateway() -> bool:
    return not base_url().startswith(DIRECT_BASE)


def endpoint(model: str) -> str:
    base = base_url()
    if not base.endswith("/v1beta"):
        base += "/v1beta"
    return f"{base}/models/{model}:generateContent"


def generate(prompt: str, model: str, *, key: str | None = None,
             generation_config: dict | None = None,
             timeout: int = 120, label: str = "gemini",
             max_attempts: int = 4) -> str | None:
    """One generateContent call -> text or None. Retries 429/5xx with
    linear backoff; other HTTP errors fail fast with a printed reason."""
    key = (key or os.environ.get("GEMINI_API_KEY")
           or os.environ.get("GOOGLE_API_KEY"))
    if not key:
        print("GEMINI_API_KEY not set — cannot call model")
        return None
    body: dict = {"contents": [{"parts": [{"text": prompt}]}]}
    if generation_config:
        body["generationConfig"] = generation_config
    data = json.dumps(body).encode()
    for attempt in range(max_attempts):
        try:
            req = urllib.request.Request(
                endpoint(model), data=data,
                headers={"Content-Type": "application/json",
                         "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = json.loads(r.read())
            parts = (payload.get("candidates") or [{}])[0].get(
                "content", {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts).strip()
            return text or None
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                wait = 20 * (attempt + 1)
                print(f"  {label} {exc.code} — retrying in {wait}s")
                time.sleep(wait)
                continue
            detail = ""
            try:
                detail = exc.read()[:300].decode("utf-8", "replace")
            except Exception:
                pass
            print(f"  {label} call failed: HTTP {exc.code} {detail}")
            return None
        except (urllib.error.URLError, TimeoutError, OSError,
                ValueError) as exc:
            wait = 20 * (attempt + 1)
            print(f"  {label} call failed ({exc}) — retrying in {wait}s")
            time.sleep(wait)
    return None


def generate_json(prompt: str, model: str, *, key: str | None = None,
                  timeout: int = 120) -> dict | None:
    """JSON-mode variant — asks for application/json and parses the
    reply. Raises ValueError on unparseable output (same failure surface
    as the callers this replaces)."""
    text = generate(
        prompt, model, key=key, timeout=timeout,
        generation_config={"response_mime_type": "application/json",
                           "temperature": 0.2})
    if text is None:
        return None
    return json.loads(text)
