#!/usr/bin/env python3
"""QC scoreboard — one roll-up of every quality counter we already keep.

Today the counts live scattered: repeat-asks register, the wp-admin
broken-render widget, the optimize gate's warnings JSON, audit-fail cards,
board open-requests. This node pulls them into one durable artifact +
meta + CMS page so "is quality trending up or down" is a glance, not a dig.

Outputs:
  reports/qc-scoreboard/QC-SCOREBOARD-<date>.md   durable markdown
  reports/meta.qc-scoreboard.yml                L2-domain node meta
  ada-cms-pages/qc-scoreboard                   CMS page (kind:report)

Runs on tony-dell (needs the served card dir + board-api + wp-boards.env).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import yaml  # noqa: E402

from lib.report import now_iso, write_meta  # noqa: E402

NODE = "qc-scoreboard"
LAYER = "L2-domain"
OUT_DIR = REPO / "reports" / "qc-scoreboard"
META = REPO / "reports" / f"meta.{NODE}.yml"
CMS_SLUG = "qc-scoreboard"
BOARD_API = os.environ.get("BOARD_API", "http://127.0.0.1:8787").rstrip("/")
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")
SERVED_ROOT = Path("/home/tony/CascadeProjects/chaba-tony-dell")
CARDS_DIR = SERVED_ROOT / "docs" / "ssot" / "kanban" / "cards"
REPEAT_ASKS = SERVED_ROOT / "docs" / "ssot" / "ssot.repeat-asks.yml"
OPT_WARNINGS = SERVED_ROOT / "reports" / "SSOT_OPTIMIZATION_WARNINGS.json"
WP_ENV = Path.home() / ".config" / "secrets" / "wp-boards.env"

AUDIT_ID_RE = re.compile(r"^(audit-fail|audit-miss|bug|incident|qc)-", re.I)


def _load_env(p: Path) -> dict:
    env = {}
    try:
        for ln in p.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def board_cards() -> list[dict]:
    req = urllib.request.Request(f"{BOARD_API}/cards")
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    return data if isinstance(data, list) else data.get("cards", [])


def wp_render_jobs() -> dict:
    """{total, broken, checked} — broken = status done/ok with missing or
    non-http output_url. Skips gracefully when env is absent."""
    env = _load_env(WP_ENV)
    if not env.get("WP_SITE_URL"):
        return {"checked": False, "note": "wp-boards.env missing"}
    base = env["WP_SITE_URL"].rstrip("/")
    tok = base64.b64encode(
        f"{env['WP_APP_USER']}:{env['WP_APP_PASSWORD']}".encode()).decode()

    def api(route):
        u = base + "/index.php?rest_route=" + urllib.parse.quote(
            route, safe="/&=")
        req = urllib.request.Request(u, headers={
            "Authorization": "Basic " + tok, "User-Agent": "qc-scoreboard/1.0"})
        return json.loads(urllib.request.urlopen(req, timeout=45).read())

    total = broken = 0
    page = 1
    while True:
        posts = api("/wp/v2/render_job&status=private,publish,draft"
                    f"&per_page=100&page={page}")
        if not posts:
            break
        for p in posts:
            total += 1
            m = p.get("meta", {})
            u = str(m.get("output_url", ""))
            if str(m.get("status", "")) in ("done", "ok") and (
                    not u or not re.match(r"https?://", u)):
                broken += 1
        if len(posts) < 100:
            break
        page += 1
    return {"checked": True, "total": total, "broken": broken}


def repeat_asks() -> dict:
    try:
        d = yaml.safe_load(REPEAT_ASKS.read_text()) or {}
    except Exception as e:
        return {"error": f"read failed: {e}"}
    topics = d.get("topics") or []
    total = sum(int(t.get("count") or 0) for t in topics)
    open_t = [t["id"] for t in topics
              if str(t.get("status", "")).startswith(("open", "recurring"))]
    fixed = len(topics) - len(open_t)
    return {"topics": len(topics), "total_asks": total,
            "open": len(open_t), "open_ids": open_t, "fixed": fixed}


def audit_cards(cards: list[dict]) -> dict:
    open_audit = [c.get("id") for c in cards
                  if AUDIT_ID_RE.match(str(c.get("id", "")))
                  and c.get("column") not in ("done", "verified")]
    return {"open": len(open_audit), "open_ids": open_audit}


def open_requests(cards: list[dict]) -> dict:
    n = 0
    for c in cards:
        for r in c.get("requests") or []:
            if isinstance(r, dict) and r.get("status") == "open":
                n += 1
    return {"open": n}


def optimize_warnings() -> dict:
    try:
        d = json.loads(OPT_WARNINGS.read_text())
    except Exception as e:
        return {"error": f"read failed: {e}"}
    cats = {k: len(v) for k, v in d.items()
            if isinstance(v, list) and k != "generated"}
    return {"generated": d.get("generated"), "by_kind": cats,
            "total": sum(cats.values())}


def render_md(m: dict) -> str:
    now = now_iso()[:16]
    ra, rj, ac, oq, ow = (m["repeat_asks"], m["render_jobs"],
                        m["audit_cards"], m["open_requests"],
                        m["opt_warnings"])
    lines = [
        f"# QC Scoreboard — {now}", "",
        "All the quality counters in one place. Details per source are in",
        "the linked artifacts; this page is the glanceable roll-up.", "",
        "## Counters", "",
        "| Counter | Value | Source |",
        "|---|---|---|",
        f"| Repeat-asks (Tony re-asked) | {ra.get('total_asks', '?')} asks across "
        f"{ra.get('topics', '?')} topics ({ra.get('open', '?')} open) | "
        "ssot.repeat-asks.yml |",
        f"| Open audit/incident cards | {ac['open']} | kanban ids "
        "audit-fail-*/audit-miss-*/bug-* |",
        f"| Open board requests | {oq['open']} | board-api /cards |",
    ]
    if rj.get("checked"):
        lines.append(
            f"| Render jobs with broken output | {rj['broken']} of "
            f"{rj['total']} | WP render_job meta |")
    else:
        lines.append(f"| Render jobs | not checked ({rj.get('note')}) | — |")
    if "error" not in ow:
        kinds = ", ".join(f"{k}={v}" for k, v in ow["by_kind"].items())
        lines.append(
            f"| SSOT optimize warnings | {ow['total']} ({kinds}) | "
            f"SSOT_OPTIMIZATION_WARNINGS.json @ {ow.get('generated', '?')[:16]} |")
    else:
        lines.append(f"| SSOT optimize warnings | {ow['error']} | — |")
    lines += ["", "## Open repeat-ask topics", ""]
    for t in ra.get("open_ids", []):
        lines.append(f"- `{t}`")
    if not ra.get("open_ids"):
        lines.append("- none open")
    if ac["open_ids"]:
        lines += ["", "## Open audit/incident cards", ""]
        lines += [f"- `{i}`" for i in ac["open_ids"][:15]]
    return "\n".join(lines) + "\n"


def _mddb_post(path: str, payload: dict, timeout: int = 30):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def publish_cms(md: str, summary: str) -> bool:
    now = now_iso()
    existing = {}
    try:
        existing = _mddb_post("get", {"collection": "ada-cms-pages",
                                      "key": CMS_SLUG, "lang": "en"}) or {}
    except Exception:
        pass
    meta = {k: (v if isinstance(v, list) else [v])
            for k, v in (existing.get("meta") or {}).items()}
    meta.setdefault("bank", ["cms"])
    meta.setdefault("scope", ["tony"])
    meta.setdefault("status", ["active"])
    meta.setdefault("source", ["api"])
    meta.setdefault("subject", [CMS_SLUG])
    meta.setdefault("attribute", ["page"])
    meta.update({
        "kind": ["report"], "slug": [CMS_SLUG],
        "title": [f"QC Scoreboard — {now[:10]}"],
        "format": ["markdown"], "lang": ["en"],
        "updated": [now], "last_verified": [now[:10]],
        "domain": ["ops"], "summary": [summary[:240]],
        "fresh_for": ["12h"], "confidence": ["high"],
        "links": ["system-report", "daily-brief"],
        "written_by": ["qc-scoreboard.py"],
    })
    tl = [x for x in meta.get("timeline", []) if isinstance(x, str)]
    tl.append(f"{now[:16]} scoreboard published")
    meta["timeline"] = tl[-40:]
    _mddb_post("add", {"collection": "ada-cms-pages", "key": CMS_SLUG,
                       "lang": "en", "contentMd": md, "meta": meta},
               timeout=60)
    from lib.cms_index import regen_reports_index
    regen_reports_index(MDDB, written_by="qc-scoreboard.py")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--meta", type=Path, default=META)
    p.add_argument("--output-dir", type=Path, default=OUT_DIR)
    p.add_argument("--no-cms", action="store_true")
    args = p.parse_args()

    cards = []
    try:
        cards = board_cards()
    except Exception as e:
        print(f"warn: board-api unavailable ({e})", file=sys.stderr)

    sync_ra = SERVED_ROOT / "scripts" / "sync-repeat-asks.py"
    if sync_ra.exists():
        try:
            r = subprocess.run([sys.executable, str(sync_ra)],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                print(f"warn: repeat-asks WP sync rc={r.returncode} "
                      f"{r.stderr.strip()[:120]}", file=sys.stderr)
        except Exception as e:
            print(f"warn: repeat-asks WP sync failed ({e})", file=sys.stderr)

    m = {
        "repeat_asks": repeat_asks(),
        "render_jobs": wp_render_jobs(),
        "audit_cards": audit_cards(cards),
        "open_requests": open_requests(cards),
        "opt_warnings": optimize_warnings(),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    day = now_iso()[:10]
    out = args.output_dir / f"QC-SCOREBOARD-{day}.md"
    md = render_md(m)
    out.write_text(md, encoding="utf-8")
    (args.output_dir / "QC-SCOREBOARD.md").write_text(md, encoding="utf-8")

    ra, rj, ac = m["repeat_asks"], m["render_jobs"], m["audit_cards"]
    parts = [f"{ra.get('total_asks', '?')} repeat-asks/{ra.get('open', '?')} open",
             f"{ac['open']} audit cards open",
             f"{m['open_requests']['open']} open requests"]
    if rj.get("checked"):
        parts.append(f"{rj['broken']}/{rj['total']} broken renders")
    summary = "; ".join(parts)
    status = "ok" if (ra.get("open", 0) == 0 and ac["open"] == 0
                      and rj.get("broken", 0) == 0) else "delta"

    write_meta(args.meta, node=NODE, layer=LAYER,
               generated_by="python3 scripts/qc-scoreboard.py",
               status=status, summary=summary,
               purpose="Roll-up of quality counters: repeat-asks, audit "
                       "cards, open requests, broken renders, gate warnings",
               sources=[str(REPEAT_ASKS), str(OPT_WARNINGS),
                        f"{BOARD_API}/cards", "wp: /wp/v2/render_job"],
               extra={k: (v if not isinstance(v, dict) else
                          {kk: vv for kk, vv in v.items()
                           if not isinstance(vv, list)})
                      for k, v in m.items()})
    print(f"wrote {out}")
    print(f"summary: {summary}")

    if not args.no_cms:
        try:
            publish_cms(md, summary)
            print(f"published CMS page '{CMS_SLUG}'")
        except Exception as e:
            print(f"warn: CMS publish failed ({e})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
