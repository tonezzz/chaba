#!/usr/bin/env python3
"""mcp-llama — FastMCP wrapper for llama.cpp server.

Runs over stdio by default for local IDE integration (e.g. Windsurf/Cascade).
It calls the OpenAI-compatible HTTP API exposed by llama-server.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-llama")

LLAMA_URL = os.environ.get("LLAMA_URL", "http://localhost:8008")
MODEL_DIR = Path(
    os.environ.get(
        "LLAMA_MODEL_DIR",
        Path(__file__).resolve().parents[2] / "data" / "models",
    )
).expanduser()


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{LLAMA_URL.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str) -> dict[str, Any]:
    url = f"{LLAMA_URL.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


@mcp.tool()
def chat(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
) -> str:
    """Chat with the loaded model."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = _post(
        "/v1/chat/completions",
        {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    return resp["choices"][0]["message"]["content"]


@mcp.tool()
def complete(
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.7,
) -> str:
    """Run a raw text completion with the loaded model."""
    resp = _post(
        "/v1/completions",
        {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "n": 1,
        },
    )
    return resp["choices"][0]["text"]


@mcp.tool()
def tokenize(text: str) -> str:
    """Return token IDs for the given text."""
    resp = _post("/tokenize", {"content": text})
    tokens = resp.get("tokens", [])
    return json.dumps({"count": len(tokens), "tokens": tokens})


@mcp.tool()
def models() -> str:
    """List available .gguf model files in the model directory."""
    if not MODEL_DIR.exists():
        return json.dumps(
            {"error": "model directory not found", "path": str(MODEL_DIR)}
        )
    files = sorted(f.name for f in MODEL_DIR.iterdir() if f.suffix == ".gguf")
    return json.dumps({"model_dir": str(MODEL_DIR), "models": files})


@mcp.tool()
def status() -> str:
    """Return llama-server /health or an error if unreachable."""
    try:
        return json.dumps(_get("/health"))
    except Exception as exc:
        return json.dumps({"error": str(exc), "llama_url": LLAMA_URL})


if __name__ == "__main__":
    mcp.run(transport="stdio")
