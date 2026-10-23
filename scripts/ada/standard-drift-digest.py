#!/usr/bin/env python3
"""standard-drift-digest.py — drift signals -> CMS `standard-drift`.

The feedback layer of the report-first flywheel (card
standard-drift-digest): one page collecting every signal that a
standard is slipping — stale generated reports, board drift, and
tool-surface debt — so Tony reviews ONE digest instead of scattered
fires. Deterministic collectors only; no model call.

Collectors:
  stale_reports   ada-cms-pages docs with generated_by whose
                  updated + meta.fresh_for has lapsed
  board_drift     doing cards stale >STALE_DOING_DAYS, cards with open
                  requests, review pile size
  tool_debt       ada-voice scripts/tool-lint.py --json violations by rule
  orphans         ssot.artifact-lifecycle detector: unreferenced scripts
                  + dead docs, ratcheted vs orphans-baseline.json

Publishes en+th to ada-cms-pages, same contract as kanban-brief.py
(ada-cms-automation registry gating, managed block, meta contract —
ssot.apps.cms-reports.yml).

Env:
    MDDB_BASE_URL     default http://100.102.134.91:11027/v1
    REPO              default = this checkout root
    ADA_PI            default ~/CascadeProjects/ada-voice (lint source)

Usage:
    standard-drift-digest.py            # gated by registry interval
    standard-drift-digest.py --force    # run regardless
    standard-drift-digest.py --dry-run  # render + print, write nothing
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parents[2])
CARDS_DIR = REPO / "docs/ssot/kanban/cards"
ADA_PI = Path(os.environ.get("ADA_PI", Path.home() / "CascadeProjects"
                            / "ada-voice"))
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
REGISTRY = "ada-cms-automation"
PAGE = "standard-drift"
BLOCK_BEGIN = "<!-- standard-drift:auto -->"
BLOCK_END = "<!-- /standard-drift:auto -->"
BLOCK_RE = re.compile(re.escape(BLOCK_BEGIN) + r".*?" +
                      re.escape(BLOCK_END), re.S)
SOURCES = ["ada-cms-pages", "docs/ssot/kanban/cards", "ada-voice tool-lint",
           "repo corpus (scripts + docs, git log)"]
ICT = timezone(timedelta(hours=7))
STALE_DOING_DAYS = 3
MAX_ROWS = 15
# orphans collector (ssot.artifact-lifecycle.yml detect contract)
ORPHAN_BASELINE_NAME = "orphans-baseline.json"
ORPHAN_BASELINE = Path(__file__).resolve().with_name(
    ORPHAN_BASELINE_NAME)
SCRIPT_ORPHAN_EXT = {".py", ".sh"}
DOC_ORPHAN_DIRS = ("docs/kb", "docs/reports", "docs/assessments")
DOC_ORPHAN_MIN_AGE_D = 90
# parked/generated trees never count — neither as candidates nor referrers
_ORPHAN_SKIP = {"__pycache__", "node_modules", ".git",
                "archive", "archived", "processed"}
# dir tokens pointing at corpus roots gesture at the tree, not a file —
# they never rescue a candidate
_NO_PREFIX = {"scripts", "docs"} | set(DOC_ORPHAN_DIRS)
_REF_PATH_RE = re.compile(r"(?:scripts|docs)/[\w.%~@/-]+")
_REF_BASE_RE = re.compile(r"\b[\w][\w@.-]*\.[A-Za-z0-9]{1,8}\b")
_REF_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+([A-Za-z_]\w*(?:\.\w+)*)", re.M)
_REF_DASHM_RE = re.compile(r"(?:^|\s)-m\s+([A-Za-z_]\w*(?:\.\w+)*)")
_REF_SLUG_RE = re.compile(r"[\w@.-]+")


def _slug_stem(rel: str) -> str:
    """Candidate stem when it is a specific slug (contains - or _) —
    bare `report-ada-debug` in a card is a real reference; bare `setup`
    or `events` in prose is not."""
    stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return stem if ("-" in stem or "_" in stem) else ""

# ---------- mddb ----------


def _post(path, payload, timeout=60):
    req = urllib.request.Request(
        f"{MDDB}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or "{}")


def _search_all(collection, page_size=500):
    docs, skip = [], 0
    while True:
        out = _post("/search", {"collection": collection,
                                "limit": page_size, "offset": skip})
        batch = out if isinstance(out, list) else out.get("results", [])
        docs += batch
        if len(batch) < page_size:
            return docs
        skip += page_size


def get_page(lang):
    docs = _search_all(COLLECTION)
    return next((d for d in docs
                 if d.get("key") == PAGE and d.get("lang") == lang), None)


# ---------- collectors ----------

_FRESH_RE = re.compile(r"(\d+)\s*([hdwm])")
_FRESH_UNIT = {"h": 1 / 24, "d": 1, "w": 7, "m": 30}


def _fresh_days(v: str) -> float | None:
    m = _FRESH_RE.match(str(v or "").strip().lower())
    if not m:
        return None
    return int(m.group(1)) * _FRESH_UNIT[m.group(2)]


def _upd_dt(v, naive_tz=timezone.utc) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=naive_tz)
    except (ValueError, TypeError):
        return None


def stale_reports(now: datetime) -> list[dict]:
    """Generated pages past their own fresh_for — the quality_loop input:
    Ada refreshes by tool, structural failures escalate to Devin."""
    out = []
    dead = {"superseded", "archived", "retracted", "expired"}
    for d in _search_all(COLLECTION):
        meta = d.get("meta") or {}
        if not meta.get("generated_by"):
            continue
        status = meta.get("status")
        if isinstance(status, list):
            status = status[0] if status else None
        if status in dead:
            continue
        fresh = meta.get("fresh_for")
        if isinstance(fresh, list):
            fresh = fresh[0] if fresh else None
        days = _fresh_days(fresh)
        if days is None:
            continue
        upd = meta.get("updated") or meta.get("addedAt")
        if isinstance(upd, list):
            upd = upd[0] if upd else None
        dt = _upd_dt(upd)
        if dt is None:
            continue
        age = (now - dt).total_seconds() / 86400
        if age > days:
            out.append({"slug": d.get("key", "?"),
                        "age_d": round(age, 1), "fresh_for": fresh,
                        "by": str(meta.get("generated_by") or "")[:60]})
    # lang variants of one slug share the key — keep the staler of them
    dedup: dict[str, dict] = {}
    for r in out:
        if r["age_d"] > dedup.get(r["slug"], {}).get("age_d", -1):
            dedup[r["slug"]] = r
    return sorted(dedup.values(), key=lambda r: -r["age_d"])


def board_drift(cards: list[dict], now: datetime) -> dict:
    """Cards waiting on someone — stale doing, open asks, review pile."""
    stale_doing, open_asks, review = [], [], 0
    for c in cards:
        col = c.get("column") or "backlog"
        if col == "done":
            continue
        cid = c.get("id") or c["_file"][:-4]
        # card `updated` stamps are naive local time (ICT)
        upd = _upd_dt(c.get("updated"), naive_tz=ICT)
        age_d = round((now - upd).total_seconds() / 86400, 1) if upd else None
        if col == "review":
            review += 1
        if col == "doing" and age_d is not None and age_d > STALE_DOING_DAYS:
            stale_doing.append({"id": cid, "age_d": age_d,
                                "title": (c.get("title") or "")[:60]})
        open_reqs = [r for r in (c.get("requests") or [])
                     if isinstance(r, dict) and r.get("status") != "answered"]
        if open_reqs:
            open_asks.append({"id": cid, "n": len(open_reqs),
                              "age_d": age_d,
                              "title": (c.get("title") or "")[:60]})
    stale_doing.sort(key=lambda r: -(r["age_d"] or 0))
    open_asks.sort(key=lambda r: -(r["age_d"] or 0))
    return {"stale_doing": stale_doing, "open_asks": open_asks,
            "review": review}


def tool_debt() -> dict:
    """ada-voice tool-lint violations by rule — the surface-debt signal."""
    py = ADA_PI / ".venv" / "bin" / "python"
    if not py.exists():
        py = "python3"
    try:
        proc = subprocess.run(
            [str(py), "scripts/tool-lint.py", "--json"],
            cwd=ADA_PI, capture_output=True, text=True, timeout=120)
        rep = json.loads(proc.stdout or "{}")
    except Exception as exc:
        return {"error": f"lint run failed: {exc}"}
    # tool-lint --json emits {ok, errors: [str], warnings: [str]} —
    # error strings are "rule: detail" shaped
    fails = rep.get("errors") or []
    by_rule: dict[str, int] = {}
    for f in fails:
        rule = str(f).split(":", 1)[0].strip() or "?"
        by_rule[rule] = by_rule.get(rule, 0) + 1
    return {"ok": rep.get("ok"), "by_rule": by_rule,
            "total": len(fails),
            "samples": [str(f)[:90] for f in fails[:MAX_ROWS]]}


# ---------- orphans ----------
# ssot.artifact-lifecycle.yml detect contract: scripts with zero references
# from declared surfaces (jobs exec / tool decls / cards / AGENTS.md /
# systemd units / reachable scripts) and docs with zero inbound links +
# no git touch in 90d. Reference scan is a graph walk — seeds are script
# files named by the declared corpus, then each reached script's body is
# scanned for further invocations (qualified `scripts/x.py` paths and
# basenames cover ./x.sh, bash x.sh, python3 x.py, source x.sh, shebang
# exec via systemd ExecStart, and subprocess calls).


_FILE_REFS: dict = {}


def _read_text(p: Path, cap=1_500_000) -> str:
    try:
        if p.stat().st_size > cap:
            return ""
        raw = p.read_bytes()
        if b"\x00" in raw[:4096]:
            return ""
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _ref_tokens(text: str):
    """Reference tokens in a blob: (qualified `scripts/...`/`docs/...`
    paths, ext'd basenames, module refs from `import x` / `python -m x`,
    sluggy bare words that can name a script by stem)."""
    return ({m.group(0).rstrip("./") for m in _REF_PATH_RE.finditer(text)},
            set(_REF_BASE_RE.findall(text)),
            set(_REF_IMPORT_RE.findall(text)) |
            set(_REF_DASHM_RE.findall(text)),
            {t.strip(".") for t in _REF_SLUG_RE.findall(text)
             if "-" in t or "_" in t})


def _file_refs(p: Path):
    if p not in _FILE_REFS:
        q, b, mods, words = _ref_tokens(_read_text(p))
        _FILE_REFS[p] = (
            q, b, mods, words,
            {t for t in q if t not in _NO_PREFIX
             and (REPO / t).is_dir()},
            {t for t in q if "*" in t})
    return _FILE_REFS[p]


def _walk_files(root: Path) -> list:
    if not root.exists():
        return []
    return [p for p in root.rglob("*")
            if p.is_file() and not (set(p.parts) & _ORPHAN_SKIP)
            and not p.name.startswith(".")]


def _is_ref(rel: str, refs) -> bool:
    """True when refs (q, basenames, mods, words, dir-prefixes, globs)
    points at rel — qualified path, basename, `import x`/`python -m x`
    module hit, slug-stem mention, an existing-dir prefix
    (WorkingDirectory / tree mention), or a glob."""
    q, b, mods, words, pfx, globs = refs
    if rel in q or rel.rsplit("/", 1)[-1] in b:
        return True
    if any(rel.startswith(p + "/") for p in pfx):
        return True
    if _slug_stem(rel) and _slug_stem(rel) in words:
        return True
    if rel.endswith(".py"):
        stem = rel[:-3]
        for m in mods:
            mp = m.replace(".", "/")
            if stem == mp or stem.endswith("/" + mp) or \
                    rel.endswith("/" + mp + "/__init__.py"):
                return True
    return any(fnmatch.fnmatch(rel, g)
               or fnmatch.fnmatch(rel, g.replace("**/", ""))
               for g in globs)


def _last_touch(*roots) -> dict:
    """path -> newest commit epoch, one `git log --name-only` pass."""
    out = {}
    try:
        proc = subprocess.run(
            ["git", "log", "--format=@%ct", "--name-only",
             "--", *roots],
            cwd=REPO, capture_output=True, text=True, timeout=300)
    except Exception:
        return out
    ts = None
    for line in proc.stdout.splitlines():
        if line.startswith("@"):
            try:
                ts = int(line[1:])
            except ValueError:
                ts = None
        elif line and ts and line not in out:
            out[line] = ts
    return out


def _script_referrer_files() -> list:
    """The declared surfaces: ssot.jobs exec + tool decls + cards live under
    docs/ssot; plus AGENTS.md, systemd units, tools.json/workflows, and
    build/run decls. docs/kb|reports|assessments deliberately excluded —
    a script named only in a doc is an orphan by contract."""
    out = _walk_files(REPO / "docs/ssot")
    sd = REPO / "systemd"
    if sd.exists():
        out += [p for p in sd.rglob("*")
                if p.is_file() and p.suffix in (".service", ".timer")]
    for name in ("AGENTS.md", "Justfile", "Makefile", "package.json"):
        if (REPO / name).is_file():
            out.append(REPO / name)
    out += [p for p in REPO.glob("docker-compose*.yml") if p.is_file()]
    out += [p for p in REPO.rglob("tools.json")
            if p.is_file() and not (set(p.parts) & _ORPHAN_SKIP)]
    out += [p for p in REPO.rglob("*.tools.yml")
            if p.is_file() and not (set(p.parts) & _ORPHAN_SKIP)]
    for d in ("workflows", ".github", ".husky", "tests"):
        out += _walk_files(REPO / d)
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _script_orphans() -> set:
    """scripts/**/*.py|sh unreachable from declared referrers — BFS over
    the script->script invocation graph seeded by the declared corpus."""
    # orphans-baseline.json lists the orphan paths themselves — as a
    # scripts/ node it would edge-rescue everything it records, so files
    # carrying the baseline name are never graph nodes
    nodes = [p for p in _walk_files(REPO / "scripts")
             if p.name != ORPHAN_BASELINE_NAME]
    rels = {p: p.relative_to(REPO).as_posix() for p in nodes}
    all_rel = set(rels.values())
    seeds = [set() for _ in range(6)]
    for f in _script_referrer_files():
        for dst, src in zip(seeds, _file_refs(f)):
            dst |= src
    reached = {r for r in all_rel if _is_ref(r, seeds)}
    edges = {}
    for p in nodes:
        edges[rels[p]] = {r for r in all_rel
                          if r != rels[p] and _is_ref(r, _file_refs(p))}
    todo = list(reached)
    while todo:
        for nxt in edges.get(todo.pop()) or ():
            if nxt not in reached:
                reached.add(nxt)
                todo.append(nxt)
    return {r for r in all_rel
            if Path(r).suffix in SCRIPT_ORPHAN_EXT} - reached


def _doc_orphans(last_touch: dict, now: datetime) -> list:
    """docs/{kb,reports,assessments} files with zero inbound links from
    other docs/README/AGENTS AND no git touch in 90d."""
    cands = set()
    for d in DOC_ORPHAN_DIRS:
        cands |= {p.relative_to(REPO).as_posix()
                  for p in _walk_files(REPO / d)}
    ref_files = _walk_files(REPO / "docs")
    ref_files += [p for p in REPO.glob("README*") if p.is_file()]
    if (REPO / "AGENTS.md").is_file():
        ref_files.append(REPO / "AGENTS.md")
    q_idx: dict = {}
    b_idx: dict = {}
    pats: list = []  # (pattern, referrer, kind) — kind "glob"|"pfx"|"mod"
    for f in ref_files:
        frel = f.relative_to(REPO).as_posix()
        fq, fb, fm, _w, fp, fg = _file_refs(f)
        for t in fq:
            q_idx.setdefault(t, set()).add(frel)
        for t in fb:
            b_idx.setdefault(t, set()).add(frel)
        pats += [(t, frel, "glob") for t in fg]
        pats += [(t, frel, "pfx") for t in fp]
        pats += [(t, frel, "mod") for t in fm]
    cutoff = now - timedelta(days=DOC_ORPHAN_MIN_AGE_D)
    out = []
    for c in sorted(cands):
        ts = last_touch.get(c)
        if ts is None or \
                datetime.fromtimestamp(ts, timezone.utc) > cutoff:
            continue  # uncommitted or touched within 90d — fresh
        refs = ((q_idx.get(c) or set()) |
                (b_idx.get(c.rsplit("/", 1)[-1]) or set())) - {c}
        inbound = bool(refs)
        if not inbound:
            for pat, fr, kind in pats:
                if fr == c:
                    continue
                if kind == "glob" and (fnmatch.fnmatch(c, pat) or
                                       fnmatch.fnmatch(
                                           c, pat.replace("**/", ""))):
                    inbound = True
                    break
                if kind == "pfx" and c.startswith(pat + "/"):
                    inbound = True
                    break
                if kind == "mod" and c.endswith(".py"):
                    mp = pat.replace(".", "/")
                    if c[:-3].endswith("/" + mp) or \
                            c.endswith("/" + mp + "/__init__.py"):
                        inbound = True
                        break
        if not inbound:
            out.append(c)
    return out


def _hsize(n: int) -> str:
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f}M"
    if n >= 1024:
        return f"{n / 1024:.1f}K"
    return f"{n}B"


def orphans(now: datetime) -> dict:
    """Orphans signal — rows for the digest + ratchet vs
    orphans-baseline.json (same shape as cms-audit-baseline.json:
    new orphans are a finding, stale entries must drop)."""
    last = _last_touch("scripts", *DOC_ORPHAN_DIRS)
    rows = [{"path": r, "kind": "script", "ts": last.get(r)}
            for r in _script_orphans()]
    rows += [{"path": r, "kind": "doc", "ts": last.get(r)}
             for r in _doc_orphans(last, now)]
    for r in rows:
        p = REPO / r["path"]
        r["size"] = p.stat().st_size if p.exists() else 0
        r["date"] = (datetime.fromtimestamp(r["ts"], timezone.utc)
                     .date().isoformat() if r["ts"] else "uncommitted")
    try:
        raw = json.loads(ORPHAN_BASELINE.read_text())
    except Exception:
        raw = {}
    base = {k for k in raw if not k.startswith("_")}
    cur = {r["path"] for r in rows}
    for r in rows:
        r["new"] = r["path"] not in base
    rows.sort(key=lambda r: (not r["new"], r["ts"] or 0))
    return {"total": len(rows), "rows": rows,
            "new": sorted(cur - base), "stale": sorted(base - cur),
            "baseline": len(base)}


# ---------- render ----------

def _load_cards():
    out = []
    for f in sorted(CARDS_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        c["_file"] = f.name
        out.append(c)
    return out


def render(sig: dict, now: datetime, lang: str) -> str:
    th = lang == "th"
    L = [BLOCK_BEGIN, "",
         f"_updated {now.astimezone(ICT):%Y-%m-%d %H:%M ICT}_", ""]
    st = sig["stale_reports"]
    L += [f"### {'รายงานเกินกำหนด' if th else 'Stale generated reports'}"
          f" ({len(st)})", ""]
    if st:
        for r in st[:MAX_ROWS]:
            L.append(f"- **{r['slug']}** — {r['age_d']}d old, fresh_for "
                     f"{r['fresh_for']} — `{r['by']}`")
    else:
        L.append("- —")
    d = sig["board_drift"]
    L += ["", f"### {'บอร์ดล้าด' if th else 'Board drift'}", ""]
    L.append(f"- review pile: **{d['review']}** cards")
    for r in d["stale_doing"][:8]:
        L.append(f"- stale doing {r['age_d']}d: **{r['id']}** {r['title']}")
    for r in d["open_asks"][:8]:
        L.append(f"- open ask x{r['n']} ({r['age_d']}d): **{r['id']}** "
                 f"{r['title']}")
    t = sig["tool_debt"]
    L += ["", f"### {'หนี้ tool surface' if th else 'Tool-surface debt'}", ""]
    if t.get("error"):
        L.append(f"- {t['error']}")
    elif not t.get("total"):
        L.append("- clean — 0 lint violations")
    else:
        rules = ", ".join(f"{k}×{v}" for k, v in t["by_rule"].items())
        L.append(f"- {t['total']} violations — {rules}")
        for s in t.get("samples") or []:
            L.append(f"  - {s}")
    o = sig["orphans"]
    head = f"### {'ไฟล์กำพร้า' if th else 'Orphans'} ({o['total']})"
    if o["new"]:
        head += (f" — {len(o['new'])} {'ใหม่' if th else 'new vs baseline'}")
    L += ["", head, ""]
    if not o["rows"]:
        L.append("- —")
    else:
        for r in o["rows"][:MAX_ROWS]:
            mark = " — **NEW**" if r["new"] else ""
            L.append(f"- **{r['path']}** — {r['kind']} · "
                     f"{r['date']} · {_hsize(r['size'])}{mark}")
        if o["total"] > MAX_ROWS:
            L.append(f"- +{o['total'] - MAX_ROWS} more")
        foot = f"- baseline {o['baseline']} known"
        if o["stale"]:
            foot += f" · {len(o['stale'])} stale entries to drop"
        L.append(foot)
    L += ["", BLOCK_END]
    return "\n".join(L)


def upsert_block(body: str, block: str) -> str:
    if BLOCK_RE.search(body or ""):
        return BLOCK_RE.sub(lambda m: block, body, count=1)
    m = re.search(r"^## ", body or "", re.M)
    if m:
        return body[:m.start()] + block + "\n\n" + body[m.start():]
    return (body or "").rstrip() + "\n\n" + block + "\n"


def page_body(lang, block):
    doc = get_page(lang)
    if doc and doc.get("contentMd"):
        return upsert_block(doc["contentMd"], block)
    title = ("Standard Drift — สัญญาณที่มาตรฐานหลุด" if lang == "th"
             else "Standard Drift — where the standard is slipping")
    lead = ("หน้านี้อัปเดตอัตโนมัติโดย chaba — รวมสัญญาณ drift ไว้ที่เดียว "
            "(รายงานเกินกำหนด / บอร์ดค้าง / หนี้ tool surface) "
            "ตาม report_first_protocol quality_loop"
            if lang == "th" else
            "Auto-updated by chaba — every signal that a standard is "
            "slipping, in one page (stale reports / stuck board / "
            "tool-surface debt), per report_first_protocol#quality_loop.")
    return f"# {title}\n\n{lead}\n\n{block}\n"


def publish(lang, body, now):
    doc = get_page(lang) or {}
    meta = {k: (v if isinstance(v, list) else [str(v)])
            for k, v in (doc.get("meta") or {}).items()}
    meta.update({
        "updated": [now.isoformat(timespec="seconds")],
        "last_verified": [now.date().isoformat()],
        "lang": [lang], "kind": ["report"], "attribute": ["report"],
        "report_role": ["rollup"], "domain": ["monitoring"],
        "generated_by": ["standard-drift-digest.py"], "sources": SOURCES,
        "title": ["Standard Drift" if lang == "en"
                  else "สัญญาณมาตรฐานหลุด"],
        "summary": ["One page of drift signals: stale generated reports, "
                    "stuck kanban items, tool-lint violations — the "
                    "feedback input for tightening standards hands-off."],
        "fresh_for": ["6h"], "confidence": ["high"],
        "timeline": [f"{now.isoformat(timespec='minutes')}: digest run"],
        "written_by": ["standard-drift-digest"],
    })
    _post("/add", {"collection": COLLECTION, "key": PAGE, "lang": lang,
                  "contentMd": body, "meta": meta}, timeout=120)


def save_registry(cfg, now):
    meta = {"kind": ["automation-config"], "bank": ["cms"],
            "scope": ["tony"], "status": ["active"], "source": ["api"],
            "written_by": ["standard-drift-digest"], "subject": [PAGE],
            "attribute": ["automation"], "slug": [PAGE],
            "title": [f"CMS automation: {PAGE}"], "format": ["json"],
            "lang": ["en"], "updated": [now.isoformat(timespec="seconds")],
            "last_verified": [now.date().isoformat()]}
    _post("/add", {"collection": REGISTRY, "key": PAGE, "lang": "en",
                  "contentMd": json.dumps(cfg, ensure_ascii=False,
                                          indent=2), "meta": meta},
          timeout=120)


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
    args = set(sys.argv[1:])
    now = datetime.now(timezone.utc)
    cfg, _ = load_registry()
    if not cfg:
        cfg = {"enabled": True, "interval_min": 360}
    reason = gated(cfg, now, "--force" in args)
    if reason:
        print(f"standard-drift: skipped ({reason})")
        return 0
    sig = {"stale_reports": stale_reports(now),
           "board_drift": board_drift(_load_cards(), now),
           "tool_debt": tool_debt(),
           "orphans": orphans(now)}
    if "--dry-run" in args:
        print(render(sig, now, "en"))
        return 0
    publish("en", page_body("en", render(sig, now, "en")), now)
    publish("th", page_body("th", render(sig, now, "th")), now)
    cfg["last_run"] = now.isoformat(timespec="seconds")
    cfg["last_duration_s"] = round(
        (datetime.now(timezone.utc) - now).total_seconds(), 1)
    save_registry(cfg, now)
    print(f"standard-drift: published ({len(sig['stale_reports'])} stale "
          f"reports, {sig['board_drift']['review']} review, "
          f"{sig['tool_debt'].get('total', '?')} lint violations, "
          f"{sig['orphans']['total']} orphans "
          f"({len(sig['orphans']['new'])} new))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
