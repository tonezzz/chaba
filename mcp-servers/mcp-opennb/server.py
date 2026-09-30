#!/usr/bin/env python3
"""mcp-opennb — FastMCP wrapper for Open Notebook's /api/search/ask.

Lets MCP clients (OpenClaw, Devin) ask the Chaba KB corpus held in Open
Notebook on idc01. Auth: Bearer <OPEN_NOTEBOOK_PASSWORD> from ONB_PASSWORD
env or an env file (ONB_ENV, default ~/.config/secrets/opennb-mcp.env —
the file may contain either ONB_PASSWORD= or OPEN_NOTEBOOK_PASSWORD=).

Config env:
  ONB_URL    — base URL (default https://idc01.taila0626a.ts.net:8445)
  ONB_MODEL  — override final-answer model id/name (default: server choice)
"""
import json
import os
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-opennb")

ONB_URL = os.environ.get("ONB_URL", "https://idc01.taila0626a.ts.net:8445").rstrip("/")
ONB_MODEL = os.environ.get("ONB_MODEL", "")
ONB_ENV = Path(os.environ.get("ONB_ENV", Path.home() / ".config/secrets/opennb-mcp.env")).expanduser()


def _password() -> str:
    pw = os.environ.get("ONB_PASSWORD")
    if pw:
        return pw
    if ONB_ENV.exists():
        for line in ONB_ENV.read_text().splitlines():
            for key in ("ONB_PASSWORD=", "OPEN_NOTEBOOK_PASSWORD="):
                if line.startswith(key):
                    return line.split("=", 1)[1].strip()
    raise RuntimeError(f"no ONB password — set ONB_PASSWORD or OPEN_NOTEBOOK_PASSWORD in {ONB_ENV}")


def _models() -> list[dict]:
    req = urllib.request.Request(
        f"{ONB_URL}/api/models?type=language",
        headers={"Authorization": f"Bearer {_password()}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _default_model_id() -> str:
    if ONB_MODEL:
        for m in _models():
            if m.get("id") == ONB_MODEL or m.get("name") == ONB_MODEL:
                return m["id"]
        return ONB_MODEL  # treat as raw id
    models = _models()
    for m in models:
        if "gemini-2.5-flash" in str(m.get("name", "")):
            return m["id"]
    return models[0]["id"]


def _sse_ask(question: str, model_id: str, timeout: int = 300) -> tuple[str, list]:
    body = {
        "question": question,
        "strategy_model": model_id,
        "answer_model": model_id,
        "final_answer_model": model_id,
    }
    req = urllib.request.Request(
        f"{ONB_URL}/api/search/ask",
        method="POST",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_password()}", "Content-Type": "application/json"},
    )
    answer, searches, sources = None, [], []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            try:
                evt = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            t = evt.get("type")
            if t == "strategy":
                searches = [s.get("term") for s in evt.get("searches", [])]
            elif t in ("final_answer", "complete"):
                answer = evt.get("final_answer") or evt.get("content") or answer
                sources = evt.get("sources") or evt.get("references") or sources
            elif t == "error":
                raise RuntimeError(str(evt.get("message", "ask error"))[:300])
    return answer or "", searches, sources


@mcp.tool()
def opennb_ask(question: str) -> str:
    """Ask Tony's Chaba knowledge base a question — infra runbooks, HA setup,
    host/service details, Ada internals. Returns the answer plus source refs."""
    answer, searches, sources = _sse_ask(question, _default_model_id())
    if not answer:
        return "Open Notebook returned no final answer (provider error or empty result)."
    out = answer
    if searches:
        out += f"\n\n[searches: {', '.join(s for s in searches if s)}]"
    if sources:
        out += f"\n[sources: {', '.join(str(s) for s in sources[:6])}]"
    return out


@mcp.tool()
def opennb_health() -> str:
    """Check Open Notebook API reachability and configured language models."""
    try:
        models = _models()
        names = [m.get("name") or m.get("id") for m in models]
        return f"ok — {ONB_URL} reachable; {len(models)} language models: {', '.join(names[:8])}"
    except Exception as exc:
        return f"fail — {exc}"


if __name__ == "__main__":
    mcp.run()
