#!/usr/bin/env python3
"""board-api — write endpoint for the kanban board page.

Binds 127.0.0.1:8787 on tony-dell; Caddy proxies /apps/board-api/* here
(prefix stripped). Each request edits the card YAML in the *served*
checkout (chaba-tony-dell — the web container bind-mounts that tree),
then re-runs render-board.py so cards.json + index.html refresh
immediately. Git persistence is handled by kanban-commit.timer.

Endpoints (after prefix strip):
  GET  /health                       -> {"ok": true}
  GET  /cards                        -> cards.json payload
  POST /action   {id, do, column?, host?}   do: queue|close|hold|retry|claim|move
      close/move->done runs the merge guard (dispatch_repos.guard): a
      dispatch card whose session branch still has commits not in
      origin/<default_branch> gets a comms entry ('unmerged commits
      remain …') and stays in review instead of closing.
  POST /respond  {id, request_id, answer, from?, reopen?}
  POST /comment  {id, from, text}    from: devin|ada|chaba|tony
  POST /request  {id, ask, request_id?, options?, from?}
  POST /pipeline {id, opt_in?, pipeline?, stage?, status?, detail?, from?}
      CI pipeline write path (docs/ssot/ssot.ci.yml). opt_in:true sets the
      `pipeline: ci` opt-in; pipeline:{...} merges a full status block
      (stages deep-merged); stage+status records one stage result.

Writes are serialized with an flock so concurrent clicks don't race.
ALL card writes must go through this API — any direct card-YAML edit
outside it (scripts, dispatch rails, hand fixes) must hold LOCK
(/tmp/board-api.lock) first or it races the server.

Smoke test: python3 scripts/board/board-api.py --selftest
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_repos as dr

REPO = Path(__file__).resolve().parent.parent.parent
CARD_DIR = REPO / "docs/ssot/kanban/cards"
RENDER = REPO / "scripts/render-board.py"
LOCK = Path("/tmp/board-api.lock")
PORT = int(os.environ.get("BOARD_API_PORT", "8787"))
ACTORS = {"devin", "ada", "chaba", "tony"}
TRANSITIONS = {"queue", "close", "hold", "retry", "claim", "move"}
COLUMNS = {"backlog", "doing", "review", "done"}


def now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


def card_path(cid: str) -> Path:
    if not cid or "/" in cid or ".." in cid:
        raise ValueError("bad card id")
    p = CARD_DIR / f"{cid}.yml"
    if not p.exists():
        raise ValueError(f"no card {cid}")
    return p


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text()) or {}


def save(p: Path, card: dict) -> None:
    p.write_text(
        yaml.safe_dump(card, allow_unicode=True, sort_keys=False, width=110)
    )


def comms_add(card: dict, frm: str, text: str) -> None:
    card.setdefault("comms", []).append(
        {"at": now(), "from": frm, "text": text[:500]}
    )


def actor(body: dict, default: str = "tony") -> str:
    frm = str(body.get("from") or default).strip()
    if frm not in ACTORS:
        raise ValueError(f"from must be one of {sorted(ACTORS)}")
    return frm


def slugify(text: str) -> str:
    """Request id from free-text ask; the hash keeps non-ascii asks and
    near-identical slugs from colliding into false duplicates."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    h = hashlib.sha1(text.encode()).hexdigest()[:6]
    return f"{slug}-{h}" if slug else f"req-{h}"


def apply_merge_guard(card: dict) -> str:
    """review->done gate (card dispatch-merge-guard). Returns a block
    message when the session branch still has commits not in
    origin/<default_branch>; "" when the transition may proceed. Guard
    notes are appended to card comms either way; a guard error never
    wedges the board — it logs and allows."""
    try:
        g = dr.guard(card)
    except Exception as e:
        comms_add(card, "chaba", f"merge guard skipped (error: {e})")
        return ""
    if g["note"]:
        comms_add(card, "chaba", g["note"])
    return "" if g["allowed"] else f"blocked — {g['summary']}"


