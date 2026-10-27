#!/usr/bin/env python3
"""education-report — consolidated Education maintenance report.

Card education-maintenance-consolidated-report. ONE JSON + ONE Markdown
artifact per run covering what used to be three separate surfaces:

  - policy audit   (reuses lessons-audit.py:audit_one — R1..R5 flags)
  - source drift   (reuses lessons-drift.py:audit_content — drift /
                    source-gone / no-repo-source on repo-path refs)
  - review queue   (reuses lessons-due.py:review_bucket — due /
                    upcoming / learned)
  - no_th intents  (meta.no_th UNION scripts/lesson-thai-exceptions.yml)
  - human-review   (rows needing Tony: junk-delete candidates,
                    source-gone pointers, due reviews, fetch failures)
  - trend          (this run vs the previous history.jsonl entry)

SAFETY: audit mode is read-only — the only door calls are /lesson
op=list / op=get. Lesson fixes stay a separate explicit /lesson upsert
stage (scripts/lesson-add.py); deletion stays human-gated (op=delete is
devin/tony only and is never called here). Board/TG summaries post ONLY
after the report verifies and no hold is active.

HOLDS (report written, notify suppressed, exit 1):
  - any op=get failure (degraded fetch — partial content can't be
    audited faithfully)
  - verify.checks failure (internal inconsistency — torn data)
  - exceptions file unreadable (exemptions would silently drop)

HARD FAIL (nothing written, exit 2): op=list unreachable / invalid.

Usage:
  education-report.py [--out-dir DIR] [--repo PATH] [--fixture FILE]
      [--date YYYY-MM-DD] [--dated] [--post board,tg] [--post-card ID]
      [--exceptions FILE] [--dump-fixture FILE]

Env:
  BOARD_API / RUNNER_API  door base (default: idc03 tailnet)
  EDU_REPORT_NOW          ISO timestamp override (tests)
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS / "board"))

try:
    import dispatch_repos as dr
    API_BASE = dr.board_api_base()
except Exception:
    API_BASE = (os.environ.get("BOARD_API") or os.environ.get("RUNNER_API")
                or "https://idc03.taila0626a.ts.net:10000").rstrip("/")

CARD_ID = "education-maintenance-consolidated-report"
DEFAULT_OUT = REPO_ROOT / "docs/reports/education-maintenance"
DEFAULT_EXCEPTIONS = SCRIPTS / "lesson-thai-exceptions.yml"
# dims mirror the lesson-polish 7-dimension policy (job doc
# 2026-10-24-lesson-polish.yml); each maps to component flags / meta so
# the score is recomputed, not re-invented.
DIMS = ("content", "level", "source", "next_review", "thai",
        "hub_link", "split_rule")
VALID_SOURCES = {"chat", "voice", "link"}
# flags that always mean "a human must look" with the reason Tony sees
HUMAN_REASONS = (
    (re.compile(r"^R2:thin"), "thin body — junk-delete candidate; "
     "deletion is human-gated (KNB-0830)"),
    (re.compile(r"^source-gone:"), "referenced source doc gone — "
     "re-point the lesson or commit the doc"),
    (re.compile(r"^R1:level-invalid"), "invalid level meta — fix via "
     "/lesson upsert"),
    (re.compile(r"^get-failed:"), "content fetch failed — check the "
     "/lesson door"),
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# component modules — imported AFTER any LESSON_OUT is set by main() so
# lessons-audit's import-time makedirs lands in the report dir
_audit = _drift = _due = None


def load_components():
    global _audit, _drift, _due
    if _audit is None:
        _audit = _load("lessons_audit", SCRIPTS / "lessons-audit.py")
        _drift = _load("lessons_drift", SCRIPTS / "lessons-drift.py")
        _due = _load("lessons_due", SCRIPTS / "lessons-due.py")
    return _audit, _drift, _due


def api(body: dict, base: str) -> dict:
    req = urllib.request.Request(
        f"{base}/lesson", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def fetch_all(base: str) -> dict:
    """One list + one get per lesson — the only door reads this tool
    makes. Returns {list: [...], gets: {slug: {content, meta, error}}}."""
    listing = api({"op": "list"}, base)
    lessons = listing.get("lessons") or []
    gets = {}
    for l in lessons:
        slug = l.get("slug") or ""
        try:
            g = api({"op": "get", "slug": slug}, base)
            gets[slug] = {"content": g.get("content") or "",
                          "meta": g.get("meta") or {},
                          "modified": g.get("modified")}
        except Exception as e:          # noqa: BLE001 — record, don't die
            gets[slug] = {"content": "", "meta": {}, "error": str(e)}
    return {"list": lessons, "gets": gets,
            "list_count": listing.get("count")}


def now_iso() -> str:
    return (os.environ.get("EDU_REPORT_NOW")
            or datetime.now(timezone.utc)
            .replace(microsecond=0).isoformat())


def load_exceptions(path: Path):
    """-> ({slug: {topic, reason}}, error|None) — the curated
    intentional-no_th map (scripts/lesson-thai-exceptions.yml)."""
    try:
        import yaml
        doc = yaml.safe_load(path.read_text())
        return (doc or {}).get("exceptions") or {}, None
    except Exception as e:              # noqa: BLE001
        return {}, str(e)


def dim_passes(flags, meta, exempt):
    """audit flags + meta -> per-dimension bool dict (7-dim policy)."""
    def has(prefix):
        return any(f.startswith(prefix) for f in flags)
    return {
        "content": not has("R2:"),
        "level": not has("R1:level"),
        "source": str(meta.get("source") or "") in VALID_SOURCES,
        "next_review": not (has("R1:no-next-review")
                            or has("R1:overdue")),
        "thai": (not has("R5:")) or exempt,
        "hub_link": not has("R4:"),
        "split_rule": not has("R3:"),
    }


def build(data: dict, repo: Path, today: str, exceptions: dict,
          generated: str) -> dict:
    audit, drift, due_mod = load_components()
    rows, flag_counts = [], {}
    drift_rows, due_rows, upcoming_rows = [], [], []
    counts = {"due": 0, "upcoming": 0, "learned": 0}
    drift_counts = {"drifted": 0, "source_gone": 0, "no_repo_source": 0}
    get_failures = []
    dim_pass = {d: 0 for d in DIMS}
    human = {}
    exempt_rows = []
    n_exempt_flagged = 0

    for l in data["list"]:
        slug = l.get("slug") or ""
        g = data["gets"].get(slug) or {}
        content, meta = g.get("content") or "", g.get("meta") or {}

        # --- policy audit (component function, byte-identical flags)
        a = audit.audit_one(slug, l.get("topic", ""), l.get("level", ""),
                            l.get("next_review", ""), content)
        if g.get("error"):
            a["flags"] = a["flags"] + [f"get-failed:{g['error']}"]
            get_failures.append(slug)
        for f in a["flags"]:
            flag_counts[f] = flag_counts.get(f, 0) + 1

        # --- exemption: door meta.no_th OR curated exceptions file
        via = ("meta" if meta.get("no_th") or l.get("no_th")
               else "exceptions" if slug in exceptions else "")
        exempt = bool(via)
        if exempt:
            ex = exceptions.get(slug) or {}
            exempt_rows.append({"slug": slug, "topic": l.get("topic", ""),
                                "via": via,
                                "reason": str(ex.get("reason") or "")})
            if any(f.startswith("R5:") for f in a["flags"]):
                n_exempt_flagged += 1

        checks = dim_passes(a["flags"], meta, exempt)
        for d, ok in checks.items():
            dim_pass[d] += 1 if ok else 0

        # --- drift (component function on the same fetched content;
        #     ldate replicated from lessons-drift.main: modified-first)
        ldate = str(l.get("modified") or "")[:10] or \
            str(meta.get("updated") or "")[:10]
        dr = drift.audit_content(repo, slug, l, ldate, content)
        if any(f.startswith("drift:") for f in dr["flags"]):
            drift_counts["drifted"] += 1
        if any(f.startswith("source-gone:") for f in dr["flags"]):
            drift_counts["source_gone"] += 1
        if any(f.startswith(("drift:", "source-gone:"))
               for f in dr["flags"]):
            drift_rows.append(dr)
        if "no-repo-source" in dr["flags"]:
            drift_counts["no_repo_source"] += 1

        # --- review queue (component function, same bucket rule)
        b = due_mod.review_bucket(
            {"status": l.get("status", ""),
             "next_review": l.get("next_review", "")}, today)
        counts[b] += 1
        if b != "learned":
            row = {"slug": slug, "topic": l.get("topic", ""),
                   "level": l.get("level", ""),
                   "next_review": l.get("next_review", "")}
            (due_rows if b == "due" else upcoming_rows).append(row)

        # --- human-review reasons
        reasons = []
        for rx, why in HUMAN_REASONS:
            hits = [f for f in a["flags"] + dr["flags"] if rx.match(f)]
            reasons += [f"{why} [{h}]" for h in hits]
        if b == "due":
            reasons.append(f"spaced review due {l.get('next_review','')}"
                           " — Tony's review queue")
        if reasons:
            human[slug] = {"slug": slug, "topic": l.get("topic", ""),
                           "level": l.get("level", ""),
                           "reasons": sorted(set(reasons))}

        rows.append({**a, "bucket": b, "checks": checks,
                     "no_th_exempt": exempt})

    flagged = [r for r in rows if r["flags"]]
    due_rows.sort(key=lambda r: r["next_review"])
    upcoming_rows.sort(key=lambda r: r["next_review"])
    total = len(rows)
    checks_passed = sum(dim_pass.values())
    compliance = round(checks_passed / (total * len(DIMS)), 4) \
        if total else 0.0
    digest = hashlib.sha256(json.dumps(
        {"slugs": sorted(r["slug"] for r in rows),
         "flags": sorted(flag_counts.items()),
         "buckets": counts, "drift": drift_counts},
        sort_keys=True).encode()).hexdigest()[:16]

    stale_exceptions = sorted(
        s for s in exceptions
        if s not in {l.get("slug") for l in data["list"]})

    return {
        "generated": generated, "date": today, "card": CARD_ID,
        "repo": str(repo),
        "refs": {
            "education_due_page": "private WP page slug education-due "
                                  "(post 354)",
            "member_index": "https://boards.surf-thailand.com/wp/lesson/",
            "runbook": "docs/ssot/jobs/education/"
                       "2026-10-27-education-maintenance-report.yml",
            "exceptions": "scripts/lesson-thai-exceptions.yml",
            "job": "ssot.jobs.yml job chaba-education-report",
        },
        "totals": {"lessons": total, "flagged": len(flagged),
                   "clean": total - len(flagged),
                   "get_failures": len(get_failures)},
        "policy": {
            "flag_counts": dict(sorted(flag_counts.items())),
            "dimensions": {d: {"pass": dim_pass[d],
                               "fail": total - dim_pass[d]}
                           for d in DIMS},
            "compliance": compliance},
        "drift": {**drift_counts, "rows": drift_rows},
        "reviews": {**counts, "due_rows": due_rows,
                    "upcoming_rows": upcoming_rows[:10],
                    "upcoming_shown": min(10, len(upcoming_rows))},
        "no_th": {"exempt": len(exempt_rows),
                  "exempt_rows": sorted(exempt_rows,
                                        key=lambda r: r["slug"]),
                  "flagged_but_exempt": n_exempt_flagged,
                  "stale_exception_slugs": stale_exceptions},
        "human_review_pending": sorted(human.values(),
                                       key=lambda r: r["slug"]),
        "rows": rows,
        "digest": digest,
    }


def verify(report: dict, data: dict, exceptions_err) -> dict:
    """Deterministic internal-consistency checks — recomputes every
    published count from the raw fetch, so a torn or misassembled
    report fails before it can be broadcast."""
    checks, holds = [], []
    total = report["totals"]["lessons"]
    listed = len(data["list"])

    def ck(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return ok

    ck("total_matches_list",
       total == listed == data.get("list_count", listed),
       f"rows={total} list={listed} count={data.get('list_count')}")
    buckets = report["reviews"]
    ck("buckets_sum",
       buckets["due"] + buckets["upcoming"] + buckets["learned"] == total,
       f"{buckets['due']}+{buckets['upcoming']}+{buckets['learned']}")
    ck("due_rows_match", buckets["due"] == len(buckets["due_rows"]))
    ck("dimensions_sum",
       all(v["pass"] + v["fail"] == total
           for v in report["policy"]["dimensions"].values()))
    recount = {}
    for r in report["rows"]:
        for f in r["flags"]:
            recount[f] = recount.get(f, 0) + 1
    ck("flag_counts_match",
       recount == report["policy"]["flag_counts"])
    drows = report["drift"]["rows"]
    ck("drift_counts_match",
       report["drift"]["drifted"]
       == len([r for r in drows
               if any(f.startswith("drift:") for f in r["flags"])])
       and report["drift"]["source_gone"]
       == len([r for r in drows
               if any(f.startswith("source-gone:")
                      for f in r["flags"])]))
    ck("exempt_subset",
       {e["slug"] for e in report["no_th"]["exempt_rows"]}
       <= {r["slug"] for r in report["rows"]},
       f"exempt={report['no_th']['exempt']}")

    if report["totals"]["get_failures"]:
        holds.append(f"get_failures={report['totals']['get_failures']}"
                     " — degraded fetch; audit only")
    if exceptions_err:
        holds.append(f"exceptions file unreadable: {exceptions_err}")
    for c in checks:
        if not c["ok"]:
            holds.append(f"verify:{c['name']} failed")
    status = "pass" if all(c["ok"] for c in checks) else "fail"
    return {"status": status, "checks": checks, "holds": sorted(set(holds))}


def trend(report: dict, out_dir: Path) -> dict:
    hist = out_dir / "history.jsonl"
    prev = None
    if hist.exists():
        for ln in hist.read_text().splitlines():
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if rec.get("date") != report["date"]:
                prev = rec
    t = {"compliance": report["policy"]["compliance"],
         "flagged": report["totals"]["flagged"],
         "drifted": report["drift"]["drifted"],
         "due": report["reviews"]["due"],
         "polish_anchor": {"date": "2026-10-24", "before": 0.9307,
                           "after": 0.9916}}
    if prev:
        t["previous"] = {k: prev.get(k) for k in
                         ("date", "compliance", "flagged", "drifted",
                          "due")}
        t["delta_compliance"] = round(
            report["policy"]["compliance"]
            - (prev.get("compliance") or 0), 4)
        t["delta_flagged"] = (report["totals"]["flagged"]
                              - (prev.get("flagged") or 0))
    else:
        t["previous"] = None
    return t


def history_line(report: dict) -> dict:
    return {"date": report["date"],
            "total": report["totals"]["lessons"],
            "flagged": report["totals"]["flagged"],
            "compliance": report["policy"]["compliance"],
            "drifted": report["drift"]["drifted"],
            "source_gone": report["drift"]["source_gone"],
            "due": report["reviews"]["due"],
            "upcoming": report["reviews"]["upcoming"],
            "no_th_exempt": report["no_th"]["exempt"],
            "human_pending": len(report["human_review_pending"]),
            "verify": report["verify"]["status"],
            "digest": report["digest"]}


def render_md(r: dict) -> str:
    t = r["totals"]
    L = [f"# Education maintenance — {r['date']}",
         "",
         f"**{t['lessons']} lessons** · {t['flagged']} flagged · "
         f"{t['clean']} clean · compliance "
         f"**{r['policy']['compliance']:.4f}** · verify "
         f"**{r['verify']['status']}**"
         + (f" · holds: {', '.join(r['verify']['holds'])}"
            if r['verify']['holds'] else ""),
         "",
         "Reused components: `lessons-audit.py` (R1–R5), "
         "`lessons-drift.py` (source refs vs git), `lessons-due.py` "
         "(review buckets) — one /lesson fetch feeds all three. "
         "Read-only: fixes are a separate explicit /lesson upsert; "
         "deletion is human-gated.",
         "",
         "## Policy flags (audit R1–R5)", ""]
    if r["policy"]["flag_counts"]:
        L += ["| flag | n |", "|---|---|"] + [
            f"| `{f}` | {n} |"
            for f, n in r["policy"]["flag_counts"].items()]
    else:
        L.append("no flags")
    L += ["", "## Policy dimensions (lesson-polish 7-dim)", "",
          "| dim | pass | fail |", "|---|---|---|"] + [
        f"| {d} | {v['pass']} | {v['fail']} |"
        for d, v in r["policy"]["dimensions"].items()]
    tr = r["trend"]
    trend_line = (f"{tr['compliance']:.4f} now"
                  + (f" vs {tr['previous']['compliance']:.4f} on "
                     f"{tr['previous']['date']} "
                     f"(Δ{tr['delta_compliance']:+.4f}, "
                     f"flagged Δ{tr['delta_flagged']:+d})"
                     if tr.get("previous") else " — first run"))
    trend_line += (f" · polish anchor {tr['polish_anchor']['before']}→"
                   f"{tr['polish_anchor']['after']} "
                   f"({tr['polish_anchor']['date']})")
    L += ["", "## Compliance trend", "", trend_line, "",
          "## Source drift (lessons-drift)", "",
          f"drifted **{r['drift']['drifted']}** · source-gone "
          f"**{r['drift']['source_gone']}** · no-repo-source "
          f"{r['drift']['no_repo_source']}", ""]
    if r["drift"]["rows"]:
        L += ["| slug | topic | flags |", "|---|---|---|"] + [
            f"| `{row['slug']}` | {row['topic'][:50]} | "
            + "<br>".join(f"`{f}`" for f in row["flags"]) + " |"
            for row in r["drift"]["rows"]]
    rv = r["reviews"]
    L += ["", "## Review queue (lessons-due)", "",
          f"due **{rv['due']}** · upcoming **{rv['upcoming']}** · "
          f"learned {rv['learned']}", ""]
    if rv["due_rows"]:
        L += ["| due | slug | topic |", "|---|---|---|"] + [
            f"| {row['next_review']} | `{row['slug']}` | "
            f"{row['topic'][:60]} |" for row in rv["due_rows"]]
    L += ["", "## Intentional no_th exceptions", "",
          f"**{r['no_th']['exempt']}** exempt "
          f"({r['no_th']['flagged_but_exempt']} would otherwise flag "
          "R5)"]
    if r["no_th"]["stale_exception_slugs"]:
        L.append(f"stale exception slugs (lesson gone): "
                 f"{', '.join(r['no_th']['stale_exception_slugs'])}")
    L += [""] + [
        f"- `{e['slug']}` {e['topic']} — via {e['via']}"
        + (f" ({e['reason']})" if e["reason"] else "")
        for e in r["no_th"]["exempt_rows"]]
    L += ["", "## Human review pending", ""]
    if r["human_review_pending"]:
        L += ["| slug | topic | why |", "|---|---|---|"] + [
            f"| `{h['slug']}` | {h['topic'][:45]} | "
            + "<br>".join(h["reasons"]) + " |"
            for h in r["human_review_pending"]]
    else:
        L.append("none")
    L += ["", "## Verify", "",
          f"status **{r['verify']['status']}** · digest "
          f"`{r['digest']}`"] + [
        f"- {'✓' if c['ok'] else '✗'} {c['name']} {c['detail']}"
        for c in r["verify"]["checks"]]
    if r["verify"]["holds"]:
        L += ["", "**HOLDS** (notify suppressed):"] + [
            f"- {h}" for h in r["verify"]["holds"]]
    L += ["", "## Refs", "",
          f"- card: `{r['card']}` · education-due page: "
          f"{r['refs']['education_due_page']}",
          f"- member index: {r['refs']['member_index']}",
          f"- runbook: `{r['refs']['runbook']}` · exceptions: "
          f"`{r['refs']['exceptions']}`",
          f"- artifacts: `latest.json`/`latest.md` + `history.jsonl` "
          f"in this dir · generated {r['generated']}",
          ""]
    return "\n".join(L)


def post(report: dict, channels: str, card_id: str, base: str) -> dict:
    """Board/TG summary — invoked ONLY when verify passes and no holds.
    Best-effort per channel; outcomes land in report['notify']."""
    t, rv = report["totals"], report["reviews"]
    prev = report["trend"].get("previous")
    delta = (f"Δ{report['trend'].get('delta_compliance', 0):+.4f}"
             if prev else "first run")
    line = (f"education-maintenance {report['date']}: {t['lessons']} "
            f"lessons, {t['flagged']} flagged, compliance "
            f"{report['policy']['compliance']:.4f} ({delta}), "
            f"drift {report['drift']['drifted']}/gone "
            f"{report['drift']['source_gone']}, due {rv['due']} — "
            f"docs/reports/education-maintenance/latest.md")
    out = {}
    for ch in [c.strip() for c in channels.split(",") if c.strip()]:
        if ch == "board":
            try:
                r = api_comment(base, card_id, "devin",
                                f"{line}\ndigest {report['digest']}")
                out["board"] = {"ok": True, "resp": r.get("message", r)}
            except Exception as e:              # noqa: BLE001
                out["board"] = {"ok": False, "error": str(e)}
        elif ch == "tg":
            try:
                sys.path.insert(0, str(SCRIPTS / "board"))
                import board_notify
                ok = board_notify.send("Education maintenance", line,
                                       channel="tg")
                out["tg"] = {"ok": bool(ok)}
            except Exception as e:              # noqa: BLE001
                out["tg"] = {"ok": False, "error": str(e)}
        else:
            out[ch] = {"ok": False, "error": "unknown channel"}
    return out


def api_comment(base: str, card_id: str, frm: str, text: str) -> dict:
    req = urllib.request.Request(
        f"{base}/comment", data=json.dumps(
            {"id": card_id, "from": frm, "text": text}).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--repo", default="",
                    help="checkout for drift source lookups "
                         "(default: git toplevel of cwd)")
    ap.add_argument("--fixture", default="",
                    help="JSON {list, gets} — offline deterministic run")
    ap.add_argument("--dump-fixture", default="",
                    help="write the live fetch here as a fixture")
    ap.add_argument("--date", default="",
                    help="YYYY-MM-DD override (tests/replays)")
    ap.add_argument("--dated", action="store_true",
                    help="also write <date>-education-maintenance.*")
    ap.add_argument("--post", default="",
                    help="channels after pass: 'board', 'tg', or both")
    ap.add_argument("--post-card", default=CARD_ID)
    ap.add_argument("--exceptions", default=str(DEFAULT_EXCEPTIONS))
    ap.add_argument("--api", default=API_BASE)
    a = ap.parse_args()

    os.environ.setdefault("LESSON_OUT", a.out_dir)
    audit_mod, _, _ = load_components()
    today = a.date or now_iso()[:10]
    # audit_one reads a module-global TODAY frozen at import — pin it to
    # this run's date so --date replays stay deterministic
    audit_mod.TODAY = today
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if a.repo:
        repo = Path(a.repo).expanduser()
    else:
        rr = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
        repo = Path(rr.stdout.strip()) if rr.returncode == 0 \
            else Path.cwd()

    # --- fetch (list + gets only — never a write)
    if a.fixture:
        data = json.loads(Path(a.fixture).read_text())
    else:
        try:
            data = fetch_all(a.api)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"education-report: /lesson unreachable: {e}",
                  file=sys.stderr)
            return 2
    if a.dump_fixture:
        Path(a.dump_fixture).write_text(json.dumps(data, indent=1,
                                                 ensure_ascii=False))

    exc_path = Path(a.exceptions)
    if exc_path.exists():
        exceptions, exc_err = load_exceptions(exc_path)
    else:
        exceptions, exc_err = {}, f"missing {exc_path}"

    report = build(data, repo, today, exceptions, now_iso())
    report["verify"] = verify(report, data, exc_err)
    report["trend"] = trend(report, out_dir)
    ok = report["verify"]["status"] == "pass" \
        and not report["verify"]["holds"]

    # --- artifacts always land (even on hold — the failed report IS
    #     the evidence); notify is the only thing gated on pass
    if a.post and ok:
        report["notify"] = post(report, a.post, a.post_card, a.api)
    elif a.post:
        report["notify"] = {"skipped": "hold/verify — see holds"}
    else:
        report["notify"] = {"skipped": "audit mode"}
    (out_dir / "latest.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    (out_dir / "latest.md").write_text(render_md(report))
    if a.dated:
        (out_dir / f"{today}-education-maintenance.json").write_text(
            json.dumps(report, indent=1, ensure_ascii=False) + "\n")
        (out_dir / f"{today}-education-maintenance.md").write_text(
            render_md(report))
    # history: one line per run, dedup same-day re-runs to the latest
    hline = history_line(report)
    hist = out_dir / "history.jsonl"
    old = []
    if hist.exists():
        for ln in hist.read_text().splitlines():
            try:
                if json.loads(ln).get("date") != today:
                    old.append(ln)
            except ValueError:
                continue
    hist.write_text("\n".join(old + [json.dumps(hline)]) + "\n")

    t = report["totals"]
    print(f"education-report: {t['lessons']} lessons, {t['flagged']} "
          f"flagged, compliance {report['policy']['compliance']:.4f}, "
          f"drift {report['drift']['drifted']}/"
          f"{report['drift']['source_gone']}, due "
          f"{report['reviews']['due']} -> {out_dir} "
          f"[verify={report['verify']['status']}"
          f"{', holds=' + str(len(report['verify']['holds'])) if report['verify']['holds'] else ''}]")
    if a.post and not ok:
        print("notify suppressed (hold/verify fail)", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
