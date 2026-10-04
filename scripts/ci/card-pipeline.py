#!/usr/bin/env python3
"""card-pipeline — the standard Chaba card CI runner (docs/ssot/ssot.ci.yml).

Takes a kanban card id that has opted in (`pipeline: ci`), executes the
stages it can automate — plan -> structure -> develop -> audit ->
benchmark — and writes each stage result into the card's comms plus the
`pipeline:` status block. Gates it can't automate (implementation in
another repo, a missing benchmark measurement, Tony approval) become
request entries on the card.

Write paths (never touch card YAML outside these):
  --cards-dir PATH   file mode: direct YAML writes under the
                     /tmp/board-api.lock flock — the kanban-dispatch.py
                     protocol; for the dispatcher host. Renders the board
                     unless --no-render.
  --api URL          api mode: GET /cards, POST /comment, /request,
                     /pipeline — for agents inside a worktree session.

Run artifact: reports/ci/<card>-<ts>.json + meta.yml (report node
ci-pipeline, ssot.reports.yml). Exit codes per ssot.quality.yml:
0 pass, 1 a stage gate failed, 2 runner error.

Selftest: python3 scripts/ci/card-pipeline.py --selftest
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent.parent
CARD_DIR = REPO / "docs/ssot/kanban/cards"
RENDER = REPO / "scripts/render-board.py"
REPORT_DIR = REPO / "reports" / "ci"
LOCK = Path(os.environ.get("BOARD_LOCK", "/tmp/board-api.lock"))
ACTOR = "devin"

sys.path.insert(0, str(REPO / "scripts" / "lib"))
try:
    import report as reportlib  # scripts/lib/report.py
except Exception:  # pragma: no cover - meta/timeline optional
    reportlib = None

STAGES = ["plan", "structure", "develop", "audit", "benchmark"]
GENERATED_PREFIXES = (
    "stacks/web/public/apps/board/",
    "reports/ci/",
)
WHITELIST_REPOS = {"chaba", "ada-pi", "sunsynk-card"}


def now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    h = hashlib.sha1(text.encode()).hexdigest()[:6]
    return f"{slug}-{h}" if slug else f"req-{h}"


def sh(cmd: list, cwd=None, timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          cwd=cwd, timeout=timeout)


# ---------------------------------------------------------------- sinks


class Sink:
    """Write path to the card. mutate() collects changes; flush() commits."""

    def read_card(self, cid: str) -> dict:
        raise NotImplementedError

    def comment(self, cid: str, text: str) -> None:
        raise NotImplementedError

    def request(self, cid: str, ask: str, request_id: str) -> None:
        raise NotImplementedError

    def set_pipeline(self, cid: str, pipeline: dict) -> None:
        raise NotImplementedError

    def flush(self) -> None:
        pass


class FileSink(Sink):
    """Direct YAML writes in a local checkout under the board flock —
    the kanban-dispatch.py protocol. All card mutations for one run are
    staged then saved once in flush()."""

    def __init__(self, cards_dir: Path, render: bool = True,
                 dry_run: bool = False):
        self.cards_dir = Path(cards_dir)
        self.render = render
        self.dry_run = dry_run
        self._dirty: dict[str, dict] = {}

    def _path(self, cid: str) -> Path:
        if not cid or "/" in cid or ".." in cid:
            raise ValueError("bad card id")
        return self.cards_dir / f"{cid}.yml"

    def read_card(self, cid: str) -> dict:
        if cid in self._dirty:
            return self._dirty[cid]
        p = self._path(cid)
        if not p.exists():
            raise ValueError(f"no card {cid}")
        card = yaml.safe_load(p.read_text()) or {}
        self._dirty[cid] = card
        return card

    def comment(self, cid: str, text: str) -> None:
        card = self.read_card(cid)
        card.setdefault("comms", []).append(
            {"at": now(), "from": ACTOR, "text": text[:500]})

    def request(self, cid: str, ask: str, request_id: str) -> None:
        card = self.read_card(cid)
        reqs = card.setdefault("requests", [])
        for r in reqs:
            if r.get("id") == request_id:
                if r.get("status") == "open":
                    return  # already raised
                r["status"] = "open"  # re-open answered/stale request
                r.pop("answer", None)
                self.comment(cid, f"re-opened request {request_id}: {ask[:120]}")
                return
        reqs.append({"id": request_id, "ask": ask, "status": "open"})
        self.comment(cid, f"raised request {request_id}: {ask[:120]}")

    def set_pipeline(self, cid: str, pipeline: dict) -> None:
        card = self.read_card(cid)
        card["pipeline"] = pipeline

    def flush(self) -> None:
        if self.dry_run:
            for cid, card in self._dirty.items():
                print(f"[dry-run] would write {self._path(cid)}")
                print(yaml.safe_dump(card, allow_unicode=True,
                                     sort_keys=False, width=110))
            return
        if not self._dirty:
            return
        with LOCK.open("w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            for cid, card in self._dirty.items():
                card["updated"] = now()
                self._path(cid).write_text(
                    yaml.safe_dump(card, allow_unicode=True,
                                   sort_keys=False, width=110))
            if self.render and RENDER.exists():
                subprocess.run([sys.executable, str(RENDER)],
                               cwd=REPO, check=False,
                               capture_output=True, timeout=60)


class ApiSink(Sink):
    """HTTP writes for agents inside a worktree: /comment, /request,
    /pipeline. Reads go through GET /cards (the rendered payload)."""

    def __init__(self, api: str, cards_dir: Path | None = None,
                 dry_run: bool = False):
        self.api = api.rstrip("/")
        self.dry_run = dry_run
        self.cards_dir = cards_dir  # optional local fallback for reads

    def _post(self, path: str, body: dict) -> dict:
        if self.dry_run:
            print(f"[dry-run] POST {path} {json.dumps(body)[:200]}")
            return {"ok": True, "dry_run": True}
        req = urllib.request.Request(
            self.api + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return {"ok": False, "status": e.code,
                    "error": e.read().decode(errors="replace")[:200]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def read_card(self, cid: str) -> dict:
        if self.cards_dir:
            p = Path(self.cards_dir) / f"{cid}.yml"
            if p.exists():
                return yaml.safe_load(p.read_text()) or {}
        try:
            with urllib.request.urlopen(self.api + "/cards",
                                        timeout=15) as r:
                payload = json.loads(r.read() or b"{}")
        except Exception as e:
            raise ValueError(f"cannot read board: {e}")
        cards = payload.get("cards", payload)
        if isinstance(cards, dict):
            cards = cards.values()
        for c in cards:
            if isinstance(c, dict) and c.get("id") == cid:
                return c
        raise ValueError(f"no card {cid}")

    def comment(self, cid: str, text: str) -> None:
        r = self._post("/comment", {"id": cid, "from": ACTOR, "text": text})
        if not r.get("ok"):
            print(f"warn: /comment failed: {r.get('error')}", file=sys.stderr)

    def request(self, cid: str, ask: str, request_id: str) -> None:
        r = self._post("/request", {"id": cid, "ask": ask,
                                    "request_id": request_id,
                                    "from": ACTOR})
        if not r.get("ok") and "duplicate" not in str(r.get("error")):
            print(f"warn: /request failed: {r.get('error')}", file=sys.stderr)

    def set_pipeline(self, cid: str, pipeline: dict) -> None:
        r = self._post("/pipeline", {"id": cid, "pipeline": pipeline,
                                     "from": ACTOR})
        if r.get("status") == 404:
            # pre-deploy board-api — keep the result visible in comms
            stages = pipeline.get("stages", {})
            line = "pipeline-status: " + " ".join(
                f"{s}={st.get('status')}" for s, st in stages.items())
            self.comment(cid, line)
        elif not r.get("ok"):
            print(f"warn: /pipeline failed: {r.get('error')}",
                  file=sys.stderr)


# ---------------------------------------------------------------- git


def repo_root(cwd: Path) -> Path | None:
    r = sh(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def repo_identity(root: Path) -> str:
    r = sh(["git", "remote", "get-url", "origin"], cwd=root)
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip().rstrip("/")).stem
    return root.name


def branch_and_base(root: Path) -> tuple[str, str]:
    b = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    branch = b.stdout.strip() if b.returncode == 0 else "?"
    base = ""
    for ref in ("origin/master", "origin/main", "master", "main"):
        m = sh(["git", "merge-base", "HEAD", ref], cwd=root)
        if m.returncode == 0 and m.stdout.strip():
            base = f"{ref}@{m.stdout.strip()[:8]}"
            break
    return branch, base


def changed_files(root: Path) -> list[str]:
    """Committed-vs-base + uncommitted paths, de-duplicated."""
    files: list[str] = []
    seen = set()

    def add(paths):
        for p in paths:
            if p and p not in seen:
                seen.add(p)
                files.append(p)

    for ref in ("origin/master", "origin/main", "master", "main"):
        r = sh(["git", "diff", "--name-only", f"{ref}...HEAD"], cwd=root)
        if r.returncode == 0:
            add(r.stdout.splitlines())
            break
    r = sh(["git", "status", "--porcelain"], cwd=root)
    if r.returncode == 0:
        for ln in r.stdout.splitlines():
            p = ln[3:].split(" -> ")[-1].strip()
            add([p])
    return files


def in_scope(files: list[str], cid: str, root: Path | None = None) -> list[str]:
    """Drop the card file itself and generated outputs — evidence must be
    real work, not pipeline bookkeeping. Untracked-dir entries from
    `git status --porcelain` (trailing /) are expanded so audit sees the
    files inside them."""
    own_card = f"docs/ssot/kanban/cards/{cid}.yml"
    out = []
    for f in files:
        if f == own_card or any(f.startswith(p) for p in GENERATED_PREFIXES):
            continue
        if root is not None and (root / f).is_dir():
            for p in sorted((root / f).rglob("*")):
                if p.is_file():
                    out.append(str(p.relative_to(root)))
        else:
            out.append(f)
    return out


# ---------------------------------------------------------------- stages


def stage_plan(card: dict) -> dict:
    missing = []
    if not (card.get("title") or "").strip():
        missing.append("title")
    spec = (card.get("spec") or "").strip()
    note = (card.get("note") or "").strip()
    if not (spec or note):
        missing.append("spec|note")
    bench = card.get("benchmark") or {}
    accept = (bench.get("metric") or card.get("metric")
              or card.get("verify")
              or re.search(r"accept|verify|metric", spec, re.I))
    if not accept:
        missing.append("acceptance (benchmark.metric|metric|verify)")
    if missing:
        return {"status": "fail",
                "detail": "missing " + ", ".join(missing),
                "missing": missing}
    return {"status": "pass",
            "detail": "dispatchable spec + acceptance signal present",
            "spec_len": len(spec or note),
            "acceptance": str(bench.get("metric") or card.get("metric")
                              or card.get("verify"))[:200],
            "declared_repo": (card.get("action") or {}).get("repo")}


def stage_structure(card: dict, root: Path | None) -> dict:
    if root is None:
        return {"status": "fail", "detail": "not inside a git worktree"}
    branch, base = branch_and_base(root)
    files = changed_files(root)
    scope = in_scope(files, card.get("id", ""), root)
    declared = (card.get("action") or {}).get("repo") or repo_identity(root)
    return {"status": "pass",
            "detail": (f"worktree {root.name} on {branch}; "
                       f"{len(scope)} in-scope file(s) vs {base or 'HEAD'}"),
            "worktree": str(root), "branch": branch, "base": base,
            "declared_repo": declared,
            "repo_identity": repo_identity(root),
            "files_changed": files, "in_scope": scope}


def stage_develop(card: dict, structure: dict) -> dict:
    declared = structure.get("declared_repo")
    mine = structure.get("repo_identity")
    scope = structure.get("in_scope") or []
    if declared and mine and declared != mine and declared in WHITELIST_REPOS:
        return {"status": "delegated",
                "detail": (f"card targets repo '{declared}' — this worktree "
                           f"is '{mine}'; needs a session on {declared}"),
                "request": (f"Implement the fix in {declared} — work was "
                            f"delegated by the ci pipeline (card targets "
                            f"repo {declared}).")}
    if scope:
        return {"status": "pass",
                "detail": f"{len(scope)} in-scope file(s) changed",
                "files": scope[:50]}
    return {"status": "delegated",
            "detail": "no in-scope changes in this worktree",
            "request": ("Develop stage found no implementation — dispatch a "
                        "session against the target repo or mark the card "
                        "not-applicable.")}


def _audit_checks(scope_files: list[str], root: Path) -> list[dict]:
    checks = []
    ssot_files = []
    for rel in scope_files:
        f = root / rel
        if not f.exists():
            continue
        if rel.endswith(".py"):
            r = sh([sys.executable, "-m", "py_compile", str(f)], cwd=root)
            checks.append({"name": f"py_compile {rel}",
                           "ok": r.returncode == 0,
                           "detail": (r.stderr or "").strip()[:300]})
        elif rel.endswith((".js", ".mjs")):
            r = sh(["node", "--check", str(f)], cwd=root)
            checks.append({"name": f"node --check {rel}",
                           "ok": r.returncode == 0,
                           "detail": (r.stderr or "").strip()[:300]})
        elif rel.endswith(".yml"):
            try:
                yaml.safe_load(f.read_text())
                checks.append({"name": f"yaml parse {rel}", "ok": True,
                               "detail": ""})
            except yaml.YAMLError as e:
                checks.append({"name": f"yaml parse {rel}", "ok": False,
                               "detail": str(e)[:300]})
        if rel.startswith("docs/ssot/") and rel.endswith(".yml"):
            ssot_files.append(rel)
    if ssot_files:
        r = sh(["node", str(REPO / "scripts" / "ssot-validate-all.mjs"),
                *ssot_files], cwd=root, timeout=300)
        bad = [ln for ln in (r.stdout or "").splitlines()
               if "Errors:" in ln or "❌" in ln]
        checks.append({"name": f"ssot-validate ({len(ssot_files)} files)",
                       "ok": r.returncode == 0 and not bad,
                       "detail": "; ".join(bad[:5])})
    return checks


def stage_audit(structure: dict, root: Path | None) -> dict:
    scope = structure.get("in_scope") or []
    if not scope:
        return {"status": "skip",
                "detail": "no in-scope changes — nothing to audit "
                          "(delegated work is audited in its own session)",
                "checks": []}
    checks = _audit_checks(scope, root) if root else []
    failed = [c for c in checks if not c["ok"]]
    if failed:
        return {"status": "fail",
                "detail": (f"{len(failed)}/{len(checks)} checks failed: "
                           + "; ".join(c["name"] for c in failed[:4])),
                "checks": checks}
    return {"status": "pass",
            "detail": f"{len(checks)} checks passed on {len(scope)} files",
            "checks": checks}


def run_benchmark_command(command: str, cwd: Path) -> tuple[str | None, str]:
    try:
        r = sh(["bash", "-c", command], cwd=cwd, timeout=120)
        out = (r.stdout or "").strip()
        if r.returncode != 0 and not out:
            return None, (r.stderr or "command failed").strip()[:200]
        return (out.splitlines()[-1][:200] if out else ""), ""
    except Exception as e:
        return None, str(e)[:200]


def stage_benchmark(card: dict, pipeline: dict, root: Path,
                    develop_ok: bool, dry_run: bool) -> tuple[dict, dict]:
    """Returns (stage_result, benchmark_record)."""
    decl = dict(card.get("benchmark") or {})
    if not decl.get("metric") and card.get("metric"):
        decl["metric"] = card["metric"]
    if card.get("verify") and "note" not in decl:
        decl["note"] = card["verify"]

    rec = dict(pipeline.get("benchmark") or {})
    rec.setdefault("metric", decl.get("metric"))
    command = decl.get("command") or rec.get("command")
    if command:
        rec["command"] = command

    if not rec.get("metric"):
        return ({"status": "blocked",
                 "detail": "no benchmark metric declared on the card",
                 "request": "Declare benchmark.metric (+command if "
                            "measurable) so the pipeline can record "
                            "before/after."}, rec)

    if rec.get("before") is None:
        if command:
            val, err = (None, "dry-run") if dry_run else \
                run_benchmark_command(command, root)
            if val is None:
                return ({"status": "blocked",
                         "detail": f"before measurement failed: {err}",
                         "request": f"benchmark.command failed "
                                    f"({err[:80]}) — measure "
                                    f"'{rec['metric'][:80]}' by hand."}, rec)
            rec["before"] = val
            rec["measured_at"] = now()
        elif decl.get("before") is not None:
            rec["before"] = decl["before"]
        else:
            return ({"status": "blocked",
                     "detail": "metric declared but no command/before value",
                     "request": f"Record a baseline for "
                                f"'{rec['metric'][:80]}' — add "
                                f"benchmark.command or benchmark.before."},
                    rec)

    if rec.get("after") is None:
        if develop_ok and command:
            val, err = (None, "dry-run") if dry_run else \
                run_benchmark_command(command, root)
            if val is not None:
                rec["after"] = val
                rec["measured_at"] = now()
        if rec.get("after") is None:
            return ({"status": "blocked",
                     "detail": (f"before={rec['before']} recorded; after "
                                f"pending develop"),
                     "request": (f"Re-run `card-pipeline.py "
                                 f"{card.get('id')} --stages benchmark` "
                                 f"after the fix lands to capture 'after' "
                                 f"(before={rec['before']}).")}, rec)
    return {"status": "pass",
            "detail": f"{rec['metric'][:80]}: "
                      f"{rec.get('before')} -> {rec.get('after')}"}, rec


# ---------------------------------------------------------------- runner


def opted_in(card: dict) -> bool:
    p = card.get("pipeline")
    if isinstance(p, str):
        return p == "ci"
    if isinstance(p, dict):
        return p.get("opt_in") == "ci"
    return False


def normalize_pipeline(card: dict, existing: dict | None = None) -> dict:
    p = existing if existing is not None else card.get("pipeline")
    if isinstance(p, dict):
        out = dict(p)
    else:
        out = {}
    out["opt_in"] = "ci"
    out.setdefault("stages", {})
    out.setdefault("started", now())
    out["updated"] = now()
    return out


def run(card_id: str, card: dict, sink: Sink, stages: list[str],
        repo: Path, dry_run: bool, quiet: bool) -> int:
    pipeline = normalize_pipeline(card)
    run_doc = {"card": card_id, "started": now_iso(), "mode": type(sink).__name__,
               "stages": {}}
    root = repo_root(repo)
    structure = {}
    exit_code = 0

    def record(name: str, result: dict):
        nonlocal exit_code
        st = result["status"]
        pipeline["stages"][name] = {
            "status": st, "at": now(),
            "detail": result.get("detail", "")[:300]}
        run_doc["stages"][name] = result
        sink.comment(card_id, f"ci {name}: {st} — "
                              f"{result.get('detail','')[:160]}")
        if result.get("request"):
            sink.request(card_id, result["request"],
                         slugify(f"ci-{name}-{card_id}-{result['request'][:60]}"))
        if st == "fail":
            exit_code = 1

    for name in stages:
        if name == "plan":
            record("plan", stage_plan(card))
        elif name == "structure":
            structure = stage_structure(card, root)
            record("structure", structure)
        elif name == "develop":
            if not structure:
                structure = stage_structure(card, root)
            record("develop", stage_develop(card, structure))
        elif name == "audit":
            if not structure:
                structure = stage_structure(card, root)
            record("audit", stage_audit(structure, root))
        elif name == "benchmark":
            dev = pipeline["stages"].get("develop", {})
            develop_ok = dev.get("status") == "pass"
            res, rec = stage_benchmark(card, pipeline, root or repo,
                                       develop_ok, dry_run)
            pipeline["benchmark"] = rec
            record("benchmark", res)

    sink.set_pipeline(card_id, pipeline)
    run_doc["finished"] = now_iso()
    run_doc["pipeline"] = pipeline

    if not dry_run:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        art = REPORT_DIR / f"{card_id}-{ts}.json"
        art.write_text(json.dumps(run_doc, indent=2, ensure_ascii=False))
        if reportlib:
            statuses = [s["status"] for s in pipeline["stages"].values()]
            bad = any(s == "fail" for s in statuses)
            try:
                reportlib.write_meta(
                    REPORT_DIR / "meta.yml", node="ci-pipeline",
                    layer="L1-producer",
                    generated_by=f"scripts/ci/card-pipeline.py {card_id}",
                    status="delta" if bad else "ok",
                    purpose="Per-card pipeline runs — stage results + benchmark before/after",
                    summary=f"{card_id}: " + ",".join(
                        f"{n}={s['status']}" for n, s in
                        pipeline["stages"].items()),
                    sources=[str(art.relative_to(REPO))])
                reportlib.append_timeline(
                    "ci-pipeline", "L1-producer",
                    "delta" if bad else "ok",
                    f"{card_id} run finished", ref=art)
            except Exception as e:
                print(f"warn: meta/timeline failed: {e}", file=sys.stderr)

    summary = " ".join(f"{n}={s['status']}"
                       for n, s in pipeline["stages"].items())
    sink.comment(card_id, f"ci run complete: {summary}")
    sink.flush()
    if not quiet:
        print(f"{card_id}: {summary}")
        print(f"exit {exit_code}")
    return exit_code


# ---------------------------------------------------------------- selftest


def _selftest() -> None:
    """Pure-function smoke test — no HTTP, no git, no card files."""
    card = {"id": "t", "title": "x", "spec": "do thing",
            "metric": "zero errors", "pipeline": "ci"}
    assert opted_in(card)
    assert not opted_in({"id": "t"})
    p = normalize_pipeline(card)
    assert p["opt_in"] == "ci" and p["stages"] == {}
    p2 = normalize_pipeline({}, {"opt_in": "ci",
                                 "stages": {"plan": {"status": "pass"}}})
    assert p2["stages"]["plan"]["status"] == "pass"

    r = stage_plan(card)
    assert r["status"] == "pass", r
    r = stage_plan({"id": "t", "title": "x"})
    assert r["status"] == "fail" and "spec|note" in r["detail"]

    scope = in_scope(["docs/ssot/kanban/cards/t.yml",
                      "stacks/web/public/apps/board/cards.json",
                      "scripts/ci/x.py"], "t")
    assert scope == ["scripts/ci/x.py"], scope

    # benchmark: no metric -> blocked+request; before pinned once
    res, rec = stage_benchmark({"id": "t"}, {}, Path("."), True, False)
    assert res["status"] == "blocked" and res["request"]
    res, rec = stage_benchmark(
        {"id": "t", "benchmark": {"metric": "m", "before": "3"}},
        {}, Path("."), False, False)
    assert rec["before"] == "3" and res["status"] == "blocked"
    res, rec = stage_benchmark(
        {"id": "t", "benchmark": {"metric": "m", "command": "echo 7"}},
        {}, Path("."), True, False)
    assert rec["before"] == "7" and rec["after"] == "7" \
        and res["status"] == "pass", (res, rec)
    # after never overwrites; develop not ok -> blocked
    res, rec = stage_benchmark(
        {"id": "t", "benchmark": {"metric": "m", "command": "echo 9"}},
        {"benchmark": {"metric": "m", "before": "7"}},
        Path("."), False, False)
    assert rec["before"] == "7" and rec.get("after") is None

    # FileSink request dedup / reopen
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        cd = Path(td)
        (cd / "c.yml").write_text(yaml.safe_dump({"id": "c"}))
        fs = FileSink(cd, render=False, dry_run=False)
        fs.request("c", "approve?", "req-1")
        fs.request("c", "approve?", "req-1")  # dup open -> no-op
        card2 = fs.read_card("c")
        assert len(card2["requests"]) == 1
        card2["requests"][0]["status"] = "answered"
        fs.request("c", "approve?", "req-1")  # answered -> reopen
        assert card2["requests"][0]["status"] == "open"
        LOCK.unlink(missing_ok=True)
        fs.flush()
        saved = yaml.safe_load((cd / "c.yml").read_text())
        assert saved["requests"][0]["status"] == "open"
        assert saved["comms"]

    print("selftest ok")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("card", nargs="?", help="kanban card id")
    ap.add_argument("--cards-dir", type=Path,
                    help="card YAML dir — file mode (flock writes)")
    ap.add_argument("--api", help="board-api base url — api mode")
    ap.add_argument("--repo", type=Path, default=Path.cwd(),
                    help="worktree to audit (default: cwd)")
    ap.add_argument("--stages", default=",".join(STAGES),
                    help="comma list — default all five")
    ap.add_argument("--force", action="store_true",
                    help="run even without `pipeline: ci` on the card")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        _selftest()
        return 0
    if not a.card:
        ap.error("card id required")

    stages = [s.strip() for s in a.stages.split(",") if s.strip()]
    bad = [s for s in stages if s not in STAGES]
    if bad:
        ap.error(f"unknown stage(s): {bad}")

    if a.api:
        sink = ApiSink(a.api, cards_dir=a.cards_dir or CARD_DIR,
                       dry_run=a.dry_run)
    else:
        sink = FileSink(a.cards_dir or CARD_DIR,
                        render=not a.no_render, dry_run=a.dry_run)

    try:
        card = sink.read_card(a.card)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not opted_in(card) and not a.force:
        print(f"{a.card}: not opted in (add `pipeline: ci` to the card, "
              f"or pass --force)", file=sys.stderr)
        return 2
    if a.force and not opted_in(card):
        # --force simulates opt-in for this run without writing it
        card["pipeline"] = "ci"
    return run(a.card, card, sink, stages, a.repo.resolve(), a.dry_run,
               a.quiet)


if __name__ == "__main__":
    sys.exit(main())
