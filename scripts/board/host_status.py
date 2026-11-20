#!/usr/bin/env python3
"""host_status — live-first answer for "what is <host> processing / is
<host> up".

Card ada-status-live-state-preference (the OPS-1045 miss, observed
2026-11-09): a "what is kk-mac processing" ask was answered from board
card comms that were hours stale — "offline 22h, 15GiB free" — while the
live lane probe reported eligible with a 4-minute heartbeat and
~92-115GiB free. This module encodes the fix's three rules so every
caller gets them for free:

  1. Live surfaces are queried BEFORE board records: the ada-nest
     heartbeat probe (kk_mac_admission.snapshot for the kk_mac lane;
     the same ada-nest-heartbeats collection for other hosts), the
     nest-mgr ada-cms-pages/nest-<host> page, and runner claims.
  2. Every board-derived statement carries a record age ("as of Xh
     ago") — the reader always sees how stale the claim is.
  3. When live telemetry contradicts a board record (offline-vs-live,
     disk figures disagree, blocked-vs-eligible) BOTH sides are
     reported and the conflict is flagged — the stale record is never
     parroted as current fact.

Everything is injectable (cards, heartbeat docs, nest-page docs, now) so
the truthfulness rules are unit-testable without network. The live
probes fail soft: unreachable MDDB -> fetched:false, never fatal.

CLI:
    host_status.py kk-mac             JSON status document
    host_status.py kk-mac --text      answer string only
    host_status.py kk-mac --board-only   skip live probes (offline use)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _d in (_REPO / "scripts" / "devnest",):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import yaml  # noqa: E402

try:
    _YamlLoader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - pure-python yaml fallback
    _YamlLoader = yaml.SafeLoader

CARDS_JSON = _REPO / "stacks" / "web" / "public" / "apps" / "board" / \
    "cards.json"
CARD_DIR = _REPO / "docs" / "ssot" / "kanban" / "cards"

try:
    import kk_mac_admission  # scripts/devnest/kk_mac_admission.py
except Exception:  # pragma: no cover - module absent outside the repo
    kk_mac_admission = None

OPS_MDDB = os.environ.get(
    "HOST_STATUS_OPS_MDDB", "http://100.102.134.91:11026/v1")
CMS_MDDB = os.environ.get(
    "HOST_STATUS_CMS_MDDB", "http://100.102.134.91:11027/v1")
HEARTBEAT_COLLECTION = "ada-nest-heartbeats"
NEST_COLLECTION = "ada-cms-pages"
HEARTBEAT_FRESH_S = 900       # kk_mac_admission's max_age_s
DISK_TOLERANCE_GB = 10.0      # board-vs-live figures disagree past this
MAX_RECORDS = 5

# Canonical host slugs -> normalized text tokens that count as a mention.
# Tokens match on (-) boundaries so "kk-mac" never swallows "kk-macbook".
HOST_TOKENS = {
    "kk-mac": {"kk-mac", "kkmac", "kks-mac-studio", "kk-imac"},
    "kk-macbook": {"kk-macbook"},
    "tony-macbook": {"tony-macbook"},
    "tony-dell": {"tony-dell", "dell"},
    "tony-omen": {"tony-omen", "omen"},
    "idc01": {"idc01"}, "idc02": {"idc02"}, "idc03": {"idc03"},
    "mn01": {"mn01"}, "con01": {"con01"},
}
# normalized alias -> canonical slug
_ALIASES = {
    "kk-mac": "kk-mac", "kkmac": "kk-mac", "kk-mac-studio": "kk-mac",
    "kks-mac-studio": "kk-mac", "kks-mac-studio-local": "kk-mac",
    "kk-imac": "kk-mac", "kk-macbook": "kk-macbook",
    "tony-macbook": "tony-macbook", "macbook": "tony-macbook",
    "tony-dell": "tony-dell", "dell": "tony-dell",
    "tony-omen": "tony-omen", "omen": "tony-omen",
    "idc01": "idc01", "idc02": "idc02", "idc03": "idc03",
    "mn01": "mn01", "con01": "con01",
}
# heartbeat doc `host` key when it differs from the slug
HEARTBEAT_HOST = {"kk-mac": "KKs-Mac-Studio"}

OFFLINE_RE = re.compile(
    r"\b(offline|unreachable|not responding|is down|host down|went down"
    r"|dead|no route)\b", re.I)
DISK_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:GiB|GB|G)\b[^.\n]{0,50}"
    r"\b(?:free|avail|left)"
    r"|\b(?:free|avail(?:able)?|left)\b[^.\n]{0,30}"
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:GiB|GB|G)\b"
    r"|\bdisk\b[^.\n]{0,30}?(\d+(?:\.\d+)?)\s*(?:GiB|GB|G)\b"
    r"|\bdisk[_ ]?free[_ ]?gb[=:\s]\s*(\d+(?:\.\d+)?)", re.I)
BLOCKED_RE = re.compile(
    r"\b(blocked|not eligible|ineligible|stalled|cannot proceed"
    r"|can't proceed)\b", re.I)
ELIGIBLE_RE = re.compile(r"\beligible\b", re.I)
# "state claim" — a record asserting something about the host's current
# condition (vs an incidental name-drop inside a lesson slug). The
# newest claim gets its own line + conflict check even when it isn't
# among the latest raw mentions (OPS-1045's stale record was exactly
# this shape).
CLAIM_RE = re.compile(
    r"\b(offline|online|eligible|blocked|down|unreachable|disk|free"
    r"|busy|idle|processing|heartbeat|stalled|rendering|running"
    r"|load|memory|GiB)\b", re.I)


def _is_claim(text: str) -> bool:
    return bool(CLAIM_RE.search(text or ""))


def _norm(s: str) -> str:
    return re.sub(r"[\s_]+", "-", str(s or "").strip().lower()).strip("-.")


def canon_host(name: str) -> str:
    """Normalize a spoken/typed host reference to its canonical slug."""
    n = _norm(name).removesuffix(".local")
    n = _norm(n)
    return _ALIASES.get(n, n)


def _tokens(slug: str) -> set:
    return HOST_TOKENS.get(slug) or {slug}


def _mentions(text: str, tokens: set) -> bool:
    norm = _norm(text)
    for tok in tokens:
        # alnum boundaries — "-" is the normalized separator, so
        # "kk-mac" matches "…-kk-mac-…" but never inside "kk-macbook"
        if re.search(r"(?<![a-z0-9])" + re.escape(_norm(tok))
                     + r"(?![a-z0-9])", norm):
            return True
    return False


def _parse_ts(raw) -> float | None:
    """Card timestamps are 'YYYY-MM-DD HH:MM' local-naive; epochs pass
    through. Returns epoch seconds or None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        # naive board time — the board host's local clock
        return dt.astimezone().timestamp()
    return dt.timestamp()