def do_action(card: dict, verb: str, frm: str) -> str:
    a = card.setdefault("action", {})
    st = a.get("status", "idle")
    if verb == "queue":
        if st in ("queued", "running"):
            return f"already {st}"
        a.setdefault("type", "dispatch")
        a["status"] = "queued"
        if card.get("column") in ("done", "review"):
            card["column"] = "backlog"
        comms_add(card, frm, "queued for processing")
        return "queued — kanban-dispatch will claim it"
    if verb == "retry":
        a["status"] = "queued"
        a.pop("result", None)
        comms_add(card, frm, "retry requested")
        return "re-queued"
    if verb == "close":
        blocked = apply_merge_guard(card)
        if blocked:
            return blocked
        card["column"] = "done"
        a["status"] = "done"
        comms_add(card, frm, "closed by Tony")
        return "moved to done"
    if verb == "hold":
        a["status"] = "idle"
        card["column"] = "backlog"
        comms_add(card, frm, "put on hold")
        return "back to backlog"
    raise ValueError(f"unknown verb {verb}")


def do_move(card: dict, body: dict) -> str:
    col = (body.get("column") or "").strip()
    if col not in COLUMNS:
        raise ValueError(f"column must be one of {sorted(COLUMNS)}")
    old = card.get("column", "backlog")
    if col == old:
        return f"already in {col}"
    if col == "done":
        blocked = apply_merge_guard(card)
        if blocked:
            return blocked
    card["column"] = col
    if col == "done":
        card.setdefault("action", {})["status"] = "done"
        card.setdefault("claim", {}).pop("session", None)
    comms_add(card, "tony", f"moved {old} -> {col}")
    return f"moved to {col}"


def do_claim(card: dict, body: dict) -> str:
    """Atomic first-wins claim for multi-host dispatch — runs under the
    request flock so two hosts can't both grab a queued card."""
    a = card.setdefault("action", {})
    if a.get("status") != "queued":
        raise ValueError(f"not claimable (status={a.get('status', 'idle')})")
    host = (body.get("host") or "").strip()
    if not host:
        raise ValueError("claim needs host")
    pinned = a.get("host")
    if pinned and pinned != host:
        raise ValueError(f"card is pinned to {pinned}")
    a["runner"] = host
    comms_add(card, host, "claimed")
    return "claimed"


def do_respond(card: dict, body: dict, frm: str) -> str:
    rid = str(body.get("request_id") or "").strip()
    answer = str(body.get("answer") or "").strip()
    if not answer:
        raise ValueError("answer required")
    for r in card.get("requests") or []:
        if r.get("id") == rid:
            verb = "answered"
            if r.get("status") == "answered":
                if not body.get("reopen"):
                    raise ValueError("already answered")
                verb = "re-answered"
            r["status"] = "answered"
            r["answer"] = answer[:500]
            comms_add(card, frm, f"{verb} {rid}: {answer[:200]}")
            return "answer saved"
    raise ValueError(f"no request {rid}")


def do_request(card: dict, body: dict) -> str:
    ask = str(body.get("ask") or "").strip()
    if not ask:
        raise ValueError("ask required")
    frm = actor(body)
    rid = str(body.get("request_id") or "").strip() or slugify(ask)
    reqs = card.setdefault("requests", [])
    if any(r.get("id") == rid for r in reqs):
        raise ValueError(f"duplicate request id {rid}")
    req = {"id": rid, "ask": ask, "status": "open"}
    if body.get("options"):
        req["options"] = body["options"]
    reqs.append(req)
    comms_add(card, frm, f"raised request {rid}: {ask[:120]}")
    return f"request {rid} raised"


PIPELINE_STAGES = {"plan", "structure", "develop", "audit", "benchmark"}
PIPELINE_STATUSES = {"pass", "fail", "skip", "delegated", "blocked",
                     "running"}


