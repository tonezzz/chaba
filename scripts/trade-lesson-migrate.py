#!/usr/bin/env python3
"""Trade docs -> Education lessons — deterministic orchestrator
(card trade-lesson-migrate-script, OPS-0103; parent
trade-docs-education-migration / OPS-0102).

The LLM only distills prose; everything else is script-side:

  inventory   docs-mcp documents.json (page paths + bodies) over
              ~/CascadeProjects/trade/docs (--docs-root/--index).
  coverage    scripts/trade-lesson-map.yml — page -> {topic, level,
              skip?}; seeded from scripts/lesson-drift-map.yml when the
              map file does not exist yet.
  draft       per topic, bundle the mapped pages' markdown into one
              prompt and `opencode run` it on the free lane (default
              litellm/gemini-3.5-flash-lite via
              ~/.config/secrets/litellm-chaba.env; --model to override).
  publish     POST board-api /lesson (upsert by topic slug — a re-run
              updates the same lesson in place; no WP creds here).
  record      on --apply: append the new lesson slug -> pages entry to
              scripts/lesson-drift-map.yml and add 'trade': 'Trade' to
              SERIES in scripts/wiki-lesson-migrate.py.

Idempotent: /lesson upserts by slug; a content hash of the doc bundle is
kept in the state file and unchanged topics are skipped (--no-hash-skip
to force). --dry-run (default) prints the plan incl. a proposed mapping
for uncovered pages — no LLM calls, no writes.

  trade-lesson-migrate.py                      # plan only
  trade-lesson-migrate.py --apply --topic ui   # one topic, real write
  trade-lesson-migrate.py --apply              # every uncovered topic
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MAP = SCRIPT_DIR / "trade-lesson-map.yml"
DRIFT_MAP = SCRIPT_DIR / "lesson-drift-map.yml"
WIKI_MIGRATE = SCRIPT_DIR / "wiki-lesson-migrate.py"
DEFAULT_DOCS = "~/CascadeProjects/trade/docs"
DEFAULT_INDEX = "~/CascadeProjects/trade/.docs-mcp/documents.json"
DEFAULT_MODEL = "litellm/gemini-3.5-flash-lite"
LITELLM_ENV = Path("~/.config/secrets/litellm-chaba.env")
STATE = Path("~/var/chaba/trade-lesson-migrate/state.json")
HUB = {"topic": "trade-map", "slug": "lesson-f429ea4f886c",
       "url": "https://boards.surf-thailand.com/wp/index.php/lesson/"
              "lesson-f429ea4f886c/"}
LEVELS = {"intro", "working", "deep"}

sys.path.insert(0, str(SCRIPT_DIR / "board"))
try:
    import dispatch_repos as dr
    API = dr.board_api_base()
except Exception:
    API = "https://idc03.taila0626a.ts.net:10000"

PROMPT = """You are distilling source docs into ONE lesson for a personal
education ledger.

Topic: {topic}   Level: {level}   ({level_hint})

Write ONLY the lesson body as an HTML fragment — no <html>/<body>, no
markdown, no code fences, no preamble. Allowed tags: <h2>, <h3>, <p>,
<ul>/<li>, <pre>, <code>, <b>/<strong>, <i>, <a>.

