#!/usr/bin/env python3
"""mcp-llama — FastMCP wrapper for local LLM inference.

Supports both the llama.cpp server OpenAI-compatible API and the Ollama API,
auto-detecting which one is running at LLAMA_URL.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-llama")

LLAMA_URL = os.environ.get("LLAMA_URL", "http://localhost:8008").rstrip("/")
MODEL_DIR = Path(
    os.environ.get(
        "LLAMA_MODEL_DIR",
        Path(__file__).resolve().parents[2] / "data" / "models",
    )
).expanduser()

DEFAULT_OLLAMA_MODEL = os.environ.get("LLAMA_OLLAMA_MODEL", "phi3-gguf:latest")


def _request(path: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout: int = 120) -> tuple[int, dict[str, Any] | str]:
    """Make an HTTP request and return (status, parsed_body_or_text)."""
    url = f"{LLAMA_URL}{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except Exception as exc:
        return 0, str(exc)


def _is_ollama() -> bool:
    """Probe Ollama's tags endpoint to decide whether to use the Ollama API."""
    status, body = _request("/api/tags", timeout=5)
    if status == 200 and isinstance(body, dict) and "models" in body:
        return True
    return False


OLLAMA_MODE = _is_ollama()


def _ollama_model(model: str | None) -> str:
    if model:
        return model
    status, body = _request("/api/tags", timeout=5)
    if status == 200 and isinstance(body, dict) and body.get("models"):
        names = [m["name"] for m in body["models"] if "embed" not in m.get("name", "")]
        if names:
            return names[0]
    return DEFAULT_OLLAMA_MODEL


@mcp.tool()
def chat(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
    model: str | None = None,
) -> str:
    """Chat with the loaded model."""
    if OLLAMA_MODE:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": _ollama_model(model),
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        status, body = _request("/api/chat", method="POST", payload=payload)
        if status != 200:
            return json.dumps({"error": f"Ollama chat failed (HTTP {status})", "body": body, "llama_url": LLAMA_URL})
        return body["message"]["content"]

    # llama.cpp server (OpenAI-compatible)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    status, body = _request(
        "/v1/chat/completions",
        method="POST",
        payload={
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    if status != 200:
        return json.dumps({"error": f"llama.cpp chat failed (HTTP {status})", "body": body, "llama_url": LLAMA_URL})
    return body["choices"][0]["message"]["content"]


@mcp.tool()
def complete(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.7,
    model: str | None = None,
) -> str:
    """Run a raw text completion with the loaded model."""
    if OLLAMA_MODE:
        payload = {
            "model": _ollama_model(model),
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        status, body = _request("/api/generate", method="POST", payload=payload)
        if status != 200:
            return json.dumps({"error": f"Ollama generate failed (HTTP {status})", "body": body, "llama_url": LLAMA_URL})
        return body["response"]

    status, body = _request(
        "/v1/completions",
        method="POST",
        payload={
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "n": 1,
        },
    )
    if status != 200:
        return json.dumps({"error": f"llama.cpp completion failed (HTTP {status})", "body": body, "llama_url": LLAMA_URL})
    return body["choices"][0]["text"]


@mcp.tool()
def tokenize(text: str) -> str:
    """Return tokenization info for the given text."""
    if OLLAMA_MODE:
        return json.dumps({
            "note": "Ollama does not expose a tokenize endpoint",
            "text_characters": len(text),
            "llama_url": LLAMA_URL,
        })

    status, body = _request("/tokenize", method="POST", payload={"content": text})
    if status != 200:
        return json.dumps({"error": f"tokenize failed (HTTP {status})", "body": body, "llama_url": LLAMA_URL})
    tokens = body.get("tokens", [])
    return json.dumps({"count": len(tokens), "tokens": tokens})


@mcp.tool()
def models() -> str:
    """List available .gguf model files or Ollama models."""
    if OLLAMA_MODE:
        status, body = _request("/api/tags", timeout=10)
        if status != 200:
            return json.dumps({"error": f"Ollama /api/tags failed (HTTP {status})", "body": body, "llama_url": LLAMA_URL})
        return json.dumps({
            "source": "ollama",
            "llama_url": LLAMA_URL,
            "models": [m["name"] for m in body.get("models", [])],
        })

    if not MODEL_DIR.exists():
        return json.dumps(
            {"error": "model directory not found", "path": str(MODEL_DIR)}
        )
    files = sorted(f.name for f in MODEL_DIR.iterdir() if f.suffix == ".gguf")
    return json.dumps({"model_dir": str(MODEL_DIR), "models": files})


@mcp.tool()
def status() -> str:
    """Return LLM server health/status."""
    if OLLAMA_MODE:
        status, body = _request("/api/tags", timeout=10)
        if status != 200:
            return json.dumps({"error": f"Ollama /api/tags returned HTTP {status}", "body": body, "llama_url": LLAMA_URL})
        return json.dumps({
            "ok": True,
            "mode": "ollama",
            "llama_url": LLAMA_URL,
            "models": [m["name"] for m in body.get("models", [])],
        })

    status, body = _request("/health", timeout=10)
    if status != 200:
        return json.dumps({"error": f"llama.cpp /health returned HTTP {status}", "body": body, "llama_url": LLAMA_URL})
    return json.dumps({"ok": True, "mode": "llama.cpp", "llama_url": LLAMA_URL, "health": body})


if __name__ == "__main__":
    mcp.run(transport="stdio")
