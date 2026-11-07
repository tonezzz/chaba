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
  base_url_override  per-call gateway override for services that must not
                     change the process-wide GEMINI_BASE_URL.

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


def endpoint(model: str, base_url_override: str | None = None) -> str:
    base = (base_url_override or base_url()).rstrip("/")
    if not base.endswith("/v1beta"):
        base += "/v1beta"
    return f"{base}/models/{model}:generateContent"


def _litellm_headers(base: str, tags, metadata) -> dict:
    """x-litellm-tags / x-litellm-metadata headers for gateway calls —
    how SpendLogs rows get lane/tool/job attribution (same header
    contract ada gemini_pool uses). Direct Google calls never see them."""
    if base.rstrip("/").startswith(DIRECT_BASE):
        return {}
    h = {}
    if tags:
        h["x-litellm-tags"] = (tags if isinstance(tags, str)
                               else ",".join(str(t) for t in tags))
    if metadata:
        h["x-litellm-metadata"] = json.dumps(metadata)
    return h


def generate(prompt: str, model: str, *, key: str | None = None,
             generation_config: dict | None = None,
             timeout: int = 120, label: str = "gemini",
             base_url_override: str | None = None,
             max_attempts: int = 4,
             tags: str | list | None = None,
             litellm_metadata: dict | None = None) -> str | None:
    """One generateContent call -> text or None. Retries 429/5xx with
    linear backoff; other HTTP errors fail fast with a printed reason.

    tags/litellm_metadata only take effect against a LiteLLM gateway
    base (env GEMINI_BASE_URL or base_url_override) — e.g.
    tags="service=news-digest,job=wp-news-digest,route=brief_th"."""
    key = (key or os.environ.get("GEMINI_API_KEY")
           or os.environ.get("GOOGLE_API_KEY"))
    if not key:
        print("GEMINI_API_KEY not set — cannot call model")
        return None
    body: dict = {"contents": [{"parts": [{"text": prompt}]}]}
    if generation_config:
        body["generationConfig"] = generation_config
    data = json.dumps(body).encode()
    base = (base_url_override or base_url()).rstrip("/")
    headers = {"Content-Type": "application/json", "x-goog-api-key": key,
               **_litellm_headers(base, tags, litellm_metadata)}
    for attempt in range(max_attempts):
        try:
            req = urllib.request.Request(
                endpoint(model, base_url_override), data=data,
                headers=headers)
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
                  timeout: int = 120, **kw) -> dict | None:
    """JSON-mode variant — asks for application/json and parses the
    reply. Raises ValueError on unparseable output (same failure surface
    as the callers this replaces). Extra kwargs (tags,
    litellm_metadata, ...) forward to generate()."""
    text = generate(
        prompt, model, key=key, timeout=timeout, **kw,
        generation_config={"response_mime_type": "application/json",
                           "temperature": 0.2})
    if text is None:
        return None
    return json.loads(text)