def do_pipeline(card: dict, body: dict, frm: str) -> str:
    """CI pipeline write path — see docs/ssot/ssot.ci.yml.

    Accepts either a full status block ({pipeline: {...}} — stages are
    deep-merged so partial updates don't clobber earlier stages) or a
    single stage result ({stage, status, detail?}). opt_in:true writes
    the `pipeline: ci` shorthand; opt_in:false removes the block."""
    if "opt_in" in body:
        if body["opt_in"]:
            if not isinstance(card.get("pipeline"), dict):
                card["pipeline"] = "ci"
            else:
                card["pipeline"]["opt_in"] = "ci"
        else:
            card.pop("pipeline", None)
            comms_add(card, frm, "pipeline opt-in removed")
            return "pipeline opt-in removed"

    pipe = body.get("pipeline")
    if isinstance(pipe, dict):
        cur = card.get("pipeline")
        if not isinstance(cur, dict):
            cur = {"opt_in": "ci", "stages": {}}
        merged = dict(cur)
        stages = dict(merged.get("stages") or {})
        for name, res in (pipe.get("stages") or {}).items():
            if name not in PIPELINE_STAGES:
                raise ValueError(f"stage must be one of {sorted(PIPELINE_STAGES)}")
            stages[name] = res
        merged["stages"] = stages
        for k, v in pipe.items():
            if k != "stages":
                merged[k] = v
        merged["opt_in"] = "ci"
        card["pipeline"] = merged
    elif body.get("stage"):
        stage = body["stage"]
        if stage not in PIPELINE_STAGES:
            raise ValueError(f"stage must be one of {sorted(PIPELINE_STAGES)}")
        status = body.get("status")
        if status not in PIPELINE_STATUSES:
            raise ValueError(f"status must be one of {sorted(PIPELINE_STATUSES)}")
        cur = card.get("pipeline")
        if not isinstance(cur, dict):
            cur = {"opt_in": "ci", "stages": {}}
        cur.setdefault("stages", {})[stage] = {
            "status": status, "at": now(),
            "detail": str(body.get("detail") or "")[:300]}
        card["pipeline"] = cur
    elif "opt_in" not in body:
        raise ValueError("pipeline, stage, or opt_in required")

    stages = (card.get("pipeline") or {}).get("stages") \
        if isinstance(card.get("pipeline"), dict) else None
    summary = " ".join(f"{n}={s.get('status')}" for n, s in
                       (stages or {}).items()) or "opt-in"
    comms_add(card, frm, f"pipeline updated: {summary}"[:500])
    return "pipeline updated"


