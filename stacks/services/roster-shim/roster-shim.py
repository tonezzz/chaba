#!/usr/bin/env python3
"""roster-shim — ada-lane ws contract shim for roster agents (card
roster-devin-nest-shims).

The Agents roster page (stacks/web/public/apps/roster) fronts every
contact with a stock <ada-webchat-card>, which speaks the ada lane ws
contract:

    ws(s)://<lane>/ws?api_key=<key>&channel=web&chat_id=web-<member>
        &mode=text&device_id=<id>
    <- {"type":"ready"}
    -> {"type":"history_request","max_turns":N}   (first ready only)
    <- {"type":"history","turns":[{role,text,ts}]}
    -> {"type":"text","text":"..."}
    <- {"type":"response_started"}
    <- {"type":"assistant_transcript_delta","text":"..."}  (xN)
    <- {"type":"response_completed"}

Agents that have no ada-voice lane (devin CLI, the nest orchestrator)
get a shim lane instead: this daemon terminates the ws contract and
forwards each text turn to a configured backend — `exec` (argv template,
stdout streams out as deltas) or `http` (POST JSON, reply text extracted
from the response). Lanes are selected by the first path segment:
/<lane>/ws, so one port serves every shimmed agent.

Auth mirrors the ada lanes: api_key must match a configured key
(global `keys:` or per-lane `keys:`, plus $ROSTER_SHIM_KEYS) or the
socket closes 4401 — the roster probe/card already render that as
"key denied". Keys are secrets: ship them via
~/.config/secrets/roster-shim.env (EnvironmentFile), not lanes.yml.

History: every completed turn appends to
<state_dir>/history/<lane>/<chat_id>.jsonl and history_request replays
the tail — threads survive reloads like the real lanes.

Usage:
    roster-shim.py --serve            daemon (service entry point)
    roster-shim.py --selftest         in-process contract check, no ws
    roster-shim.py --lanes FILE       alternate lanes.yml

Env:
    ROSTER_SHIM_LANES    lanes.yml path (default: beside this script)
    ROSTER_SHIM_BIND     listen addr (default 127.0.0.1)
    ROSTER_SHIM_PORT     listen port (default 8796)
    ROSTER_SHIM_STATE    state dir (default ~/.local/share/roster-shim)
    ROSTER_SHIM_KEYS     comma-separated extra allowed api_keys
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - install.sh pins pyyaml
    yaml = None

import websockets
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response as WsResponse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2] if len(HERE.parents) > 2 else HERE.parent

BIND = os.environ.get("ROSTER_SHIM_BIND", "127.0.0.1")
PORT = int(os.environ.get("ROSTER_SHIM_PORT", "8796"))
STATE_DIR = Path(os.environ.get(
    "ROSTER_SHIM_STATE",
    os.path.expanduser("~/.local/share/roster-shim")))
LANES_FILE = Path(os.environ.get(
    "ROSTER_SHIM_LANES", str(HERE / "lanes.yml")))

WS_PATH_RE = re.compile(r"^/([a-z0-9][a-z0-9-]*)/ws/?$")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# Reply extraction for http backends, in priority order.
REPLY_PATHS = ("reply_text", "text", "reply", "response", "answer", "content")


# ---------------------------------------------------------------- config

def _expand_env(value):
    """Expand $VAR / ${VAR} inside string scalars (config templating)."""
    if isinstance(value, str):
        return _sub_env(value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def _sub_env(s: str) -> str:
    import re as _re
    return _re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)",
                   lambda m: os.environ.get(m.group(1) or m.group(2), m.group(0)),
                   s)


def _sub_tmpl(arg: str, fields: dict) -> str:
    "'{key}' placeholder substitution for argv templates."""
    def rep(m):
        k = m.group(1)
        if k not in fields:
            raise KeyError(f"unknown template field {{{k}}}")
        return str(fields[k])
    return re.sub(r"\{([a-z_]+)\}", rep, arg)


def load_config(path: Path | None = None) -> dict:
    path = path or LANES_FILE
    if yaml is None:
        raise SystemExit("PyYAML required — install.sh creates the venv")
    if not path.exists():
        raise SystemExit(f"lanes config not found: {path}")
    cfg = yaml.safe_load(path.read_text()) or {}
    cfg = _expand_env(cfg)
    cfg.setdefault("bind", BIND)
    cfg.setdefault("port", PORT)
    cfg.setdefault("state_dir", str(STATE_DIR))
    cfg.setdefault("lanes", {})
    env_keys = [k.strip() for k in
                os.environ.get("ROSTER_SHIM_KEYS", "").split(",") if k.strip()]
    cfg["_env_keys"] = env_keys
    return cfg


def allowed_keys(cfg: dict, lane: str) -> set:
    keys = set(cfg.get("keys") or [])
    keys |= set((cfg["lanes"].get(lane) or {}).get("keys") or [])
    keys |= set(cfg.get("_env_keys") or [])
    return keys


# ------------------------------------------------------------- backends