Shape (match the ledger's house style):
  <h2>{title_hint}</h2>
  <p><i>trade series — hub: <a href="{hub_url}">trade-map</a>.</i></p>
  then 3-6 <h3> sections that teach the material: what exists, how it
  fits together, the few commands/paths/config keys worth remembering.
  Prefer tables-as-<ul> and tight bullets over prose walls. <pre> for
  real command/config examples copied from the sources.

Rules:
- English only — the Thai section is appended downstream.
- Only facts present in the sources; no invented flags, paths, URLs.
- Drop boilerplate (TOCs, "last updated" stamps, review schedules).
- If a source is a stub (README/index page), mine its links/structure
  but do not pad.

The attached bundle concatenates the source pages, each under a
`===== PAGE: <path> =====` header.
"""

LEVEL_HINTS = {
    "intro": "first-contact orientation — the map a newcomer reads once",
    "working": "practitioner level — enough detail to operate the area",
    "deep": "reference depth — edge cases, internals, gotchas",
}


def api_post(path, body, timeout=120):
    body = {**body, "from": "devin"}
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout)
                          .read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path} -> {e.code}: "
                           f"{e.read()[:300].decode('utf-8', 'replace')}")


def load_index(path):
    return json.loads(Path(path).read_text()) if Path(path).exists() \
        else {}


def page_body(page, docs_root, index):
    """Markdown for a docs-mcp page: real file first (fresher than the
    index), fall back to the indexed body."""
    cand = docs_root / f"{page}.md"
    if not cand.exists() and cand.parent.is_dir():
        low = f"{page.rsplit('/', 1)[-1]}.md".lower()
        for f in cand.parent.iterdir():
            if f.name.lower() == low:
                cand = f
                break
    if cand.exists():
        return cand.read_text(errors="replace")
    ent = index.get(page) or {}
    return ent.get("body") or ""


def seed_from_drift_map(drift_path):
    """Invert lesson-drift-map.yml into page -> {topic, level}. Topic and
    level come from the '# <topic> (<level>)' comments beside each slug —
    slugs alone can't be reversed."""
    if not drift_path.exists():
        return {"topics": {}, "pages": {}}
    text = drift_path.read_text()
    cfg = yaml.safe_load(text)
    meta = {}
    for m in re.finditer(r"^\s{2}(lesson-[0-9a-f]+):\s*(?:#\s*(\S+)\s*"
                         r"\(([^)]*)\))?", text, re.M):
        slug, topic, note = m.group(1), m.group(2), (m.group(3) or "")
        lvl = next((w for w in re.split(r"[ ,]+", note)
                    if w in LEVELS), "working")
        meta[slug] = {"topic": topic or slug, "level": lvl}
    pages, topics = {}, {}
    for slug, spec in (cfg.get("lessons") or {}).items():
        t = meta.get(slug) or {"topic": slug, "level": "working"}
        topics[t["topic"]] = {"level": t["level"]}
        for p in spec.get("pages") or []:
            pages.setdefault(p, {"topic": t["topic"],
                                 "level": t["level"]})
    return {"topics": topics, "pages": pages}


def load_map(path, drift_path):
    if path.exists():
        cfg = yaml.safe_load(path.read_text()) or {}
        cfg.setdefault("topics", {})
        cfg.setdefault("pages", {})
        return cfg, False
    return seed_from_drift_map(drift_path), True


def topic_groups(cfg):
    """topic -> {level, pages[]}; extra_pages merge in for synthesis
    lessons."""
    groups = {}
    for page, spec in (cfg.get("pages") or {}).items():
        if not isinstance(spec, dict) or spec.get("skip"):
            continue
        t = spec.get("topic")
        if not t:
            continue
        g = groups.setdefault(t, {"level": spec.get("level") or
                                  (cfg.get("topics") or {})
                                  .get(t, {}).get("level", "working"),
                                  "pages": []})
        g["pages"].append(page)
    for t, spec in (cfg.get("topics") or {}).items():
        if not isinstance(spec, dict):
            continue
        g = groups.setdefault(t, {"level": spec.get("level", "working"),
                                  "pages": []})
        for p in spec.get("extra_pages") or []:
            if p not in g["pages"]:
                g["pages"].append(p)
    for g in groups.values():
        g["pages"].sort()
    return groups


def proposed_mapping(uncovered):
    """Deterministic guess for pages nobody mapped yet — printed as a
    YAML snippet in --dry-run so the map grows by paste, not by
    conversation."""
    def guess(page):
        seg = page.split("/", 1)[0].lower()
        if "/" not in page:
            stem = re.sub(r"[^a-z0-9]+", "-",
                          page.lower()).strip("-")[:24]
            return f"trade-{stem}", "intro"
        return (f"trade-{seg}", "working")
    lines = []
    for p in sorted(uncovered):
        t, lvl = guess(p)
        lines.append(f"  {p}: {{topic: {t}, level: {lvl}}}")
    return "\n".join(lines)


def bundle(topic, group, docs_root, index):
    parts, missing = [], []
    for p in group["pages"]:
        body = page_body(p, docs_root, index).strip()
        if body:
            parts.append(f"===== PAGE: {p} =====\n\n{body}")
        else:
            missing.append(p)
    return "\n\n".join(parts), missing


def bundle_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def litellm_env(model):
    """LITELLM_KEY for litellm/* models — the opencode provider reads it
    from the environment ({env:LITELLM_KEY} in opencode.json)."""
    env = dict(os.environ)
    if not str(model).startswith("litellm/") or env.get("LITELLM_KEY"):
        return env
    f = Path(os.path.expanduser(str(LITELLM_ENV)))
    if f.is_file():
        for line in f.read_text().splitlines():
            if line.startswith("LITELLM_KEY="):
                env["LITELLM_KEY"] = (line.split("=", 1)[1].strip()
                                      .strip('"').strip("'"))
    return env


def opencode_is_v2():
    try:
        r = subprocess.run(["opencode", "--version"],
                           capture_output=True, text=True, timeout=15)
        m = re.search(r"(\d+)\.", r.stdout or "")
        return bool(m and int(m.group(1)) >= 2)
    except Exception:
        return False


def run_opencode(topic, group, bundle_text, model, run_dir, timeout):
    """-> (html, events_path). Raises on no usable output."""
    run_dir.mkdir(parents=True, exist_ok=True)
    pack = run_dir / "bundle.md"
    prompt = PROMPT.format(
        topic=topic, level=group["level"],
        level_hint=LEVEL_HINTS.get(group["level"], ""),
        title_hint=topic.replace("-", " ").title(),
        hub_url=HUB["url"])
    pack.write_text(prompt + "\n\n" + bundle_text)
    (run_dir / "prompt.md").write_text(prompt)

    cmd = ["opencode", "run", "--format", "json"]
    if opencode_is_v2():
        cmd.append("--standalone")
    cmd += ["--model", model, "--title", f"trade lesson {topic}",
            "-f", str(pack),
            "Distill the attached doc bundle into the lesson body."]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=timeout, env=litellm_env(model),
                       cwd=str(run_dir))
    events = run_dir / "events.jsonl"
    events.write_text(r.stdout or "")
    (run_dir / "stderr.log").write_text(r.stderr or "")
    (run_dir / "run.log").write_text(
        f"cmd: {' '.join(cmd)}\nrc: {r.returncode}\n")

    text = ""
    for line in (r.stdout or "").splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        part = ev.get("part") or {}
        if part.get("type") == "text" and part.get("text"):
            text = part["text"]
    html = extract_html(text)
    if not html:
        tail = (r.stderr or "")[-300:]
        raise RuntimeError(f"opencode rc={r.returncode} produced no HTML "
                           f"(see {run_dir}); stderr tail: {tail}")
    (run_dir / "lesson.html").write_text(html)
    return html, events