def age_str(age_s: float | None) -> str:
    if age_s is None:
        return "unknown age"
    if age_s < 90:
        return f"{int(age_s)}s ago"
    if age_s < 5400:
        return f"{round(age_s / 60)}m ago"
    if age_s < 129600:
        return f"{round(age_s / 3600)}h ago"
    return f"{round(age_s / 86400)}d ago"


def as_of(ts: float | None, now: float) -> str:
    """The freshness tag every board-derived claim must carry."""
    if ts is None:
        return "as of unknown age"
    return f"as of {age_str(max(0.0, now - ts))}"


def _mddb_search(url: str, collection: str, query: str = "",
                 limit: int = 100) -> list[dict]:
    req = urllib.request.Request(
        url.rstrip("/") + "/search",
        data=json.dumps({"collection": collection, "query": query,
                         "limit": limit}).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        v = json.load(r)
    return v if isinstance(v, list) else []


def _doc_body(doc: dict) -> dict | None:
    try:
        body = json.loads(doc.get("contentMd", "{}"))
    except (TypeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _body_ts(body: dict) -> float | None:
    return _parse_ts(body.get("ts"))


def live_probe(slug: str, *, heartbeat_docs: list | None = None,
               ops_url: str = OPS_MDDB, now: float | None = None) -> dict:
    """Fresh telemetry for the host. kk-mac goes through the lane
    admission snapshot (same view the dispatchers gate on); every other
    host gets the freshest matching ada-nest-heartbeats doc."""
    now = time.time() if now is None else now
    live = {"source": None, "fetched": False, "online": None,
            "heartbeat_age_s": None}
    try:
        if slug == "kk-mac" and kk_mac_admission is not None:
            snap = kk_mac_admission.snapshot(
                host=HEARTBEAT_HOST[slug],
                docs=heartbeat_docs, url=ops_url, now=now,
                ssh_fallback=False)
            age = snap.get("heartbeat_age_s")
            live.update({
                "source": "kk_mac_lane_probe",
                "fetched": True,
                "online": (age is not None
                           and age <= HEARTBEAT_FRESH_S),
                "heartbeat_age_s": age,
                "heartbeat_age": age_str(age),
                "eligible": snap.get("eligible"),
                "reasons": snap.get("reasons"),
                "disk_free_gb": snap.get("disk_free_gb"),
                "ollama_ok": snap.get("ollama_ok"),
                "load_1m": snap.get("load_1m"),
                "cpu_temp_c": snap.get("cpu_temp_c"),
                "node_busy": snap.get("node_busy"),
            })
            return live
        docs = (heartbeat_docs if heartbeat_docs is not None
                else _mddb_search(ops_url, HEARTBEAT_COLLECTION))
        bodies = [b for b in (_doc_body(d) for d in docs) if b]
        slug_toks = _tokens(slug) | {slug}
        cand = [b for b in bodies
                if _norm(b.get("host")) in slug_toks]
        if slug == "kk-mac":  # tailnet-ip alias docs for the mac
            cand += [b for b in bodies
                     if b.get("tailnet_ip") == "100.108.217.17"]
        body = max(cand, key=lambda b: _body_ts(b) or 0,
                   default=None)
        if body is None:
            live.update({"source": "ada-nest-heartbeats",
                         "fetched": True, "online": None})
            return live
        ts = _body_ts(body)
        age = max(0.0, now - ts) if ts else None
        live.update({
            "source": "ada-nest-heartbeats",
            "fetched": True,
            "online": (age is not None and age <= HEARTBEAT_FRESH_S),
            "heartbeat_age_s": round(age, 1) if age is not None else None,
            "heartbeat_age": age_str(age),
            "disk_free_gb": body.get("disk_free_gb"),
            "ollama_ok": body.get("ollama_ok"),
            "load_1m": body.get("load_1m"),
            "cpu_temp_c": body.get("cpu_temp_c"),
            "node_busy": bool(body.get("tmux_jobs"))
            if body.get("tmux_jobs") is not None else None,
        })
        return live
    except Exception as exc:  # fail soft — probes never kill the answer
        live["error"] = f"{type(exc).__name__}: {exc}"
        return live


def nest_page(slug: str, *, cms_docs: list | None = None,
              cms_url: str = CMS_MDDB, now: float | None = None) -> dict:
    """nest-mgr publishes ada-cms-pages/nest-<host> — its presence and
    freshness are a live surface (the daemon republishes on state
    change and every PUBLISH_S)."""
    now = time.time() if now is None else now
    out = {"found": None}
    try:
        docs = (cms_docs if cms_docs is not None else _mddb_search(
            cms_url, NEST_COLLECTION, query=f"nest-{slug}"))
        # the page slug is nest-<short hostname> — try every alias
        wants = {f"nest-{slug}"} | {f"nest-{t}" for t in _tokens(slug)}
        hit = None
        for d in docs:
            meta = d.get("meta") or {}
            title = str(d.get("title") or "")
            slug_v = str(d.get("slug") or (meta.get("slug") or [""])[0])
            if _norm(slug_v) in wants or _norm(title) in wants:
                hit = d
                break
        if hit is None:
            out["found"] = False
            return out
        meta = hit.get("meta") or {}
        raw = None
        for k in ("updated", "ts", "modified", "date"):
            v = meta.get(k) or hit.get(k)
            if isinstance(v, list):
                v = v[0] if v else None
            if v:
                raw = v
                break
        ts = _parse_ts(raw)
        out.update({
            "found": True,
            "title": str(hit.get("title") or want),
            "page_age_s": (round(now - ts, 1)
                           if ts is not None else None),
            "page_age": age_str(now - ts if ts is not None else None),
        })
        return out
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


def load_cards_dir(cards_dir: Path | str) -> list[dict]:
    out = []
    for p in sorted(Path(cards_dir).glob("*.yml")):
        try:
            c = yaml.load(p.read_text(), Loader=_YamlLoader)
        except Exception:
            continue
        if isinstance(c, dict):
            c.setdefault("id", p.stem)
            out.append(c)
    return out


def default_cards() -> list[dict]:
    """cards.json (rendered dump, one file) first — a render lag of a
    few minutes is acceptable for a status answer; the canonical YAML
    dir is the fallback."""
    try:
        payload = json.loads(CARDS_JSON.read_text())
        cards = payload.get("cards")
        if isinstance(cards, list):
            return [c for c in cards if isinstance(c, dict)]
    except Exception:
        pass
    return load_cards_dir(CARD_DIR)


def board_records(cards: list[dict], slug: str, *,
                  now: float, limit: int = MAX_RECORDS) -> list[dict]:
    """Newest board statements mentioning the host, each tagged with
    its record age. Comms + request asks only — spec/title mentions are
    context, not claims."""
    toks = _tokens(slug)
    recs = []
    for c in cards or []:
        cid = c.get("id")
        for e in c.get("comms") or []:
            if not isinstance(e, dict):  # legacy string comms
                e = {"text": e}
            text = str(e.get("text") or "")
            if not text or not _mentions(text, toks):
                continue
            recs.append({"kind": "comm", "card": cid,
                         "at": e.get("at"), "from": e.get("from"),
                         "text": text[:240], "ts": _parse_ts(e.get("at"))})
        for r in c.get("requests") or []:
            if not isinstance(r, dict):
                continue
            text = str(r.get("ask") or "")
            if not text or not _mentions(text, toks):
                continue
            recs.append({"kind": "request", "card": cid,
                         "at": r.get("at"), "from": r.get("from"),
                         "text": text[:240], "ts": _parse_ts(r.get("at"))})
    recs.sort(key=lambda r: (r["ts"] is None, -(r["ts"] or 0)))
    for r in recs:
        r["age_s"] = (round(now - r["ts"], 1)
                      if r["ts"] is not None else None)
        r["as_of"] = as_of(r["ts"], now)
    return recs[:limit]


def latest_claim(cards: list[dict], slug: str, *, now: float,
                 scan: int = 40) -> dict | None:
    """Newest host-STATE claim on the board — the record that would
    mislead if parroted. Scans deeper than board_records' display cap
    so an older claim is still age-tagged and conflict-checked."""
    recs = board_records(cards, slug, now=now, limit=scan)
    return next((r for r in recs if _is_claim(r["text"])), None)


def processing(cards: list[dict], slug: str, *, now: float) -> list[dict]:
    """Cards the board says this host's runner is working right now.
    Board-sourced — the claim `since` age is attached so a dead runner's
    stuck claim reads as stale, not current."""
    out = []
    for c in cards or []:
        a = c.get("action") or {}
        if not isinstance(a, dict):
            continue
        if a.get("status") != "running":
            continue
        if canon_host(a.get("runner") or "") != slug:
            continue
        claim = c.get("claim") or {}
        ts = _parse_ts(claim.get("since") or c.get("updated"))
        out.append({
            "card": c.get("id"), "title": c.get("title"),
            "runner": a.get("runner"), "since": claim.get("since"),
            "as_of": as_of(ts, now),
        })
    return out


def _disk_figures(text: str) -> list[float]:
    return [float(x) for m in DISK_RE.finditer(text)
            for x in m.groups() if x]


def detect_conflicts(records: list[dict], live: dict) -> list[dict]:
    """Board-vs-telemetry contradictions. Both sides always reported —
    the conflict flag is what stops a stale record being parroted."""
    if not live.get("fetched"):
        return []
    online = live.get("online")
    eligible = live.get("eligible")
    live_disk = live.get("disk_free_gb")
    conflicts = []
    for r in records:
        text = r["text"]
        if online and OFFLINE_RE.search(text):
            conflicts.append({
                "kind": "offline_vs_live",
                "board": {"card": r["card"], "as_of": r["as_of"],
                          "text": text},
                "live": (f"online — heartbeat {live.get('heartbeat_age')}"
                         + (", lane probe eligible"
                            if eligible else "")),
                "note": "board record claims the host is down; live "
                        "telemetry contradicts it — the record is stale",
            })
        if online and eligible and BLOCKED_RE.search(text) \
                and not ELIGIBLE_RE.search(text):
            conflicts.append({
                "kind": "blocked_vs_eligible",
                "board": {"card": r["card"], "as_of": r["as_of"],
                          "text": text},
                "live": "lane probe eligible now",
                "note": "board record claims blocked; the live lane "
                        "probe admits work — the blocker has cleared",
            })
        if live_disk is not None:
            for fig in _disk_figures(text):
                if abs(float(live_disk) - fig) > DISK_TOLERANCE_GB:
                    conflicts.append({
                        "kind": "disk_disagree",
                        "board": {"card": r["card"], "as_of": r["as_of"],
                                  "figure_gb": fig, "text": text},
                        "live": f"disk_free_gb={live_disk}",
                        "note": "disk figures disagree beyond "
                                f"{DISK_TOLERANCE_GB:g}GiB — trust the "
                                "live figure",
                    })
                    break
    return conflicts


def _compose(slug: str, live: dict, nest: dict, proc: list[dict],
             records: list[dict], claim: dict | None,
             conflicts: list[dict]) -> str:
    parts = []
    if live.get("fetched") and live.get("online"):
        seg = f"{slug} is ONLINE (live {live.get('source')}): "
        seg += f"heartbeat {live.get('heartbeat_age')}"
        if live.get("eligible") is not None:
            seg += (", lane probe eligible"
                    if live["eligible"]
                    else f", probe NOT eligible "
                         f"({'+'.join(live.get('reasons') or [])})")
        if live.get("disk_free_gb") is not None:
            seg += f", {live['disk_free_gb']}GiB free"
        if live.get("ollama_ok") is not None:
            seg += ", ollama " + ("ok" if live["ollama_ok"] else "down")
        if live.get("node_busy") is not None:
            seg += ", node " + ("busy" if live["node_busy"] else "idle")
        parts.append(seg + ".")
    elif live.get("fetched"):
        age = live.get("heartbeat_age")
        parts.append(
            f"{slug}: live telemetry shows no fresh heartbeat"
            + (f" (last beat {age})" if age else "")
            + " — host looks down/unprobed right now.")
    else:
        parts.append(
            f"{slug}: no live telemetry reachable "
            f"({live.get('error', 'no probe')}) — falling back to board "
            "records; treat figures as stale-prone.")
    if nest.get("found"):
        parts.append(f"nest-mgr page nest-{slug} last published "
                     f"{nest.get('page_age')}.")
    if proc:
        ids = ", ".join(
            f"{p['card']} ({p['as_of'].replace('as of ', '')})"
            for p in proc)
        parts.append(f"board claims it is running: {ids}.")
    if records:
        bits = "; ".join(
            f"card {r['card']} ({r['as_of']}): \"{r['text'][:140]}\""
            for r in records[:3])
        parts.append(f"latest board records — {bits}.")
    if claim and claim not in records[:3]:
        parts.append(
            f"newest board host-state claim — card {claim['card']} "
            f"({claim['as_of']}): \"{claim['text'][:160]}\".")
    for c in conflicts:
        b = c["board"]
        parts.append(
            f"CONFLICT [{c['kind']}]: card {b['card']} said "
            f"\"{b['text'][:120]}\" ({b['as_of']}) but live telemetry "
            f"says {c['live']} — the board record is stale, prefer the "
            "live figure.")
    return " ".join(parts)


def host_status(host: str, *, now: float | None = None,
                cards: list | None = None,
                cards_dir: Path | str | None = None,
                heartbeat_docs: list | None = None,
                nest_docs: list | None = None,
                ops_url: str = OPS_MDDB,
                cms_url: str = CMS_MDDB,
                live: dict | None = None,
                board_only: bool = False) -> dict:
    """Compose the answer. Live surfaces first; board records tagged;
    contradictions flagged. All inputs injectable for tests."""
    now = time.time() if now is None else now
    slug = canon_host(host)
    if cards is None:
        cards = (load_cards_dir(cards_dir) if cards_dir
                 else default_cards())
    if live is None:
        live = ({"fetched": False, "source": None, "online": None,
                 "error": "board_only"} if board_only else
                live_probe(slug, heartbeat_docs=heartbeat_docs,
                           ops_url=ops_url, now=now))
    nest = ({"found": None} if board_only else
            nest_page(slug, cms_docs=nest_docs, cms_url=cms_url, now=now))
    proc = processing(cards, slug, now=now)
    records = board_records(cards, slug, now=now)
    claim = latest_claim(cards, slug, now=now)
    # conflict-check the newest state claim too even when it fell
    # outside the displayed records
    conflict_inputs = list(records)
    if claim and all(r["text"] != claim["text"]
                     or r["card"] != claim["card"]
                     for r in conflict_inputs):
        conflict_inputs.append(claim)
    conflicts = detect_conflicts(conflict_inputs, live)
    answer = _compose(slug, live, nest, proc, records, claim, conflicts)
    return {
        "ok": True,
        "host": slug,
        "queried_at": datetime.fromtimestamp(now).isoformat(
            timespec="seconds"),
        "confidence": ("live" if live.get("online")
                       else "board_only"),
        "contradiction": bool(conflicts),
        "live": live,
        "nest_mgr": nest,
        "processing": proc,
        "board_records": records,
        "latest_claim": claim,
        "conflicts": conflicts,
        "answer": answer,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("host")
    ap.add_argument("--text", action="store_true",
                    help="print only the composed answer")
    ap.add_argument("--board-only", action="store_true",
                    help="skip live probes (offline/debug)")
    ap.add_argument("--cards-dir", default=None)
    ap.add_argument("--ops-url", default=OPS_MDDB)
    ap.add_argument("--cms-url", default=CMS_MDDB)
    args = ap.parse_args(argv)
    out = host_status(args.host, cards_dir=args.cards_dir,
                      ops_url=args.ops_url, cms_url=args.cms_url,
                      board_only=args.board_only)
    if args.text:
        print(out["answer"])
    else:
        print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