class ExecBackend:
    """argv template per turn; stdout streams out as deltas.

    Spec keys: argv (every turn), first (used until <workspace>/.started
    exists — e.g. `devin -p` before `devin -c -p`), cwd_template,
    timeout_s, env.
    """

    def __init__(self, spec: dict, lane: str, cfg: dict):
        self.spec = spec
        self.lane = lane
        self.cfg = cfg
        self.timeout = float(spec.get("timeout_s", 600))

    def _fields(self, chat_id: str, ws_dir: Path) -> dict:
        return {
            "text": "",  # filled by caller
            "chat_id": chat_id,
            "lane": self.lane,
            "state_dir": str(self.cfg.get("state_dir", STATE_DIR)),
            "repo": str(REPO),
            "here": str(HERE),
            "workspace": str(ws_dir),
        }

    async def run(self, text: str, chat_id: str,
                  emit) -> tuple[str, bool]:
        cwd_tpl = self.spec.get(
            "cwd_template", "{state_dir}/workspaces/{lane}/{chat_id}")
        ws_dir = Path(os.path.expanduser(
            _sub_tmpl(cwd_tpl, self._fields(chat_id, Path("/")))))
        ws_dir.mkdir(parents=True, exist_ok=True)
        marker = ws_dir / ".started"
        tpl_key = "argv" if marker.exists() or "first" not in self.spec \
            else "first"
        argv_tpl = self.spec.get(tpl_key) or self.spec.get("argv")
        if not argv_tpl:
            return "backend error: no argv configured", False
        fields = self._fields(chat_id, ws_dir)
        fields["text"] = text
        argv = [_sub_tmpl(str(a), fields) for a in argv_tpl]
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in
                    (self.spec.get("env") or {}).items()})
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(ws_dir), env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        out_parts: list[str] = []
        err_parts: list[str] = []

        async def pump(stream, sink, is_err=False):
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    return
                s = chunk.decode("utf-8", "replace")
                sink.append(s)
                if not is_err:
                    await emit(s)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    pump(proc.stdout, out_parts, False),
                    pump(proc.stderr, err_parts, True),
                    proc.wait()),
                timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return (f"backend timed out after {self.timeout:.0f}s "
                    f"(argv: {argv[0]})"), False
        text_out = "".join(out_parts).strip()
        err = "".join(err_parts).strip()
        if proc.returncode != 0:
            detail = err.splitlines()[-1] if err else f"rc={proc.returncode}"
            return f"backend failed ({argv[0]}): {detail[:400]}", False
        if tpl_key == "first":
            marker.touch()
        if not text_out:
            return (err.splitlines()[-1] if err else
                    "backend returned no output"), False
        return text_out, True


class HttpBackend:
    """POST {text, chat_id, lane} JSON to url; extract reply text."""

    def __init__(self, spec: dict, lane: str, cfg: dict):
        self.url = spec["url"]
        self.timeout = float(spec.get("timeout_s", 120))
        self.reply_path = spec.get("reply_path")
        self.lane = lane

    async def run(self, text: str, chat_id: str,
                  emit) -> tuple[str, bool]:
        payload = json.dumps({
            "text": text, "chat_id": chat_id, "lane": self.lane,
            "member": "web"}).encode()
        req = urllib.request.Request(
            self.url, data=payload,
            headers={"Content-Type": "application/json"})

        def _fetch():
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())

        try:
            data = await asyncio.to_thread(_fetch)
        except Exception as e:
            return f"backend http error: {e}", False
        reply = self._extract(data)
        if reply is None:
            return f"backend returned no reply text: {str(data)[:300]}", False
        # Stream the reply in card-sized bites so the bubble types out.
        for i in range(0, len(reply), 120):
            await emit(reply[i:i + 120])
            await asyncio.sleep(0.02)
        return reply, True

    def _extract(self, data):
        if isinstance(data, str):
            return data
        if not isinstance(data, dict):
            return None
        if self.reply_path:
            node = data
            for part in self.reply_path.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            return node if isinstance(node, str) else None
        for key in REPLY_PATHS:
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v
        return None


def make_backend(spec: dict, lane: str, cfg: dict):
    t = (spec or {}).get("type", "exec")
    if t == "exec":
        return ExecBackend(spec, lane, cfg)
    if t == "http":
        return HttpBackend(spec, lane, cfg)
    raise ValueError(f"lane {lane}: unknown backend type {t!r}")


# --------------------------------------------------------------- history

def _safe_name(s: str) -> str:
    s = SAFE_NAME_RE.sub("_", s or "anon")
    return s[:80] or "anon"


def history_path(cfg: dict, lane: str, chat_id: str) -> Path:
    return (Path(cfg["state_dir"]) / "history" / _safe_name(lane)
            / f"{_safe_name(chat_id)}.jsonl")


