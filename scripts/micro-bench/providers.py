"""Provider calls for micro-bench — one chat() entry point per cfg.

Providers:
  openai_compat  POST {base_url}/chat/completions (ollama /v1, llama.cpp,
                 vllm — anything OpenAI-shaped). Returns usage tokens.
  gemini         POST generativelanguage/v1beta/{model}:generateContent.
                 Key from GEMINI_API_KEY or ~/.config/secrets/gemini-api-key.env.
  mock           offline echo — exercises the pipeline with no services
                 (used by the dry-run-dummy variant; --dry-run doesn't
                 need it, it skips providers entirely).

Each chat(cfg, messages, timeout) returns
  {text, prompt_tokens, completion_tokens, ms}
or raises. Callers translate errors into fixture status=error.
"""
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

GEMINI_KEY_FILE = Path.home() / ".config" / "secrets" / "gemini-api-key.env"


def _gemini_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    if GEMINI_KEY_FILE.exists():
        for line in GEMINI_KEY_FILE.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _post(url, payload, timeout, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def chat(cfg, messages, timeout=60):
    """cfg = {provider, model, base_url?} — returns {text, usage, ms}."""
    provider = cfg.get("provider")
    start = time.monotonic()

    if provider == "mock":
        last = messages[-1]["content"] if messages else ""
        return {"text": f'{{"answer": "mock: {last[:40]}"}}',
                "prompt_tokens": 0, "completion_tokens": 0,
                "ms": round((time.monotonic() - start) * 1000)}

    if provider == "ssh_cmd":
        # Remote model runner: cfg.cmd is a shell command that reads the
        # user text on stdin and writes the reply on stdout (e.g.
        # "ssh idc03 /tmp/t5-correct.py"). No token usage from an opaque
        # pipe — polish_tokens stays null, downstream still counts.
        last = messages[-1]["content"] if messages else ""
        r = subprocess.run(cfg["cmd"], shell=True, input=last,
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"ssh_cmd rc={r.returncode}: "
                               f"{r.stderr.strip()[:200]}")
        return {"text": r.stdout.strip(),
                "prompt_tokens": None, "completion_tokens": None,
                "ms": round((time.monotonic() - start) * 1000)}

    if provider == "openai_compat":
        body = _post(
            cfg["base_url"].rstrip("/") + "/chat/completions",
            {"model": cfg["model"], "messages": messages,
             "temperature": 0, "stream": False},
            timeout)
        msg = body["choices"][0]["message"]
        # llama.cpp may put reasoning in reasoning_content; content wins
        text = msg.get("content") or msg.get("reasoning_content") or ""
        usage = body.get("usage") or {}
        return {
            "text": text,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "ms": round((time.monotonic() - start) * 1000),
        }

    if provider == "gemini":
        key = _gemini_key()
        if not key:
            raise RuntimeError("gemini provider: no GEMINI_API_KEY "
                               "(env or ~/.config/secrets/gemini-api-key.env)")
        sys_parts = [{"text": m["content"]} for m in messages
                     if m["role"] == "system"]
        user_parts = [{"text": m["content"]} for m in messages
                      if m["role"] == "user"]
        body = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{cfg['model']}:generateContent?key={key}",
            {"system_instruction": {"parts": sys_parts} if sys_parts else None,
             "contents": [{"role": "user", "parts": user_parts}],
             "generationConfig": {"temperature": 0}},
            timeout)
        cand = (body.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "")
                       for p in (cand.get("content") or {}).get("parts", []))
        usage = body.get("usageMetadata") or {}
        return {
            "text": text,
            "prompt_tokens": usage.get("promptTokenCount"),
            "completion_tokens": usage.get("candidatesTokenCount"),
            "ms": round((time.monotonic() - start) * 1000),
        }

    raise RuntimeError(f"unknown provider {provider!r}")