def extract_html(text):
    """Final assistant text -> the HTML lesson body. Strips code fences
    and any chatter around the fragment."""
    text = (text or "").strip()
    if not text:
        return ""
    fences = re.findall(r"```(?:html)?\s*\n(.*?)```", text, re.S)
    cand = fences[-1].strip() if fences else text
    m = re.search(r"<(h[23]|p|ul|pre)\b", cand)
    if m:
        cand = cand[m.start():]
    if "<" not in cand:
        return ""
    return cand


def publish(topic, level, html):
    return api_post("/lesson", {"topic": topic, "level": level,
                                "source": "link", "content": html})


def update_drift_map(path, slug, topic, level, pages):
    """Append `slug: {pages}` under lessons: — lessons: is the last block
    so EOF append keeps every existing comment. Idempotent on slug."""
    text = path.read_text()
    if re.search(rf"^\s{{2}}{re.escape(slug)}:", text, re.M):
        return False
    entry = (f"  {slug}:"
             f"{' ' * max(1, 28 - len(slug))}# {topic} ({level})\n"
             f"    pages:\n"
             + "".join(f"      - {p}\n" for p in pages))
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + entry)
    return True


def update_wiki_series(path):
    line = re.search(r"^SERIES = \{.*\}", path.read_text(), re.M)
    if not line or "'trade'" in line.group(0) or '"trade"' in \
            line.group(0):
        return False
    new = line.group(0)[:-1].rstrip() + ', "trade": "Trade"}'
    text = path.read_text()
    path.write_text(text[:line.start()] + new + text[line.end():])
    return True


def load_state(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1) + "\n")


