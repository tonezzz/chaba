#!/usr/bin/env python3
"""line-digest.py — weekly per-member LINE digest push (Ghost-newsletter
equivalent for chaba-cms, card cmssurface-render-digest).

Tony's call 2026-10-14: PER-MEMBER LINE pushes, not a family group —
"kk-ha is an office, not a home". Recipients resolve from the member /
person registry (docs/ssot/apps/ssot.apps.ada-persons.yml); the relay
itself maps person name -> userId via its caller/alias tables.

Sources (each contributes <=2 bullet lines, window = last --days):
  house-timeline  device leaves updated in window (per member collection)
  media-inbox     receipt leaves added in window (media-* docs, excl -extract)
  news digests    *-digest rollups refreshed in window -> link
  kanban done     cards with column=done updated in window (board-api /cards)
  render_job      WP boards render_job posts in window (needs
                  ~/.config/secrets/wp-boards.env; skipped silently when
                  absent or the CPT isn't REST-visible)

Idempotency: message_id = line-digest-<member>-<ISOyear>w<ISOweek>; sent
ids persist in --state (default ~/.local/share/ada/line-digest.json) so a
re-run or a timer+manual overlap never double-pushes. The relay ignores
the field — dedup is ours.

Push path: POST <relay>/send {to, instance, text, message_id} — same
loopback endpoint chat_send uses; `to` is the person name (relay resolves
display-name / LINE_PERSON_ALIASES / caller names), `instance` the
member's lane so LINE_LANE_LOCK/ALLOW apply.

Rollout gate (spec VERIFY): default --members is `tony` only. Per-member
recipients turn on by extending LINE_DIGEST_MEMBERS after Tony eyeballs a
DRY-RUN — do not widen it in the unit until approved.

Usage:
  line-digest.py --dry-run                 # render Tony's digest, print
  line-digest.py --members tony,kk --days 7
  LINE_DIGEST_MEMBERS=tony line-digest.py

Env:
  MDDB_CMS_URL        CMS plane (default http://127.0.0.1:11027/v1)
  LINE_RELAY_URL      default http://127.0.0.1:8912/send
  LINE_DIGEST_MEMBERS comma list (default tony)
  LINE_DIGEST_SITE    public base for page links
                      (default https://cms.surf-thailand.com)
  BOARD_API_CARDS     default https://tony-dell.taila0626a.ts.net/apps/board-api/cards
  WP_BOARDS_ENV       wp creds file (render_job source)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

MDDB = os.environ.get(
    "MDDB_CMS_URL", "http://127.0.0.1:11027/v1").rstrip("/")
RELAY = os.environ.get("LINE_RELAY_URL", "http://127.0.0.1:8912/send")
SITE = os.environ.get("LINE_DIGEST_SITE",
                      "https://cms.surf-thailand.com").rstrip("/")
BOARD_CARDS = os.environ.get(
    "BOARD_API_CARDS",
    "https://tony-dell.taila0626a.ts.net/apps/board-api/cards")
STATE = Path(os.environ.get(
    "LINE_DIGEST_STATE",
    "~/.local/share/ada/line-digest.json")).expanduser()
PERSONS_YML = Path(__file__).resolve().parents[2] / \
    "docs/ssot/apps/ssot.apps.ada-persons.yml"
WP_ENV = Path(os.environ.get(
    "WP_BOARDS_ENV", "~/.config/secrets/wp-boards.env")).expanduser()

# Member -> lane. Collection is the member's CMS lane; `instance` is the
# relay persona so lane locks/allowlists apply; `lang` picks the digest's
# own strings. Registry membership is still sourced from the persons
# SSOT — a name missing there warns and is skipped.
MEMBERS = {
    "tony": {"collection": "ada-cms-pages", "instance": "tony",
             "lang": "en"},
    "kk": {"collection": "ada-cms-pages-kk", "instance": "kk",
           "lang": "th"},
    "testo": {"collection": "ada-cms-pages", "instance": "testo",
              "lang": "en"},
    "nhong": {"collection": "ada-cms-pages", "instance": "nhong",
              "lang": "th"},
}

TXT = {
    "en": {"home": "home", "media": "media-inbox", "news": "news",
           "kanban": "kanban", "renders": "renders", "full": "full index",
           "devices": "devices", "items": "items", "cards done": "cards done",
           "week": "chaba week"},
    "th": {"home": "บ้าน", "media": "กล่องสื่อ", "news": "ข่าว",
           "kanban": "งานบอร์ด", "renders": "วิดีโอเรนเดอร์",
           "full": "สารบัญทั้งหมด", "devices": "อุปกรณ์",
           "items": "รายการ", "cards done": "การ์ดเสร็จ",
           "week": "ชบาสัปดาห์นี้"},
}

ICT = dt.timezone(dt.timedelta(hours=7))


def _post(base: str, path: str, payload: dict, timeout: float = 30):
    req = urllib.request.Request(
        f"{base.rstrip('/')}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def list_docs(collection: str) -> list[dict]:
    docs, offset = [], 0
    while True:
        page = _post(MDDB, "search", {"collection": collection, "query": "",
                                      "limit": 500, "offset": offset})
        if isinstance(page, dict):
            page = page.get("documents") or page.get("docs") or []
        docs += page
        if len(page) < 500:
            return docs
        offset += 500


def meta1(meta: dict, name: str) -> str:
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v is not None else ""


def persons() -> set[str]:
    """Person keys from the registry (tony, kk, testo, nhong, …)."""
    try:
        import yaml
        reg = yaml.safe_load(PERSONS_YML.read_text()) or {}
        return {k for k in (reg.get("persons") or {})
                if k not in ("default", "unknown", "guest")}
    except Exception:
        return set()


# ---------- sources: each -> list[str] bullet lines ----------


def src_house_timeline(docs, since_ts, t):
    n = sum(1 for d in docs
            if d.get("key", "").startswith("house-timeline-")
            and d.get("key") != "house-timeline-qc"
            and (d.get("updatedAt") or 0) >= since_ts)
    if not n:
        return []
    return [f"• {t['home']}: {n} {t['devices']} — "
            f"{SITE}/p/house-timeline"]


def src_media_inbox(docs, since_ts, t):
    n = sum(1 for d in docs
            if d.get("key", "").startswith("media-")
            and d["key"] not in ("media-inbox", "media-inbox-qc")
            and not d["key"].endswith("-extract")
            and (d.get("addedAt") or 0) >= since_ts)
    if not n:
        return []
    return [f"• {t['media']}: {n} {t['items']} — {SITE}/p/media-inbox"]


def src_news(docs, since_ts, t):
    hits = []
    for d in docs:
        key = d.get("key", "")
        if not key.endswith("-digest") or key.count("-digest") > 1:
            continue
        meta = d.get("meta") or {}
        if meta1(meta, "report_role") != "digest":
            continue
        if (d.get("updatedAt") or 0) < since_ts:
            continue
        hits.append(key)
    if not hits:
        return []
    head = hits[0]
    more = f" +{len(hits) - 1}" if len(hits) > 1 else ""
    return [f"• {t['news']}: {head}{more} — {SITE}/k/digest"]


_DONE_COMM = re.compile(r"closed|moved .*done|-> done|auto-?clos", re.I)


def _comm_dt(at: str) -> dt.datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return dt.datetime.strptime(str(at)[:16], fmt) \
                .replace(tzinfo=ICT)
        except ValueError:
            continue
    return None


def src_kanban(since_dt, t):
    """Cards whose done-transition comm landed in the window — 'updated'
    alone counts every card touch, not completions."""
    try:
        req = urllib.request.Request(BOARD_CARDS)
        payload = json.load(urllib.request.urlopen(req, timeout=20))
        cards = payload.get("cards") if isinstance(payload, dict) \
            else payload
        n = 0
        for c in cards or []:
            if c.get("column") != "done":
                continue
            for cm in c.get("comms") or []:
                when = _comm_dt(cm.get("at") or "")
                if when and when >= since_dt \
                        and _DONE_COMM.search(cm.get("text") or ""):
                    n += 1
                    break
        if not n:
            return []
        return [f"• {t['kanban']}: {n} {t['cards done']}"]
    except Exception:
        return []


def _wp_env(path: Path) -> dict:
    env = {}
    try:
        for ln in path.read_text().splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def src_render_jobs(since_dt, t):
    env = _wp_env(WP_ENV)
    if not env.get("WP_SITE_URL") or not env.get("WP_APP_USER"):
        return []
    try:
        base = env["WP_SITE_URL"].rstrip("/")
        tok = base64.b64encode(
            f"{env['WP_APP_USER']}:{env['WP_APP_PASSWORD']}".encode()
        ).decode()
        route = ("/wp/v2/render_job?per_page=20&_fields=date,title"
                 f"&after={since_dt.astimezone(dt.timezone.utc):%Y-%m-%dT%H:%M:%S}")
        req = urllib.request.Request(
            f"{base}/index.php?rest_route={route}",
            headers={"Authorization": f"Basic {tok}"})
        posts = json.load(urllib.request.urlopen(req, timeout=20))
        if not isinstance(posts, list) or not posts:
            return []
        n = len(posts)
        first = re.sub(r"<[^>]+>", "",
                       str(posts[0].get("title", {}).get("rendered", "")))
        return [f"• {t['renders']}: {n} — {first[:60]}"]
    except Exception:
        return []


# ---------- build + send ----------


def build_digest(member: str, days: int) -> str | None:
    spec = MEMBERS[member]
    t = TXT[spec["lang"]]
    since_dt = dt.datetime.now(ICT) - dt.timedelta(days=days)
    since_ts = since_dt.timestamp()
    try:
        docs = list_docs(spec["collection"])
    except Exception:
        return None
    lines = []
    for fn in (src_house_timeline, src_media_inbox, src_news):
        lines += fn(docs, since_ts, t)
    lines += src_kanban(since_dt, t)
    lines += src_render_jobs(since_dt, t)
    if not lines:
        return None
    span = f"{since_dt:%Y-%m-%d} → {dt.datetime.now(ICT):%m-%d}"
    return "\n".join([f"📋 {t['week']} {span}", *lines,
                      f"{t['full']}: {SITE}/"])


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_state(path: Path, st: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, indent=1, sort_keys=True))


def send(relay: str, member: str, text: str, message_id: str) -> dict:
    spec = MEMBERS[member]
    payload = {"to": member, "instance": spec["instance"],
               "text": text, "message_id": message_id}
    req = urllib.request.Request(
        relay, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=20))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: "
                f"{e.read()[:200].decode('utf-8', 'replace')}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--members",
                    default=os.environ.get("LINE_DIGEST_MEMBERS", "tony"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--relay-url", default=RELAY)
    ap.add_argument("--state", type=Path, default=STATE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="resend even if message_id already in state")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    known = persons()
    iso = dt.datetime.now(ICT).isocalendar()
    state = load_state(a.state)
    results = []
    for member in [m.strip() for m in a.members.split(",") if m.strip()]:
        if member not in MEMBERS:
            results.append({"member": member, "ok": False,
                            "error": "no lane mapping"})
            continue
        if known and member not in known:
            results.append({"member": member, "ok": False,
                            "error": "not in persons registry"})
            continue
        mid = f"line-digest-{member}-{iso.year}w{iso.week:02d}"
        text = build_digest(member, a.days)
        if text is None:
            results.append({"member": member, "ok": True,
                            "skipped": "no sources / mddb unreachable"})
            continue
        if a.dry_run:
            results.append({"member": member, "ok": True, "dry_run": True,
                            "message_id": mid, "chars": len(text),
                            "text": text})
            continue
        if not a.force and mid in state:
            results.append({"member": member, "ok": True,
                            "skipped": f"already sent ({mid})"})
            continue
        res = send(a.relay_url, member, text, mid)
        rec = {"member": member, "ok": bool(res.get("ok")),
               "message_id": mid, "chars": len(text)}
        if not res.get("ok"):
            rec["error"] = res.get("error")
        else:
            state[mid] = {"at": dt.datetime.now(dt.timezone.utc)
                          .isoformat(timespec="seconds"),
                          "to": member}
            save_state(a.state, state)
        results.append(rec)
    print(json.dumps(results, ensure_ascii=False, indent=1)
          if a.json else "\n".join(
              (f"[{r['member']}] " +
               (r.get("text") or
                ("dry-run " if r.get("dry_run") else "") +
                ("OK " if r["ok"] else "FAIL ") +
                (r.get("skipped") or r.get("message_id") or
                 r.get("error") or "")))
              for r in results))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