def render() -> None:
    subprocess.run(
        [sys.executable, str(RENDER)], cwd=REPO, timeout=60, check=False
    )


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("board-api %s\n" % (fmt % args))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"ok": True})
        if path == "/cards":
            j = REPO / "stacks/web/public/apps/board/cards.json"
            if j.exists():
                return self._send(200, json.loads(j.read_text()))
            return self._send(404, {"error": "no cards.json yet"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0)) or b"0") or b"{}")
        except Exception:
            return self._send(400, {"error": "bad json"})

        with LOCK.open("w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                if path == "/action":
                    verb = body.get("do", "queue")
                    if verb not in TRANSITIONS:
                        raise ValueError(f"do must be one of {sorted(TRANSITIONS)}")
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    if verb == "claim":
                        msg = do_claim(card, body)
                    elif verb == "move":
                        msg = do_move(card, body)
                    else:
                        msg = do_action(card, verb, "tony")
                    card["updated"] = now()
                    save(p, card)
                elif path == "/respond":
                    frm = actor(body)
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    msg = do_respond(card, body, frm)
                    card["updated"] = now()
                    save(p, card)
                elif path == "/comment":
                    frm = actor(body, default="")
                    text = str(body.get("text") or "").strip()
                    if not text:
                        raise ValueError("text required")
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    comms_add(card, frm, text)
                    card["updated"] = now()
                    save(p, card)
                    msg = "comment added"
                elif path == "/request":
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    msg = do_request(card, body)
                    card["updated"] = now()
                    save(p, card)
                elif path == "/pipeline":
                    frm = actor(body)
                    p = card_path(body.get("id", ""))
                    card = load(p)
                    msg = do_pipeline(card, body, frm)
                    card["updated"] = now()
                    save(p, card)
                else:
                    return self._send(404, {"error": "not found"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:
                return self._send(500, {"error": str(e)})
            render()
        self._send(200, {"ok": True, "message": msg})


def _selftest() -> None:
    """Pure-function smoke test — no HTTP, no card files.
    Run: python3 scripts/board/board-api.py --selftest"""
    def rejects(fn, frag):
        try:
            fn()
        except ValueError as e:
            assert frag in str(e), f"expected {frag!r} in {e!r}"
            return
        raise AssertionError(f"expected ValueError {frag!r}")

    card = {"requests": [{"id": "r1", "ask": "pick one", "status": "open"}]}
    rejects(lambda: do_respond(card, {"request_id": "r1", "answer": " "}, "tony"),
            "answer required")
    rejects(lambda: do_respond(card, {"request_id": "nope", "answer": "x"}, "tony"),
            "no request")
    do_respond(card, {"request_id": "r1", "answer": "yes"}, "ada")
    assert card["requests"][0]["status"] == "answered"
    assert card["comms"][-1]["from"] == "ada"
    rejects(lambda: do_respond(card, {"request_id": "r1", "answer": "b"}, "tony"),
            "already answered")
    do_respond(card, {"request_id": "r1", "answer": "b", "reopen": True}, "tony")
    assert card["requests"][0]["answer"] == "b"
    assert "re-answered r1" in card["comms"][-1]["text"]

    rejects(lambda: do_request(card, {"ask": "  "}), "ask required")
    rejects(lambda: do_request(card, {"ask": "q", "from": "nobody"}),
            "from must be one of")
    do_request(card, {"ask": "ship it?", "request_id": "rq2",
                      "options": ["y", "n"], "from": "ada"})
    req = card["requests"][-1]
    assert req == {"id": "rq2", "ask": "ship it?", "status": "open",
                   "options": ["y", "n"]}
    assert card["comms"][-1]["from"] == "ada"
    assert "raised request rq2" in card["comms"][-1]["text"]
    rejects(lambda: do_request(card, {"ask": "again", "request_id": "rq2"}),
            "duplicate request id")
    do_request(card, {"ask": "auto id please"})
    assert card["requests"][-1]["id"].startswith("auto-id-please-")
    do_request(card, {"ask": "ตอบหน่อย"})  # non-ascii ask still gets an id
    assert card["requests"][-1]["id"].startswith("req-")

    # /pipeline
    card = {}
    rejects(lambda: do_pipeline(card, {}, "devin"),
            "pipeline, stage, or opt_in required")
    do_pipeline(card, {"opt_in": True}, "devin")
    assert card["pipeline"] == "ci"
    rejects(lambda: do_pipeline(card, {"stage": "bogus", "status": "pass"},
                                "devin"), "stage must be one of")
    rejects(lambda: do_pipeline(card, {"stage": "plan", "status": "meh"},
                                "devin"), "status must be one of")
    do_pipeline(card, {"stage": "plan", "status": "pass",
                       "detail": "spec ok"}, "devin")
    assert isinstance(card["pipeline"], dict)
    assert card["pipeline"]["stages"]["plan"]["status"] == "pass"
    # full block merge — earlier stages preserved
    do_pipeline(card, {"pipeline": {"stages": {
        "audit": {"status": "pass", "at": "t", "detail": "2 checks"}},
        "benchmark": {"metric": "m", "before": "2"}}}, "devin")
    assert card["pipeline"]["stages"]["plan"]["status"] == "pass"
    assert card["pipeline"]["stages"]["audit"]["status"] == "pass"
    assert card["pipeline"]["benchmark"]["before"] == "2"
    do_pipeline(card, {"opt_in": False}, "devin")
    assert "pipeline" not in card
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