def lesson_topics(api_ok=True):
    """slug set + topic set from /lesson op:list — empty when the door
    is unreachable (plan still prints)."""
    try:
        r = api_post("/lesson", {"op": "list"}, timeout=30)
    except Exception:
        return set(), set()
    ls = r.get("lessons") or []
    return ({l.get("slug") for l in ls},
            {l.get("topic") for l in ls})


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs-root", default=DEFAULT_DOCS)
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--map", default=str(DEFAULT_MAP),
                    help="coverage map (default scripts/trade-lesson-map"
                         ".yml; seeded from lesson-drift-map.yml)")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="print the plan only (default)")
    ap.add_argument("--apply", action="store_true",
                    help="draft + publish + update drift-map/SERIES")
    ap.add_argument("--topic", default="",
                    help="only topics containing this substring")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--run-dir",
                    default=os.path.expanduser(
                        "~/var/chaba/trade-lesson-migrate/runs"),
                    help="where bundles/events/lesson.html land")
    ap.add_argument("--state", default=os.path.expanduser(str(STATE)))
    ap.add_argument("--timeout", type=int, default=1200,
                    help="per-topic opencode timeout (s)")
    ap.add_argument("--sleep", type=float, default=1.0,
                    help="delay between /lesson calls")
    ap.add_argument("--no-hash-skip", action="store_true",
                    help="re-draft even when the bundle hash is unchanged")
    ap.add_argument("--all-topics", action="store_true",
                    help="also re-draft topics whose lesson already "
                         "exists (default: only uncovered topics)")
    a = ap.parse_args()
    apply_mode = a.apply
    docs_root = Path(os.path.expanduser(a.docs_root))
    index = load_index(os.path.expanduser(a.index))
    cfg, seeded = load_map(Path(a.map), DRIFT_MAP)
    groups = topic_groups(cfg)
    mapped = {p for p, s in (cfg.get("pages") or {}).items()
              if isinstance(s, dict) and not s.get("skip")}
    skipped = {p for p, s in (cfg.get("pages") or {}).items()
               if isinstance(s, dict) and s.get("skip")}
    inventory = set(index.keys()) if index else set()
    uncovered = sorted(p for p in inventory
                       if p not in mapped and p not in skipped)
    slugs, topics_live = lesson_topics()

    if a.topic:
        needle = a.topic.lower()
        groups = {t: g for t, g in groups.items()
                  if needle in t.lower()}
    if not groups:
        print("no mapped topics to process", file=sys.stderr)
        return 2

    # ---- plan ----
    print(f"docs_root={docs_root}  index={len(inventory)} pages  "
          f"map={'seeded from drift-map' if seeded else a.map}  "
          f"model={a.model}")
    state = load_state(Path(a.state))
    plan = []
    for t in sorted(groups):
        g = groups[t]
        text, missing = bundle(t, g, docs_root, index)
        h = bundle_hash(text)
        exists = t in topics_live
        unchanged = (state.get(t) or {}).get("hash") == h and exists
        action = ("skip" if unchanged and not a.no_hash_skip
                  else "draft")
        if exists and not a.all_topics:
            action = "skip (lesson exists)"
        plan.append({"topic": t, "level": g["level"], "pages": g["pages"],
                     "missing": missing, "hash": h, "text": text,
                     "exists": exists, "action": action})
        flag = "!" if missing else " "
        print(f"{flag} {t:<28} {g['level']:<8} {len(g['pages']):>2} "
              f"pages {len(text) // 1024:>4}KB  "
              f"{'exists' if exists else 'NEW':<6} -> {action}")
        for p in missing:
            print(f"    MISSING {p}")
    if uncovered:
        print(f"\n{len(uncovered)} index page(s) not in the map — "
              f"proposed entries for {a.map}:")
        print("pages:")
        print(proposed_mapping(uncovered))
    if not apply_mode:
        print(f"\ndry-run: {sum(1 for p in plan if p['action'] == 'draft')}"
              f" topic(s) would be drafted; --apply to run")
        return 0

    # ---- apply ----
    if seeded:
        # persist the drift-map-derived coverage so the map file exists
        # before the first publish touches the ledger
        seed_yaml = {"docs_root": a.docs_root, "index_json": a.index,
                     "topics": cfg["topics"], "pages": cfg["pages"]}
        Path(a.map).write_text(
            "# Seeded by trade-lesson-migrate.py from "
            "lesson-drift-map.yml — review + extend.\n"
            + yaml.safe_dump(seed_yaml, sort_keys=False,
                             allow_unicode=True))
        print(f"seeded {a.map} from lesson-drift-map.yml")
    ok = fail = skipped_n = 0
    drift_touched = series_touched = False
    for p in plan:
        t = p["topic"]
        if p["action"] != "draft":
            skipped_n += 1
            continue
        if not p["text"].strip():
            print(f"SKIP {t}: empty bundle", file=sys.stderr)
            fail += 1
            continue
        run_dir = Path(a.run_dir) / \
            f"{time.strftime('%Y%m%d-%H%M%S')}-{t}"
        try:
            html, _ = run_opencode(t, p, p["text"], a.model, run_dir,
                                   a.timeout)
        except Exception as e:
            fail += 1
            print(f"FAIL {t}: {str(e)[:300]}", file=sys.stderr)
            continue
        try:
            r = publish(t, p["level"], html)
        except Exception as e:
            fail += 1
            print(f"FAIL {t}: /lesson {str(e)[:300]}", file=sys.stderr)
            continue
        slug = r.get("slug", "?")
        ok += 1
        print(f"ok   {t:<28} {r.get('message', slug)} "
              f"({len(html)}B html)")
        if update_drift_map(DRIFT_MAP, slug, t, p["level"], p["pages"]):
            drift_touched = True
            print(f"     drift-map += {slug}")
        state[t] = {"hash": p["hash"], "slug": slug,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        time.sleep(a.sleep)
    if ok:
        if update_wiki_series(WIKI_MIGRATE):
            series_touched = True
            print("wiki-lesson-migrate SERIES += 'trade': 'Trade'")
        save_state(Path(a.state), state)
    print(f"\n{ok} published, {skipped_n} skipped, {fail} failed"
          + (" [drift-map updated]" if drift_touched else "")
          + (" [SERIES updated]" if series_touched else ""))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
