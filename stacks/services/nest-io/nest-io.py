#!/usr/bin/env python3
"""nest-io.py — the Nest I/O fabric (v1).

Decouples the input surface from the response surface. An utterance on
surface A binds to a session whose reply surface can be B — voice reply
in-session, a `speak` on a vcast screen / TV, a kanban card comment, or a
silent note into a memory bank. Gemini Live becomes one lane among others:
every input also gets a lane recommendation (gemini-live vs local).

Four pieces, one daemon:

  1. Surface registry — producers register {kind, room, caps, target}
     (voice ws session, vcast screen, HA media_player, kanban card, bank).
     vcast displays are mirrored in automatically from input-bridge
     /displays each tick. Stale surfaces expire after SURFACE_TTL_S.
  2. Ingestion tiers — EVERY input gets a tier decision recorded in the
     ledger: hot (live session), warm (compressed session summary), cold
     (extracted facts -> cold-queue.jsonl, optional MDDB bank write),
     discard (noise/dup/filler). The triage is the point — the record of
     WHY is as important as the decision.
  3. Session registry — an input binds to a session keyed by its origin
     surface (+user when known); a second surface joining while a session
     is open becomes a co-listener, never steals the reply surface.
  4. Response broker — /v1/respond picks the output surface and delivers
     through adapters (input-bridge speak/cast, board-api comment, MDDB
     bank note, HA tts.speak). Every respond also returns reply_text so
     the calling ws session always has something to say. Failed surfaces
     fall back; the last fallback is a note — a reply is never dropped.

Route rule precedence for picking the reply surface:
  explicit phrase in the utterance ("answer on the TV", "on screen 3",
  "reply here") > session-pinned route > room match (screen in the same
  room) > last-active screen > origin surface.

Adapters are config-gated and safe by default: with no *_URL env the
service still runs — deliveries are recorded as queued/unsupported in the
ledger, nothing leaves the box. NEST_IO_OFFLINE=1 suppresses all egress.

Usage:
    nest-io.py --serve          daemon: HTTP + sweeper (service entry)
    nest-io.py --once           mirror displays + sweep + write state, exit
    nest-io.py --selftest       in-process scenario: surfaces, inputs,
                                tiers, routing, broker — prints decisions
    nest-io.py --ledger [N]     print the last N ledger entries

Env:
    NEST_IO_BIND        listen addr (default 127.0.0.1; tailnet IP to serve LAN)
    NEST_IO_PORT        listen port (default 8795)
    NEST_IO_STATE       state dir (default ~/.local/share/nest/io-fabric)
    NEST_IO_OFFLINE     "1" = never emit egress, record only
    INPUT_BRIDGE_URL    default https://tony-dell.taila0626a.ts.net/api/input-bridge
    BOARD_API_URL       default https://tony-dell.taila0626a.ts.net/apps/board-api
    MDDB_BASE_URL       default http://100.102.134.91:11023/v1
    NEST_IO_MDDB_COLD   "1" = also write cold facts to ada-ha-bank-inbox-cold
    HA_URL / HASS_TOKEN enables the ha_media_player speak adapter
    NEST_IO_GEMINI      "degraded"|"down" forces lane=local (quota breaker)
    NEST_IO_SURFACES    seed surfaces JSON file (static screens like the TV)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ICT = timezone(timedelta(hours=7))
STATE_DIR = Path(os.environ.get(
    "NEST_IO_STATE", Path.home() / ".local" / "share" / "nest" / "io-fabric"))
STATE_FILE = STATE_DIR / "fabric-state.json"
COLD_QUEUE = STATE_DIR / "cold-queue.jsonl"
NOTE_QUEUE = STATE_DIR / "note-queue.jsonl"

PORT = int(os.environ.get("NEST_IO_PORT", "8795"))
BIND = os.environ.get("NEST_IO_BIND", "127.0.0.1")
OFFLINE = os.environ.get("NEST_IO_OFFLINE", "") == "1"
INPUT_BRIDGE = os.environ.get(
    "INPUT_BRIDGE_URL",
    "https://tony-dell.taila0626a.ts.net/api/input-bridge").rstrip("/")
BOARD_API = os.environ.get(
    "BOARD_API_URL",
    "https://tony-dell.taila0626a.ts.net/apps/board-api").rstrip("/")
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
MDDB_COLD = os.environ.get("NEST_IO_MDDB_COLD", "") == "1"
COLD_BANK = "ada-ha-bank-inbox-cold"
HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HASS_TOKEN = os.environ.get("HASS_TOKEN", "")
GEMINI_STATE = os.environ.get("NEST_IO_GEMINI", "").lower()  # ""|degraded|down
SEED_SURFACES = os.environ.get("NEST_IO_SURFACES", "")

SESSION_GAP_S = 120        # inputs within this gap continue the session
SESSION_TTL_S = 15 * 60    # idle session is closed + warm summary flushed
SURFACE_TTL_S = 10 * 60    # registered surface goes stale without heartbeat
BRIDGE_TTL_S = 90          # mirrored vcast screens re-check faster
DEDUP_S = 60               # same text+surface inside this window = dup
LEDGER_CAP = 300
HOT_RING = 12              # hot turns kept verbatim per session
WARM_BITS_CAP = 40
TICK_S = 30
HTTP_TIMEOUT = 8

FILLERS = {
    "um", "uh", "er", "erm", "hmm", "mm", "hm", "yeah", "yep", "yes",
    "ok", "okay", "k", "kk", "right", "sure", "ah", "oh", "eh", "well",
    "like", "so", "na", "ka", "kha", "khrap", "kap", "ha",
    "ค่ะ", "ครับ", "คะ", "อืม", "เอ่อ", "อะ", "นะ", "ใช่", "โอเค", "อืมม",
}
ADA_RX = re.compile(r"^\s*(hey |ok |okay )?(ada|เอด้า|เอดา)\b", re.I)
QUESTION_RX = re.compile(r"[?？]$|^(who|what|when|where|why|how|which|"
                         r"is|are|was|were|do|does|did|can|could|will|would|"
                         r"shall|should|may)\b", re.I)
COMMAND_RX = re.compile(
    r"^(turn|switch|open|close|play|pause|stop|cast|show|put|set|dim|"
    r"start|restart|check|look|watch|read|tell|say|speak|answer|reply|"
    r"remind|remember|note|add|send|call|run|list|find|search|get|give|"
    r"mute|volume|lock|unlock|arm|disarm)\b", re.I)
TOOL_WORDS = re.compile(
    r"\b(cast|screen|tv|television|camera|cctv|light|lights|lamp|switch|"
    r"door|gate|lock|ac|aircon|thermostat|temperature|speaker|volume|"
    r"play|youtube|spotify|music|movie|show|nav|open|turn|dim|timer|"
    r"reminder|calendar|card|kanban|dispatch|devin)\b", re.I)
ROUTE_RX = re.compile(
    r"(?:answer|reply|respond|tell me|say it|play it|show it|put it|"
    r"cast it|send it|speak)\s+(?:on|to|at)\s+(?:the\s+|my\s+)?"
    r"(tv|television|living[- ]?room|kitchen|bedroom|screen\s*(\d+)|"
    r"ipad|tablet|phone|iphone|board|card|([\w-]+))",
    re.I)
HERE_RX = re.compile(r"(?:answer|reply|respond)\s+(?:right )?here\b|"
                     r"on this (?:device|screen|phone)\b", re.I)
QUIET_RX = re.compile(r"\b(silently|quietly|just (?:note|log|record|remember)|"
                      r"don'?t (?:say|speak|answer out loud))\b", re.I)

# cold fact patterns -> (kind, subject group, attribute group)
FACT_RULES = [
    (re.compile(r"\bremember (?:that |to )?(?P<a>.+)", re.I),
     "procedure", None, "a"),
    (re.compile(r"\bmy (?P<s>[\w' ]{2,30}?) (?:is|are|was|were) "
                r"(?P<a>.+)", re.I), "preference", "s", "a"),
    (re.compile(r"\bi (?:prefer|like|love|hate|dislike|don'?t like|use|"
                r"usually|always|never) (?P<a>.+)", re.I),
     "preference", None, "a"),
    (re.compile(r"\b(?:the |my )?([\w' ]{2,20}?) (?:password|pin|code) "
                r"is (?P<a>.+)", re.I), "sensitive", None, "a"),
    (re.compile(r"\b(?:from now on|always|never),? (?P<a>.+)", re.I),
     "procedure", None, "a"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _age_s(iso: str | None) -> float:
    if not iso:
        return 1e9
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (_now() - dt).total_seconds()
    except ValueError:
        return 1e9


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w']+|[^\s\w]", text.lower())


def _http(method: str, url: str, payload: dict | None = None,
          headers: dict | None = None, timeout: int = HTTP_TIMEOUT):
    """Tiny JSON HTTP client. Returns (status, parsed|text). Raises on
    transport error — callers treat exceptions as delivery failure."""
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type":
                                          "application/json",
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        try:
            return r.status, json.loads(body)
        except Exception:
            return r.status, body.decode("utf-8", "replace")


# ---------------------------------------------------------------- fabric

class Fabric:
    """Core state machine — surfaces, sessions, tiers, broker. All I/O
    adapters go through self.send() so tests run fully offline."""

    def __init__(self, state_dir: Path = STATE_DIR, offline: bool = OFFLINE):
        self.dir = state_dir
        self.offline = offline
        self.lock = threading.RLock()
        self.cold_queue = self.dir / "cold-queue.jsonl"
        self.note_queue = self.dir / "note-queue.jsonl"
        self.state = {"surfaces": {}, "sessions": {},
                      "metrics": {"requests_total": 0, "inputs_total": 0,
                                  "deliveries_total": 0,
                                  "deliveries_failed": 0,
                                  "fallbacks_total": 0},
                      "started": _iso(_now())}
        self.ledger: list[dict] = []
        self._seen: list[tuple[str, str, str]] = []   # (surface, norm, iso)
        self._load()
        self._load_seed_surfaces()

    # ------------------------------------------------------------ state
    def _load(self):
        try:
            doc = json.loads((self.dir / "fabric-state.json").read_text())
            for k in ("surfaces", "sessions", "metrics"):
                if isinstance(doc.get(k), dict):
                    self.state[k].update(doc[k])
            self.ledger = [e for e in doc.get("ledger", [])
                           if isinstance(e, dict)][-LEDGER_CAP:]
        except Exception:
            pass

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        doc = {"service": "nest-io v1", "updated": _iso(_now()),
               **self.state, "ledger": self.ledger[-LEDGER_CAP:]}
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".st-")
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1)
        os.replace(tmp, self.dir / "fabric-state.json")

    def _load_seed_surfaces(self):
        if not SEED_SURFACES:
            return
        try:
            for s in json.loads(Path(SEED_SURFACES).read_text()):
                if isinstance(s, dict) and s.get("id"):
                    s.setdefault("source", "seed")
                    self.register_surface(s)
        except Exception as e:
            print(f"warn: seed surfaces unreadable ({e})", file=sys.stderr)

    def log(self, etype: str, **fields):
        e = {"ts": _iso(_now()), "kind": etype, **fields}
        with self.lock:
            self.ledger.append(e)
            if len(self.ledger) > LEDGER_CAP:
                self.ledger = self.ledger[-LEDGER_CAP:]
        return e

    def bump(self, key: str, n: int = 1):
        m = self.state["metrics"]
        m[key] = int(m.get(key) or 0) + n

    # --------------------------------------------------------- surfaces
    def register_surface(self, s: dict) -> dict:
        """Register or heartbeat a surface."""
        with self.lock:
            sid = str(s.get("id") or "").strip()
            if not sid:
                kind = s.get("kind", "misc")
                sid = f"{kind}-{hashlib.md5(json.dumps(s, sort_keys=True).encode()).hexdigest()[:6]}"
            cur = self.state["surfaces"].setdefault(sid, {"id": sid})
            cur.update({k: v for k, v in s.items() if v is not None})
            cur.setdefault("kind", "misc")
            cur["last_seen"] = _iso(_now())
            if s.get("active"):
                cur["last_active"] = _iso(_now())
            cur.pop("stale", None)
            self.log("surface", surface=sid, action="register",
                     surface_kind=cur.get("kind"))
            return cur

    def surfaces(self, live_only: bool = False) -> list[dict]:
        out = list(self.state["surfaces"].values())
        if live_only:
            out = [s for s in out if not s.get("stale")]
        return sorted(out, key=lambda s: s.get("id") or "")

    def _find_surface(self, ref) -> dict | None:
        """Resolve a surface ref: id, vcast screen number, name/alias."""
        if isinstance(ref, dict):
            return ref
        ss = self.state["surfaces"]
        ref_s = str(ref)
        if ref_s in ss:
            return ss[ref_s]
        m = re.match(r"^(?:screen[- ]?)?(\d+)$", ref_s)
        if m:
            n = int(m.group(1))
            for s in ss.values():
                if (s.get("target") or {}).get("vcast_screen") == n:
                    return s
                if s.get("id") == f"screen-{n}":
                    return s
        low = ref_s.lower()
        for s in ss.values():
            names = [s.get("id") or "", s.get("label") or "",
                     *(s.get("aliases") or [])]
            if any(low == str(x).lower() for x in names if x):
                return s
        return None

    # ----------------------------------------------------------- mirror
    def mirror_displays(self):
        """Mirror input-bridge /displays into screen surfaces."""
        if self.offline:
            return 0
        try:
            st, d = _http("GET", f"{INPUT_BRIDGE}/displays", timeout=4)
            items = d.get("displays") if isinstance(d, dict) else d
            if not isinstance(items, list):
                return 0
        except Exception as e:
            self.log("mirror", ok=False, error=str(e)[:120])
            return 0
        n = 0
        for d in items:
            if not isinstance(d, dict):
                continue
            scr = d.get("screen")
            if scr is None:
                continue
            live = not d.get("disconnected_at")
            self.register_surface({
                "id": f"screen-{scr}", "kind": "screen",
                "label": d.get("label") or d.get("name") or f"vcast {scr}",
                "room": d.get("room"),
                "caps": ["speak", "display", "cast"],
                "target": {"vcast_screen": scr},
                "active": live and d.get("state") not in (None, "idle"),
                "meta": {"state": d.get("state"),
                         "state_detail": d.get("state_detail")},
                "source": "input-bridge"})
            s = self.state["surfaces"][f"screen-{scr}"]
            if not live:
                s["stale"] = True
            n += 1
        self.log("mirror", ok=True, displays=n)
        return n

    # ------------------------------------------------------------- tier
    def _dup(self, surface: str, norm: str) -> bool:
        self._seen = [x for x in self._seen if _age_s(x[2]) < DEDUP_S]
        if (surface, norm) in [(a, b) for a, b, _ in self._seen]:
            return True
        self._seen.append((surface, norm, _iso(_now())))
        self._seen = self._seen[-500:]
        return False

    def extract_facts(self, text: str) -> list[dict]:
        facts = []
        for rx, kind, sg, ag in FACT_RULES:
            m = rx.search(text)
            if not m:
                continue
            fact = {"kind": kind, "text": text.strip()[:300],
                    "attribute": (m.group(ag) or "").strip()[:200]}
            if sg:
                fact["subject"] = (m.group(sg) or "").strip()[:80]
            facts.append(fact)
        return facts

    def decide_tier(self, text: str, surface: str, addressed: bool,
                    session_open: bool, kind: str = "utterance") -> dict:
        """One tier per input + reasons. The ledger IS the triage."""
        norm = _norm(text)
        toks = _tokens(text)
        words = [t for t in toks if re.match(r"[\w']+$", t)]
        reasons = []
        if kind == "noise" or not norm or len(norm) < 2:
            return {"tier": "discard", "reason": "empty-or-noise",
                    "facts": []}
        if self._dup(surface, norm):
            return {"tier": "discard", "reason": "dup-60s", "facts": []}
        if words and all(w in FILLERS for w in words):
            return {"tier": "discard", "reason": "filler-only",
                    "facts": []}
        facts = self.extract_facts(text)
        explicit_remember = bool(re.search(r"\bremember\b", text, re.I))
        declarative = (facts and not addressed
                       and not QUESTION_RX.search(text)
                       and not COMMAND_RX.search(text))
        if explicit_remember or declarative:
            reasons.append("durable-fact" if declarative
                           else "explicit-remember")
            return {"tier": "cold", "reason": ";".join(reasons),
                    "facts": facts}
        if addressed or QUESTION_RX.search(text) \
                or COMMAND_RX.search(text):
            return {"tier": "hot", "reason": "addressed-or-interactive",
                    "facts": facts}
        # ambient content stays a summary even inside a live session —
        # only short continuations get promoted to hot context.
        if not addressed and len(norm) >= 30:
            return {"tier": "warm", "reason": "ambient-content",
                    "facts": facts}
        if session_open:
            return {"tier": "hot", "reason": "session-continuation",
                    "facts": facts}
        if len(words) >= 6:
            return {"tier": "warm", "reason": "ambient-content",
                    "facts": facts}
        return {"tier": "discard", "reason": "short-noncontent",
                "facts": facts}

    # --------------------------------------------------------- sessions
    def _bind_session(self, surface_id: str, user: str | None,
                      room: str | None, explicit_id: str | None) -> dict:
        ss = self.state["sessions"]
        if explicit_id and explicit_id in ss:
            ses = ss[explicit_id]
        else:
            ses = None
            for s in ss.values():
                if s.get("closed_at"):
                    continue
                if s.get("origin_surface") == surface_id and \
                        _age_s(s.get("last_input_at")) < SESSION_GAP_S:
                    ses = s
                    break
            if ses is None:
                # co-listen: open session for the same user/room -> join,
                # don't steal the reply surface.
                for s in ss.values():
                    if s.get("closed_at") or \
                            _age_s(s.get("last_input_at")) >= SESSION_GAP_S:
                        continue
                    same_user = user and s.get("user") and \
                        s.get("user") == user
                    same_room = room and s.get("room") and \
                        s.get("room") == room
                    if same_user or (same_room and not user):
                        if surface_id not in s["co_listeners"] and \
                                surface_id != s["origin_surface"]:
                            s["co_listeners"].append(surface_id)
                            self.log("session", action="co-listen",
                                     session=s["id"], surface=surface_id)
                        return s
                sid = f"s{int(time.time() * 1000) % 10_000_000:07d}-" \
                      f"{hashlib.md5((surface_id + _iso(_now())).encode()).hexdigest()[:4]}"
                ses = {"id": sid, "origin_surface": surface_id,
                       "user": user, "room": room,
                       "reply_surface": None, "reply_kind": None,
                       "co_listeners": [], "lane": None,
                       "opened_at": _iso(_now()), "last_input_at": None,
                       "closed_at": None,
                       "tier_counts": {"hot": 0, "warm": 0, "cold": 0,
                                       "discard": 0},
                       "hot": [], "warm_bits": [],
                       "warm_summary": None, "route_override": None,
                       "route_history": []}
                ss[sid] = ses
                self.log("session", action="open", session=sid,
                         surface=surface_id, user=user, room=room)
        return ses

    # ------------------------------------------------------------ route
    def _explicit_route(self, text: str) -> dict | None:
        if HERE_RX.search(text):
            return {"mode": "origin", "why": "reply-here"}
        m = ROUTE_RX.search(text)
        if not m:
            if QUIET_RX.search(text):
                return {"mode": "note", "why": "quiet"}
            return None
        word = (m.group(1) or "").lower().strip()
        if m.group(2):
            s = self._find_surface(m.group(2))
            return {"mode": "surface", "ref": m.group(2), "surface": s,
                    "why": f"screen-{m.group(2)}"}
        if word in ("board", "card", "kanban"):
            return {"mode": "card", "why": "to-card"}
        if word in ("tv", "television", "living-room", "livingroom",
                    "living"):
            s = self._pick_tv()
            return {"mode": "surface", "ref": "tv", "surface": s,
                    "why": "tv"}
        s = self._find_surface(word) or self._find_surface(m.group(3) or "")
        if s:
            return {"mode": "surface", "ref": word, "surface": s,
                    "why": f"named:{word}"}
        if word in ("ipad", "tablet", "phone", "iphone"):
            for sf in self.state["surfaces"].values():
                if word in (sf.get("id") or "").lower() or \
                        word in (sf.get("label") or "").lower():
                    return {"mode": "surface", "ref": word, "surface": sf,
                            "why": f"named:{word}"}
        return {"mode": "unresolved", "ref": word, "why": "named-unknown"}

    def _pick_tv(self) -> dict | None:
        """Prefer a surface flagged is_tv / tv alias; else newest screen."""
        screens = [s for s in self.state["surfaces"].values()
                   if s.get("kind") == "screen" and not s.get("stale")]
        for s in screens:
            names = " ".join([s.get("id") or "", s.get("label") or "",
                              " ".join(s.get("aliases") or [])]).lower()
            if "tv" in names or s.get("is_tv"):
                return s
        return max(screens, key=lambda s: s.get("last_active") or "",
                   default=None)

    def resolve_reply(self, ses: dict, text: str,
                      origin: dict | None) -> dict:
        """Return {surface, kind, why, route} — precedence: explicit >
        pinned > room > last-active screen > origin."""
        route = self._explicit_route(text)
        if route and route.get("mode") == "unresolved":
            route = None
        if route:
            if route["mode"] == "origin":
                return {"surface": origin, "kind": self._surface_kind(origin),
                        "why": "explicit:reply-here", "route": "explicit"}
            if route["mode"] == "note":
                return {"surface": {"id": "bank", "kind": "note",
                                    "target": {"bank": "general"}},
                        "kind": "note", "why": "explicit:quiet-note",
                        "route": "explicit"}
            if route["mode"] == "card":
                return {"surface": {"id": "board", "kind": "card",
                                    "target": {"card": "focus"}},
                        "kind": "card", "why": "explicit:to-card",
                        "route": "explicit"}
            if route.get("surface"):
                s = route["surface"]
                return {"surface": s, "kind": self._surface_kind(s),
                        "why": f"explicit:{route['why']}",
                        "route": "explicit"}
        if ses.get("route_override"):
            s = self._find_surface(ses["route_override"])
            if s and not s.get("stale"):
                return {"surface": s, "kind": self._surface_kind(s),
                        "why": "session-pinned", "route": "pinned"}
        room = ses.get("room")
        if room:
            mates = [s for s in self.state["surfaces"].values()
                     if s.get("kind") == "screen" and not s.get("stale")
                     and (s.get("room") or "").lower() == room.lower()]
            if mates:
                s = max(mates, key=lambda x: x.get("last_active") or "")
                return {"surface": s, "kind": self._surface_kind(s),
                        "why": f"room:{room}", "route": "room"}
        act = [s for s in self.state["surfaces"].values()
               if s.get("kind") == "screen" and not s.get("stale")
               and s.get("last_active")]
        if act:
            s = max(act, key=lambda x: x.get("last_active") or "")
            return {"surface": s, "kind": self._surface_kind(s),
                    "why": "last-active-screen", "route": "last-active"}
        return {"surface": origin, "kind": self._surface_kind(origin),
                "why": "origin", "route": "origin"}

    @staticmethod
    def _surface_kind(s: dict | None) -> str:
        if not s:
            return "ws"
        if s.get("kind") == "screen" or (s.get("target") or {}).get(
                "vcast_screen") is not None:
            return "screen"
        if (s.get("target") or {}).get("ha_media_player"):
            return "speaker"
        return s.get("kind") or "ws"

    # ------------------------------------------------------------- lane
    def decide_lane(self, text: str, addressed: bool, tier: str,
                    requested: str | None) -> dict:
        if requested in ("local", "gemini-live"):
            return {"lane": requested, "why": "caller-pinned"}
        if GEMINI_STATE in ("degraded", "down"):
            return {"lane": "local",
                    "why": f"gemini-{GEMINI_STATE}-breaker"}
        if tier in ("warm", "discard"):
            return {"lane": "local", "why": "non-interactive-tier"}
        if tier == "cold" and not addressed:
            return {"lane": "local", "why": "cold-extraction"}
        if addressed and TOOL_WORDS.search(text):
            return {"lane": "gemini-live", "why": "tool-surface"}
        if QUESTION_RX.search(text) and not TOOL_WORDS.search(text):
            return {"lane": "local", "why": "low-risk-qa"}
        if addressed:
            return {"lane": "gemini-live", "why": "interactive-turn"}
        return {"lane": "local", "why": "default-nonrealtime"}

    # ------------------------------------------------------------ input
    def ingest(self, body: dict) -> dict:
        """POST /v1/inputs — triage + bind + route + lane. dry_run=true
        computes the same decisions without mutating state."""
        self.bump("inputs_total")
        dry = bool(body.get("dry_run"))
        surface_ref = body.get("surface") or body.get("surface_id") or "anon"
        text = str(body.get("text") or "")
        kind = str(body.get("kind") or "utterance")
        user = body.get("user")
        addressed = bool(body.get("addressed")) or bool(ADA_RX.search(text))
        origin = self._find_surface(surface_ref)
        room = body.get("room") or (origin or {}).get("room")
        if origin is None and not dry:
            origin = self.register_surface({
                "id": str(surface_ref), "kind": "voice",
                "room": room, "caps": ["listen", "speak"],
                "source": "implicit", "active": True})
        ses_open_hint = False
        for s in self.state["sessions"].values():
            if s.get("closed_at") or \
                    _age_s(s.get("last_input_at")) >= SESSION_GAP_S:
                continue
            if s.get("origin_surface") == str(surface_ref):
                ses_open_hint = True
                break
            # a joinable open session (same user, or same room with no
            # user claim) also counts — co-listener turns are live turns.
            if user and s.get("user") and s["user"] == user:
                ses_open_hint = True
                break
            if room and s.get("room") and s["room"] == room and \
                    not (s.get("user") or user):
                ses_open_hint = True
                break
        dec = self.decide_tier(text, str(surface_ref), addressed,
                             ses_open_hint, kind)
        if dry:
            ses = {"id": "(dry)", "room": room, "co_listeners": [],
                   "route_override": None, "tier_counts": {}}
            lane = self.decide_lane(text, addressed, dec["tier"],
                                    body.get("lane"))
            reply = self.resolve_reply(ses, text, origin)
            return {"input_id": None, "dry_run": True, **dec,
                    "session_id": None, "reply": reply, **self._pub(lane)}
        with self.lock:
            ses = self._bind_session(str(surface_ref), user, room,
                                     body.get("session_id"))
            ses["last_input_at"] = _iso(_now())
            ses["tier_counts"][dec["tier"]] += 1
            inp = {"id": f"i{len(self.ledger):05d}-"
                         f"{hashlib.md5((text + _iso(_now())).encode()).hexdigest()[:6]}",
                   "ts": _iso(_now()), "surface": str(surface_ref),
                   "tier": dec["tier"], "why": dec["reason"],
                   "text": text[:300], "user": user}
            self._apply_tier(ses, inp, dec, text)
            lane = self.decide_lane(text, addressed, dec["tier"],
                                    body.get("lane"))
            ses["lane"] = lane["lane"]
            reply = self.resolve_reply(ses, text, origin)
            if reply["route"] == "explicit" and reply.get("surface"):
                ses["route_override"] = reply["surface"].get("id")
                ses["reply_surface"] = reply["surface"].get("id")
            elif not ses.get("reply_surface") or reply["route"] in (
                    "room", "last-active"):
                ses["reply_surface"] = (reply.get("surface") or {}
                                        ).get("id") or \
                    (origin or {}).get("id")
            ses["reply_kind"] = reply["kind"]
            ses["route_history"].append(
                {"ts": _iso(_now()), "route": reply["route"],
                 "surface": (reply.get("surface") or {}).get("id"),
                 "why": reply["why"]})
            ses["route_history"] = ses["route_history"][-20:]
            self.log("input", input=inp["id"], session=ses["id"],
                     tier=dec["tier"], why=dec["reason"],
                     reply_surface=ses["reply_surface"],
                     lane=lane["lane"], text=text[:80])
            self.save()
        return {"input_id": inp["id"], "session_id": ses["id"],
                "tier": dec["tier"], "tier_reason": dec["reason"],
                "facts": dec["facts"], "co_listeners": ses["co_listeners"],
                "reply": reply, **self._pub(lane)}

    @staticmethod
    def _pub(lane: dict) -> dict:
        return {"lane": lane["lane"], "lane_reason": lane["why"]}

    def _apply_tier(self, ses: dict, inp: dict, dec: dict, text: str):
        t = dec["tier"]
        if t == "hot":
            ses["hot"].append({"ts": inp["ts"], "text": text[:300]})
            ses["hot"] = ses["hot"][-HOT_RING:]
        elif t == "warm":
            ses["warm_bits"].append(self._warm_bit(text))
            ses["warm_bits"] = ses["warm_bits"][-WARM_BITS_CAP:]
        elif t == "cold":
            self._enqueue_cold(dec["facts"] or
                               [{"kind": "fact", "text": text[:300]}],
                               inp)
        # discard: nothing retained beyond the ledger line

    @staticmethod
    def _warm_bit(text: str) -> dict:
        """Extractive warm compression: gist + salient keywords."""
        words = _tokens(text)
        kw = sorted({w for w in words if re.match(r"[a-z]{4,}$", w)
                     and w not in FILLERS
                     and w not in {"that", "this", "with", "have", "from",
                                   "what", "when", "there", "about"}})[:8]
        return {"t": text.strip()[:160], "kw": kw}

    def _enqueue_cold(self, facts: list[dict], inp: dict):
        self.dir.mkdir(parents=True, exist_ok=True)
        for f in facts:
            rec = {"ts": _iso(_now()), "input": inp["id"],
                   "surface": inp["surface"], "user": inp.get("user"),
                   **f, "confidence": 0.6, "source": "nest-io",
                   "status": "staged"}
            with self.cold_queue.open("a") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.log("cold", input=inp["id"], fact_kind=f.get("kind"),
                     sensitive=f.get("kind") == "sensitive")
            if MDDB_COLD and not self.offline and \
                    f.get("kind") != "sensitive":
                try:
                    key = "cold-" + hashlib.md5(
                        (rec["ts"] + f.get("text", "")).encode()
                    ).hexdigest()[:10]
                    _http("POST", f"{MDDB}/add", {
                        "collection": COLD_BANK, "key": key, "lang": "en",
                        "contentMd": f.get("text", ""),
                        "meta": {"kind": [f.get("kind", "fact")],
                                 "status": ["staged"],
                                 "scope": ["tony"], "source": ["nest-io"],
                                 "confidence": ["0.6"],
                                 "subject": [f.get("subject") or "misc"],
                                 "written_by": ["nest-io"],
                                 "updated": [_iso(_now())]}}, timeout=15)
                except Exception as e:
                    self.log("cold", input=inp["id"], ok=False,
                             error=str(e)[:120])

    # ----------------------------------------------------------- broker
    def respond(self, body: dict) -> dict:
        """POST /v1/respond — pick the output surface and deliver."""
        self.bump("requests_total")
        text = str(body.get("text") or "")
        kind = str(body.get("kind") or "auto")
        ses = None
        if body.get("session_id"):
            ses = self.state["sessions"].get(str(body["session_id"]))
        target = None
        if body.get("surface"):
            target = self._find_surface(body["surface"])
            if target is None:
                return {"error": f"unknown surface {body['surface']}",
                        "ok": False}
        elif body.get("screen") is not None:
            target = self._find_surface(str(body["screen"]))
            if target is None:  # unregistered screen — cast raw anyway
                target = {"id": f"screen-{body['screen']}", "kind": "screen",
                          "target": {"vcast_screen": int(body["screen"])}}
        elif ses and ses.get("reply_surface"):
            target = self._find_surface(ses["reply_surface"])
        if kind == "auto":
            if body.get("url"):
                kind = "cast"
            elif body.get("card_id") or body.get("card"):
                kind = "card"
            elif body.get("bank") or body.get("note"):
                kind = "note"
            else:
                kind = "speak"
        deliveries = []
        if kind in ("speak", "cast"):
            deliveries += self._deliver_screen_chain(
                target, kind, text, body, ses)
        elif kind == "card":
            deliveries.append(self._deliver_card(
                str(body.get("card_id") or body.get("card") or "focus"),
                text, ses))
        elif kind == "note":
            deliveries.append(self._deliver_note(
                str(body.get("bank") or "general"), text, body))
        else:
            return {"error": f"unknown kind {kind}", "ok": False}
        # co-listeners get the same utterance when it was spoken
        if kind == "speak" and ses:
            for sid in ses.get("co_listeners") or []:
                s = self._find_surface(sid)
                if s and (s.get("target") or {}).get("vcast_screen"):
                    deliveries.append(self._deliver_screen(
                        s, "speak", text, body))
        ok = any(d.get("ok") for d in deliveries)
        if not ok and kind != "note":
            self.bump("fallbacks_total")
            deliveries.append(self._deliver_note(
                "general", text, body, fallback=True))
        self.save()
        return {"ok": any(d.get("ok") for d in deliveries),
                "kind": kind, "deliveries": deliveries,
                "reply_text": text,
                "session_id": ses and ses.get("id")}

    def _deliver_screen_chain(self, target, kind, text, body, ses):
        """Deliver to target; walk the fallback list on failure."""
        chain = []
        if target:
            chain.append(target)
        if ses and ses.get("reply_surface"):
            s = self._find_surface(ses["reply_surface"])
            if s and all(c.get("id") != s.get("id") for c in chain):
                chain.append(s)
        if ses:  # last: the origin surface (talk back where spoken from)
            s = self._find_surface(ses.get("origin_surface") or "")
            if s and all(c.get("id") != s.get("id") for c in chain):
                chain.append(s)
        out = []
        for s in chain or [{}]:
            d = self._deliver_screen(s, kind, text, body)
            out.append(d)
            if d.get("ok"):
                break
        return out

    def _deliver_screen(self, s: dict, kind: str, text: str,
                        body: dict) -> dict:
        tgt = s.get("target") or {}
        sid = s.get("id") or "?"
        if tgt.get("vcast_screen") is not None:
            n = tgt["vcast_screen"]
            if kind == "speak":
                msg = {"type": "speak", "text": text[:600],
                       "lang": body.get("lang") or "en"}
                if body.get("audio"):
                    msg["audio"] = body["audio"]
            else:
                mt = {"nav": "nav", "play": "play", "image": "image",
                      "audio": "audio"}.get(body.get("cast") or "nav", "nav")
                msg = {"type": mt, "url": body.get("url")}
            return self._send("vcast", sid, f"{INPUT_BRIDGE}/pub",
                              {"screen": n, "msg": msg})
        if tgt.get("ha_media_player"):
            return self._deliver_ha(tgt["ha_media_player"], text, sid)
        if s.get("kind") in ("voice", "ws", "misc"):
            # ws caller speaks it itself — the reply_text return channel
            return {"ok": True, "target": sid, "via": "ws-reply",
                    "detail": "returned to caller"}
        return {"ok": False, "target": sid, "via": "none",
                "error": "no adapter for surface"}

    def _deliver_card(self, card_id: str, text: str, ses) -> dict:
        body = {"id": card_id, "from": "ada-fabric",
                "text": text[:600]}
        if ses:
            body["text"] = f"[session {ses['id']}] {body['text']}"
        return self._send("board-api", card_id,
                          f"{BOARD_API}/comment", body)

    def _deliver_note(self, bank: str, text: str, body: dict,
                      fallback: bool = False) -> dict:
        rec = {"ts": _iso(_now()), "bank": bank, "text": text[:600],
               "session": body.get("session_id"),
               "fallback": fallback}
        if self.offline:
            return {"ok": True, "target": f"bank:{bank}", "via": "offline",
                    "detail": "recorded"}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            key = "note-" + hashlib.md5(
                (rec["ts"] + text).encode()).hexdigest()[:10]
            _http("POST", f"{MDDB}/add", {
                "collection": f"ada-ha-bank-{bank}", "key": key,
                "lang": "en", "contentMd": text[:600],
                "meta": {"kind": ["note"], "scope": ["tony"],
                         "status": ["active"], "source": ["nest-io"],
                         "written_by": ["nest-io"],
                         "updated": [_iso(_now())],
                         "last_verified": [_now().date().isoformat()]}},
                  timeout=15)
            self.bump("deliveries_total")
            return {"ok": True, "target": f"bank:{bank}", "via": "mddb"}
        except Exception as e:
            with self.note_queue.open("a") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.bump("deliveries_failed")
            self.log("deliver", target=f"bank:{bank}", ok=False,
                     error=str(e)[:120])
            return {"ok": True, "target": f"bank:{bank}",
                    "via": "note-queue", "detail": str(e)[:80]}

    def _deliver_ha(self, player: str, text: str, sid: str) -> dict:
        if not HA_URL or not HASS_TOKEN:
            return {"ok": False, "target": sid, "via": "ha",
                    "error": "HA_URL/HASS_TOKEN not configured"}
        return self._send("ha-tts", sid,
                          f"{HA_URL}/api/services/tts/speak",
                          {"entity_id": "tts.google_translate_en_com",
                           "media_player_entity_id": player,
                           "message": text[:400]},
                          headers={"Authorization":
                                   f"Bearer {HASS_TOKEN}"})

    def _send(self, via: str, target: str, url: str,
              payload: dict, headers: dict | None = None) -> dict:
        if self.offline:
            self.bump("deliveries_total")
            self.log("deliver", via=via, target=target, ok=True,
                     offline=True)
            return {"ok": True, "target": target, "via": via,
                    "detail": "offline-recorded"}
        try:
            st, _ = _http("POST", url, payload, headers=headers)
            ok = 200 <= st < 300
            self.bump("deliveries_total")
            if not ok:
                self.bump("deliveries_failed")
            self.log("deliver", via=via, target=target, ok=ok,
                     status=st)
            return {"ok": ok, "target": target, "via": via,
                    "status": st}
        except Exception as e:
            self.bump("deliveries_total")
            self.bump("deliveries_failed")
            self.log("deliver", via=via, target=target, ok=False,
                     error=str(e)[:120])
            return {"ok": False, "target": target, "via": via,
                    "error": str(e)[:120]}

    # ------------------------------------------------------------ sweep
    def sweep(self):
        """Expire idle sessions (flush warm summary) + stale surfaces."""
        now_closed = []
        for s in self.state["sessions"].values():
            if s.get("closed_at") or \
                    _age_s(s.get("last_input_at")) < SESSION_TTL_S:
                continue
            s["closed_at"] = _iso(_now())
            if s.get("warm_bits"):
                bits = s["warm_bits"]
                kw = sorted({k for b in bits for k in b.get("kw", [])})
                s["warm_summary"] = {
                    "n_bits": len(bits),
                    "keywords": kw[:20],
                    "gists": [b["t"] for b in bits][-10:]}
            now_closed.append(s["id"])
            self.log("session", action="close", session=s["id"],
                     warm_bits=len(s.get("warm_bits") or []))
        for s in self.state["surfaces"].values():
            ttl = BRIDGE_TTL_S if s.get("source") == "input-bridge" \
                else SURFACE_TTL_S
            if _age_s(s.get("last_seen")) > ttl:
                s["stale"] = True
        # prune sessions closed > 24h
        self.state["sessions"] = {
            k: s for k, s in self.state["sessions"].items()
            if not s.get("closed_at") or _age_s(s["closed_at"]) < 86400}
        if now_closed:
            self.save()
        return {"closed": now_closed}

    def health(self) -> dict:
        open_ses = [s for s in self.state["sessions"].values()
                    if not s.get("closed_at")]
        up = int((_now() - datetime.fromisoformat(
            self.state["started"])).total_seconds())
        return {"ok": True, "service": "nest-io", "version": 1,
                "uptime_s": up, "host": socket.gethostname().split(".")[0],
                "offline": self.offline,
                "surfaces": len(self.state["surfaces"]),
                "surfaces_live": len([s for s in
                                      self.state["surfaces"].values()
                                      if not s.get("stale")]),
                "sessions_open": len(open_ses),
                "cold_queue": (sum(1 for _ in self.cold_queue.open())
                               if self.cold_queue.exists() else 0),
                "gemini": GEMINI_STATE or "up"}

    def metrics(self) -> dict:
        m = dict(self.state["metrics"])
        tiers = {"hot": 0, "warm": 0, "cold": 0, "discard": 0}
        for s in self.state["sessions"].values():
            for k, v in (s.get("tier_counts") or {}).items():
                tiers[k] = tiers.get(k, 0) + v
        m.update({"uptime_s": self.health()["uptime_s"],
                  "tier_decisions": tiers,
                  "sessions_total": len(self.state["sessions"]),
                  "surfaces": len(self.state["surfaces"])})
        return m


# ------------------------------------------------------------------ http

class Handler(BaseHTTPRequestHandler):
    fabric: Fabric = None
    server_version = "nest-io/1"

    def _j(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            raise ValueError(f"bad json: {e}")

    def log_message(self, *a):  # quiet — journald has the prints
        pass

    def do_GET(self):
        f = self.fabric
        p = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if p == "/health":
                return self._j(200, f.health())
            if p == "/metrics":
                return self._j(200, f.metrics())
            if p == "/v1/surfaces":
                return self._j(200, {"surfaces": f.surfaces()})
            if p == "/v1/sessions":
                return self._j(200, {"sessions": [
                    {k: v for k, v in s.items() if k != "hot"}
                    for s in f.state["sessions"].values()]})
            m = re.match(r"^/v1/sessions/([\w-]+)$", p)
            if m:
                s = f.state["sessions"].get(m.group(1))
                return self._j(200, s) if s else \
                    self._j(404, {"error": "no such session"})
            if p == "/v1/ledger":
                import urllib.parse
                q = urllib.parse.parse_qs(
                    self.path.split("?", 1)[1] if "?" in self.path else "")
                n = int((q.get("n") or [50])[0])
                return self._j(200, {"ledger": f.ledger[-n:]})
            return self._j(404, {"error": "unknown path",
                                 "paths": ["/health", "/metrics",
                                           "/v1/surfaces", "/v1/sessions",
                                           "/v1/sessions/<id>",
                                           "/v1/ledger"]})
        except Exception as e:
            return self._j(500, {"error": str(e)})

    def do_POST(self):
        f = self.fabric
        p = self.path.split("?")[0].rstrip("/")
        try:
            body = self._body()
        except ValueError as e:
            return self._j(400, {"error": str(e)})
        try:
            if p == "/v1/surfaces":
                if not isinstance(body, dict):
                    return self._j(400, {"error": "object required"})
                return self._j(200, f.register_surface(body))
            if p == "/v1/inputs":
                if not body.get("text") and body.get("kind") != "noise":
                    return self._j(400, {"error": "text required"})
                return self._j(200, f.ingest(body))
            if p == "/v1/respond":
                if not body.get("text") and not body.get("url"):
                    return self._j(400, {"error": "text or url required"})
                return self._j(200, f.respond(body))
            m = re.match(r"^/v1/sessions/([\w-]+)/close$", p)
            if m:
                s = f.state["sessions"].get(m.group(1))
                if not s:
                    return self._j(404, {"error": "no such session"})
                s["closed_at"] = _iso(_now())
                if s.get("warm_bits"):
                    bits = s["warm_bits"]
                    s["warm_summary"] = {
                        "n_bits": len(bits),
                        "keywords": sorted({k for b in bits
                                            for k in b.get("kw", [])})[:20],
                        "gists": [b["t"] for b in bits][-10:]}
                f.save()
                return self._j(200, {"ok": True, "closed": s["id"],
                                     "warm_summary": s.get("warm_summary")})
            if p == "/v1/sweep":
                return self._j(200, f.sweep())
            return self._j(404, {"error": "unknown path"})
        except Exception as e:
            return self._j(500, {"error": str(e)})

    def do_DELETE(self):
        m = re.match(r"^/v1/surfaces/([\w.-]+)$",
                     self.path.split("?")[0].rstrip("/"))
        if m and m.group(1) in self.fabric.state["surfaces"]:
            del self.fabric.state["surfaces"][m.group(1)]
            self.fabric.save()
            return self._j(200, {"ok": True, "removed": m.group(1)})
        return self._j(404, {"error": "no such surface"})


def serve(fab: Fabric):
    Handler.fabric = fab
    httpd = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"nest-io: http://{BIND}:{PORT} state={STATE_DIR} "
          f"offline={fab.offline} gemini={GEMINI_STATE or 'up'}")
    stop = threading.Event()

    def sweeper():
        while not stop.is_set():
            try:
                fab.mirror_displays()
                fab.sweep()
            except Exception as e:
                print(f"sweep error: {e}", file=sys.stderr)
            stop.wait(TICK_S)

    t = threading.Thread(target=sweeper, daemon=True)
    t.start()
    try:
        httpd.serve_forever()
    finally:
        stop.set()
        fab.save()


def selftest(fab: Fabric):
    """In-process scenario — exercises tiers, routing, co-listen, broker.
    Always offline: recorded deliveries, zero egress."""
    fab.offline = True
    fab.register_surface({"id": "pwa-iphone", "kind": "voice",
                          "room": "living-room",
                          "caps": ["listen", "speak"], "active": True})
    fab.register_surface({"id": "screen-2", "kind": "screen",
                          "room": "living-room", "is_tv": True,
                          "label": "living-room TV",
                          "caps": ["speak", "display"],
                          "target": {"vcast_screen": 2}, "active": True})
    fab.register_surface({"id": "pwa-ipad", "kind": "voice",
                          "room": "living-room",
                          "caps": ["listen", "speak"], "active": True})
    cases = [
        ("utterance on pwa -> routed to room TV screen",
         {"surface": "pwa-iphone", "text": "ada what time is it?",
          "user": "tony"}),
        ("explicit TV override",
         {"surface": "pwa-iphone", "text": "answer on the TV",
          "user": "tony"}),
        ("co-listen: second surface same room+user",
         {"surface": "pwa-ipad", "text": "and what about tomorrow",
          "user": "tony"}),
        ("cold: declarative fact",
         {"surface": "pwa-iphone", "text": "my gate remote is in the "
          "kitchen drawer"}),
        ("cold: explicit remember",
         {"surface": "pwa-iphone", "text": "remember that the cleaner "
          "comes on fridays", "user": "tony"}),
        ("warm: ambient content",
         {"surface": "pwa-iphone", "text": "so the neighbor was saying "
          "the fence on the east side needs repair next month"}),
        ("discard: filler",
         {"surface": "pwa-iphone", "text": "um uh ok"}),
        ("discard: dup",
         {"surface": "pwa-iphone", "text": "ada what time is it?",
          "user": "tony"}),
    ]
    outs = []
    for label, body in cases:
        r = fab.ingest(dict(body))
        outs.append((label, r))
        print(f"--- {label}\n    tier={r['tier']} ({r['tier_reason']}) "
              f"lane={r['lane']} reply={r['reply']['why']}"
              f"->{(r['reply'].get('surface') or {}).get('id')}")
    sid = outs[0][1]["session_id"]
    r = fab.respond({"session_id": sid, "text": "It is 3:40 PM."})
    print(f"--- broker speak -> {r['deliveries']}")
    r = fab.respond({"session_id": sid, "text": "summary for the board",
                     "kind": "card", "card_id": "nest-io-fabric"})
    print(f"--- broker card -> {r['deliveries']}")
    r = fab.respond({"session_id": sid, "text": "quiet note",
                     "kind": "note", "bank": "general"})
    print(f"--- broker note -> {r['deliveries']}")
    fab.sweep()
    fab.save()
    print(json.dumps(fab.health(), indent=1))
    return outs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true",
                    help="daemon: HTTP + sweeper (service entry)")
    ap.add_argument("--once", action="store_true",
                    help="mirror displays + sweep + save, exit")
    ap.add_argument("--selftest", action="store_true",
                    help="in-process scenario, prints decisions")
    ap.add_argument("--ledger", nargs="?", const=30, type=int,
                    help="print last N ledger entries")
    ap.add_argument("--state", default=str(STATE_DIR))
    a = ap.parse_args()

    fab = Fabric(state_dir=Path(a.state))
    if a.selftest:
        selftest(fab)
        return 0
    if a.ledger is not None:
        for e in fab.ledger[-a.ledger:]:
            print(json.dumps(e, ensure_ascii=False))
        return 0
    if a.serve:
        serve(fab)
        return 0
    n = fab.mirror_displays()
    fab.sweep()
    fab.save()
    print(f"nest-io once: {n} displays mirrored, "
          f"{len(fab.state['surfaces'])} surfaces, "
          f"{len(fab.state['sessions'])} sessions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
