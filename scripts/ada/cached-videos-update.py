#!/usr/bin/env python3
"""cached-videos-update.py — yt-live media cache -> CMS `cached-videos-report`.

Scans the real cache dirs on tony-dell and renders the managed
<!-- cachedvideos:auto --> block:

  - ~/.cache/yt-live-media/<videoId>.<variant>/ — real cached media.
    A dir only counts as real when its info.json's `id` matches the dir
    name prefix; mismatches/bare dirs are listed as "misplaced" so junk
    can't masquerade as cached videos.
  - ~/.cache/yt-live-subs/*.vtt — subtitle history (video id + langs).

Publishes en+th to ada-cms-pages, updates the ada-cms-automation
registry doc. Stdlib only — same contract as market-report-update.py.

Env:
    MDDB_BASE_URL   default http://100.102.134.91:11023/v1
    YT_MEDIA_CACHE  default ~/.cache/yt-live-media
    YT_SUBS_CACHE   default ~/.cache/yt-live-subs

Usage:
    cached-videos-update.py            # gated by registry interval
    cached-videos-update.py --force    # run regardless
    cached-videos-update.py --dry-run  # render + print, write nothing
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
MCACHE = Path(os.environ.get(
    "YT_MEDIA_CACHE", os.path.expanduser("~/.cache/yt-live-media")))
SCACHE = Path(os.environ.get(
    "YT_SUBS_CACHE", os.path.expanduser("~/.cache/yt-live-subs")))
APPDIR = Path(os.environ.get(
    "YT_LIVE_APPDIR",
    os.path.expanduser("~/CascadeProjects/chaba-tony-dell/"
                       "stacks/web/public/apps/yt-live")))
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
PAGE = "cached-videos-report"
BLOCK_BEGIN = "<!-- cachedvideos:auto -->"
BLOCK_END = "<!-- /cachedvideos:auto -->"
ICT = timezone(timedelta(hours=7))
SOURCES = ["~/.cache/yt-live-media", "~/.cache/yt-live-subs"]
VID_RE = re.compile(r"^[A-Za-z0-9_-]{6,15}\.")


# ---------- MDDB ----------

def _post(path, payload, timeout=60):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _search_all(collection, page_size=500):
    docs, offset = [], 0
    while True:
        page = _post("search", {"collection": collection, "query": "",
                                "limit": page_size, "offset": offset})
        docs += page
        if len(page) < page_size:
            return docs
        offset += page_size


def get_page(lang):
    docs = _search_all(COLLECTION)
    return next((d for d in docs
                 if d.get("key") == PAGE and d.get("lang") == lang), None)


# ---------- scan ----------

def _dir_size(path):
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _fmt_size(n):
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}G"


def scan_cache():
    """(real entries, misplaced dirs, sub list)."""
    real, stray = [], []
    try:
        dirs = sorted(MCACHE.iterdir())
    except OSError:
        dirs = []
    for d in dirs:
        if not d.is_dir():
            continue
        name = d.name
        vid = name.split(".", 1)[0]
        variant = name.split(".", 1)[1] if "." in name else "?"
        info = {}
        try:
            info = json.loads((d / "info.json").read_text())
        except Exception:
            pass
        mtime = datetime.fromtimestamp(d.stat().st_mtime, ICT)
        if info.get("id") == vid:
            real.append({
                "id": vid, "variant": variant,
                "title": info.get("title") or vid,
                "complete": (d / "complete").exists(),
                "size": _dir_size(d), "mtime": mtime,
                "url": info.get("webpage_url")
                       or f"https://youtu.be/{vid}",
            })
        else:
            stray.append({"name": name, "size": _dir_size(d),
                          "mtime": mtime})

    subs = []
    try:
        for f in sorted(SCACHE.iterdir(), key=lambda p: -p.stat().st_mtime):
            if f.suffix == ".vtt":
                subs.append({"file": f.name,
                             "mtime": datetime.fromtimestamp(
                                 f.stat().st_mtime, ICT)})
    except OSError:
        pass
    return real, stray, subs


def scan_playables():
    """Dub/demo assets served at /apps/yt-live/ — what Ada can actually
    play on a screen."""
    out = []
    try:
        for f in sorted(APPDIR.iterdir(), key=lambda p: -p.stat().st_mtime):
            if f.name.endswith("-dub.mp4") or f.name.startswith("dub-v"):
                out.append({"file": f.name, "size": f.stat().st_size,
                            "mtime": datetime.fromtimestamp(
                                f.stat().st_mtime, ICT)})
    except OSError:
        pass
    return out


# ---------- render ----------

def render_block(now, en=True):
    real, stray, subs = scan_cache()
    playables = scan_playables()
    total = sum(e["size"] for e in real) + sum(e["size"] for e in stray)
    L = [BLOCK_BEGIN]
    if en:
        L.append(f"_Updated {now.strftime('%Y-%m-%d %H:%M ICT')} · "
                 f"{len(real)} cached · {len(subs)} subtitled · "
                 f"{_fmt_size(total)} on disk_\n")
        L.append("## Cached media\n")
        if real:
            L.append("| Video | Variant | Size | Cached | Status |")
            L.append("|---|---|---|---|---|")
            for e in real:
                L.append(
                    f"| [{e['title'][:60]}]({e['url']}) "
                    f"| {e['variant']} | {_fmt_size(e['size'])} "
                    f"| {e['mtime'].strftime('%m-%d %H:%M')} "
                    f"| {'✅ complete' if e['complete'] else '⏳ partial'} |")
        else:
            L.append("_Cache is empty._")
        if stray:
            L.append(f"\n### Misplaced dirs ({len(stray)} — not real "
                     "cache entries)\n")
            for s in stray:
                L.append(f"- `{s['name']}/` — {_fmt_size(s['size'])}, "
                         f"{s['mtime'].strftime('%Y-%m-%d')} "
                         "(no matching info.json — probably a copied "
                         "app dir; safe to review/clean)")
        if playables:
            L.append(f"\n### Playable dubs ({len(playables)} — served at "
                     "`/apps/yt-live/`)\n")
            L.append("| File | Size | Updated |")
            L.append("|---|---|---|")
            for p in playables[:25]:
                L.append(f"| `{p['file']}` | {_fmt_size(p['size'])} "
                         f"| {p['mtime'].strftime('%Y-%m-%d %H:%M')} |")
        if subs:
            L.append(f"\n### Subtitle library ({len(subs)})\n")
            L.append("| Video id / langs | Updated |")
            L.append("|---|---|")
            for s in subs[:25]:
                L.append(f"| `{s['file'].replace('.vtt','')}` "
                         f"| {s['mtime'].strftime('%Y-%m-%d %H:%M')} |")
    else:
        L.append(f"_อัปเดต {now.strftime('%Y-%m-%d %H:%M ICT')} · "
                 f"แคช {len(real)} รายการ · ซับ {len(subs)} ไฟล์_\n")
        L.append("## สื่อที่แคชไว้\n")
        if real:
            for e in real:
                L.append(f"- **{e['title'][:60]}** ({e['variant']}, "
                         f"{_fmt_size(e['size'])}) — "
                         f"{'สมบูรณ์' if e['complete'] else 'ไม่สมบูรณ์'}")
        else:
            L.append("_แคชว่าง_")
        if stray:
            L.append(f"\nมีไดเรกทอรีที่วางผิดที่ {len(stray)} รายการ")
    L.append(BLOCK_END)
    summary = {"cached": len(real), "subtitles": len(subs),
               "playables": len(playables),
               "stray_dirs": len(stray),
               "bytes": total}
    return "\n".join(L) + "\n", summary


BLOCK_RE = re.compile(
    re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), re.S)


def apply_block(body, block):
    if BLOCK_RE.search(body or ""):
        return BLOCK_RE.sub(lambda m: block, body, count=1)
    m = re.search(r"^## ", body or "", re.M)
    if m:
        return body[:m.start()] + block + "\n\n" + body[m.start():]
    return (body or "").rstrip() + "\n\n" + block + "\n"


def publish(lang, body, now):
    doc = get_page(lang) or {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta.update({
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": [lang],
        "kind": ["report"],
        "attribute": ["report"],
        "report_role": ["rollup"],
        "generated_by": ["cached-videos-update.py"],
        "sources": SOURCES,
        "title": ["Cached Videos" if lang == "en"
                  else "วิดีโอที่แคชไว้"],
        "written_by": ["cached-videos-update"],
    })
    _post("add", {"collection": COLLECTION, "key": PAGE, "lang": lang,
                  "contentMd": body, "meta": meta}, timeout=120)


def save_registry(cfg, now):
    meta = {"kind": ["automation-config"], "bank": ["cms"],
            "scope": ["tony"], "status": ["active"], "source": ["api"],
            "written_by": ["cached-videos-update"], "subject": [PAGE],
            "attribute": ["automation"], "slug": [PAGE],
            "title": [f"CMS automation: {PAGE}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("add", {"collection": REGISTRY, "key": PAGE, "lang": "en",
                  "contentMd": json.dumps(cfg, ensure_ascii=False,
                                          indent=2),
                  "meta": meta}, timeout=120)


def load_registry():
    try:
        docs = _search_all(REGISTRY)
    except Exception as e:
        print(f"warn: registry unreachable ({e}) — running anyway",
              file=sys.stderr)
        return {}, False
    for d in docs:
        if d.get("key") == PAGE:
            try:
                return json.loads(d.get("contentMd") or "{}"), True
            except json.JSONDecodeError:
                return {}, True
    return {}, True


def gated(cfg, now, force):
    if not cfg.get("enabled", True):
        return "disabled"
    if force or cfg.get("run_now"):
        return None
    interval = int(cfg.get("interval_min") or 0)
    last = cfg.get("last_run")
    if interval and last:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if now < last_dt + timedelta(minutes=interval, seconds=-30):
                return f"interval (last run {last})"
        except ValueError:
            pass
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now_utc = datetime.now(timezone.utc)
    now = now_utc.astimezone(ICT)
    cfg, reg_up = load_registry()
    why = gated(cfg, now_utc, args.force)
    if why:
        print(f"cached-videos: skipped ({why})")
        return 0

    status, error = "ok", None
    try:
        en_block, summary = render_block(now, en=True)
        th_block, _ = render_block(now, en=False)

        en_body = apply_block((get_page("en") or {}).get("contentMd") or
                              "# Cached Videos\n", en_block)
        th_body = apply_block((get_page("th") or {}).get("contentMd") or
                              "# วิดีโอที่แคชไว้\n", th_block)

        if args.dry_run:
            print(en_block)
            print("---")
            print(th_block)
            print(json.dumps(summary, ensure_ascii=False))
            return 0

        publish("en", en_body, now_utc)
        publish("th", th_body, now_utc)
        print(f"published {PAGE} en+th — {summary['cached']} cached, "
              f"{summary['subtitles']} subs, {summary['stray_dirs']} stray")

        if reg_up:
            st = dict(cfg)
            st.update({"run_now": False,
                       "last_run": now_utc.isoformat(timespec="seconds"),
                       "last_status": status,
                       "generated_by": "cached-videos-update.py",
                       "pages": [PAGE],
                       "owner": "cached-videos-update.py",
                       "schedule": "every 30m (chaba-cached-videos.timer)"})
            save_registry(st, now_utc)
    except Exception as e:
        status, error = "error", str(e)
        print(f"error: {e}", file=sys.stderr)
        if reg_up and not args.dry_run:
            try:
                st = dict(cfg)
                st.update({"run_now": False,
                           "last_run": now_utc.isoformat(timespec="seconds"),
                           "last_status": "error",
                           "last_error": str(e)[:500]})
                save_registry(st, now_utc)
            except Exception:
                pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