def append_turn(cfg: dict, lane: str, chat_id: str,
                role: str, text: str):
    p = history_path(cfg, lane, chat_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"role": role, "text": text,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_history(cfg: dict, lane: str, chat_id: str,
                 max_turns: int) -> list:
    p = history_path(cfg, lane, chat_id)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-max_turns:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []


# ----------------------------------------------------------------- shim

class Shim:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.backends: dict[str, object] = {}
        self.locks: dict[tuple, asyncio.Lock] = {}
        for name, lane_cfg in (cfg.get("lanes") or {}).items():
            if not (lane_cfg or {}).get("enabled", True):
                continue
            self.backends[name] = make_backend(
                lane_cfg.get("backend") or {}, name, cfg)

    def lane_names(self):
        return sorted(self.backends)

    # -- ws plumbing -----------------------------------------------------

    async def process_request(self, connection, request):
        """Plain GET /<lane>/health -> 200 json (verify.sh probe)."""
        path = getattr(request, "path", "") or ""
        m = re.match(r"^/([a-z0-9][a-z0-9-]*)/health/?$", path.split("?")[0])
        if m and m.group(1) in self.backends:
            body = json.dumps({"ok": True, "lane": m.group(1),
                               "lanes": self.lane_names()}).encode()
            return WsResponse(
                200, "OK",
                Headers({"Content-Type": "application/json"}), body=body)
        return None  # let websockets handle the upgrade / reject

    async def handler(self, ws):
        req = getattr(ws, "request", None)
        path = (getattr(req, "path", "") or "") if req else ""
        qs = {}
        if "?" in path:
            path, query = path.split("?", 1)
            from urllib.parse import parse_qs
            qs = {k: v[0] for k, v in parse_qs(query).items()}
        m = WS_PATH_RE.match(path)
        lane = m.group(1) if m else None
        if lane not in self.backends:
            await ws.close(code=4404, reason="unknown lane")
            return
        key = qs.get("api_key", "")
        keys = allowed_keys(self.cfg, lane)
        if keys and key not in keys:
            await ws.close(code=4401, reason="bad api_key")
            return
        if not keys:
            # No keys configured at all — fail closed unless the operator
            # explicitly opens the lane for tailnet-only dev.
            if os.environ.get("ROSTER_SHIM_ALLOW_ANY") != "1":
                await ws.close(code=4403,
                               reason="no keys configured")
                return
        chat_id = qs.get("chat_id") or f"web-{qs.get('device_id', 'anon')}"
        await ws.send(json.dumps({"type": "ready"}))
        lock = self.locks.setdefault((lane, chat_id), asyncio.Lock())
        async for raw in ws:
            if not isinstance(raw, str):
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            t = msg.get("type")
            if t == "history_request":
                turns = read_history(self.cfg, lane, chat_id,
                                     int(msg.get("max_turns", 200)))
                await ws.send(json.dumps(
                    {"type": "history", "turns": turns}))
            elif t == "text":
                text = str(msg.get("text") or "").strip()
                if not text:
                    continue
                await self._turn(ws, lane, chat_id, text, lock)
            # other frame types (audio, interrupt, …) — text lane ignores

    async def _turn(self, ws, lane, chat_id, text, lock):
        append_turn(self.cfg, lane, chat_id, "user", text)
        backend = self.backends[lane]
        async with lock:
            await ws.send(json.dumps({"type": "response_started"}))
            buf: list[str] = []

            async def emit(delta: str):
                if delta:
                    buf.append(delta)
                    await ws.send(json.dumps({
                        "type": "assistant_transcript_delta",
                        "text": delta}))

            reply, ok = await backend.run(text, chat_id, emit)
        full = "".join(buf).strip() or reply.strip()
        append_turn(self.cfg, lane, chat_id, "assistant", full)
        await ws.send(json.dumps({"type": "response_completed"}))


async def amain():
    cfg = load_config()
    shim = Shim(cfg)
    if not shim.lane_names():
        raise SystemExit("no enabled lanes in config")
    async with serve(shim.handler, cfg["bind"], int(cfg["port"]),
                     process_request=shim.process_request):
        print(f"roster-shim on {cfg['bind']}:{cfg['port']} "
              f"lanes={','.join(shim.lane_names())}", flush=True)
        await asyncio.Future()  # run forever


def selftest():
    """Contract check without a socket: config load, templating, history."""
    cfg = load_config()
    shim = Shim(cfg)
    assert shim.lane_names(), "no lanes configured"
    for name in shim.lane_names():
        assert name in WS_PATH_RE.match(f"/{name}/ws").group(1)
    # history round-trip in a temp state dir
    cfg2 = dict(cfg)
    cfg2["state_dir"] = "/tmp/roster-shim-selftest"
    append_turn(cfg2, "selftest", "web-tony", "user", "hi")
    append_turn(cfg2, "selftest", "web-tony", "assistant", "hello")
    turns = read_history(cfg2, "selftest", "web-tony", 10)
    assert [t["role"] for t in turns] == ["user", "assistant"], turns
    # argv templating
    fields = {"text": "hello world", "chat_id": "web-tony",
              "lane": "devin", "state_dir": "/tmp/s", "repo": "/r",
              "workspace": "/tmp/s/w"}
    assert _sub_tmpl("devin -c -p {text}", fields) == \
        "devin -c -p hello world"
    print(f"selftest ok — lanes: {', '.join(shim.lane_names())}")
    return 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    if "--serve" in sys.argv or len(sys.argv) == 1:
        asyncio.run(amain())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
