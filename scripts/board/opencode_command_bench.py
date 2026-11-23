#!/usr/bin/env python3
"""opencode_command_bench.py — manual-shell baseline vs the allowlisted
/opencode-command publisher (card
ada-opencode-command-publisher-20261108).

Runs BOTH lanes against an identical fixture in tmp space and measures
the bytes an agent actually exchanges:

  manual lane — the pre-tool flow done with real commands: cat the
    deployed file, sha256sum, diff -u, git add+commit in a throwaway
    repo, cp/mv deploy, sha256sum verify. Command stdout is what
    reaches the model context.
  tool lane — opencode_command.handle() receipts; request+response
    JSON bytes counted per call.

Scenarios (same ledger, different starting state):
  publish-update  steady state: canonical == deployed == old content,
                  candidate = new content. Tool runs
                  preview→validate→publish→sync→verify.
  drift-repair    this card's actual job: canonical == menu-restored,
                  deployed == pre-menu live copy. Tool runs
                  preview→sync→verify (canonical already correct).

Fixture: real canonical ada.md + real deployed ada.md, so the diff is
the production one. Authoring the new command text costs the same in
both lanes — reported as a constant, not attributed to either.

Token estimate: chars/4 + 60-char call envelope — the
reports/mcp-files-bench convention used by board_read_bench.py.

    python3 scripts/board/opencode_command_bench.py \
        --json docs/reports/opencode-command-bench-2026-11-20.json \
        --md docs/reports/opencode-command-bench-2026-11-20.md
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter

REPO = Path(__file__).resolve().parents[2]
CALL_ENVELOPE_CHARS = 60
CANON_REL = "stacks/idc02/ada-code/commands/ada.md"
DEPLOYED_FIXTURE = ("/home/tony/.local/share/ada-code/workspace/"
                    ".opencode/commands/ada.md")


def _load():
    spec = importlib.util.spec_from_file_location(
        "opencode_command_bench",
        REPO / "scripts" / "board" / "opencode_command.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(argv, cwd=None) -> tuple:
    t0 = perf_counter()
    r = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=60)
    return r.stdout + r.stderr, (perf_counter() - t0) * 1000


def manual_lane(repo: Path, deploy: Path, candidate: Path,
                publish: bool) -> dict:
    """The real shell pipeline an agent runs today: inspect, write,
    commit (publish scenario), deploy, verify."""
    calls = []
    canon = repo / CANON_REL

    b, ms = _run(["cat", str(deploy)])
    calls.append({"cmd": "cat deployed", "bytes": len(b), "ms": ms})

    b, ms = _run(["sha256sum", str(deploy)])
    calls.append({"cmd": "sha256sum deployed", "bytes": len(b), "ms": ms})

    b, ms = _run(["diff", "-u", str(deploy), str(candidate)])
    calls.append({"cmd": "diff -u deployed candidate",
                  "bytes": len(b), "ms": ms})

    if publish:
        b, ms = _run(["cp", str(candidate), str(canon)])
        calls.append({"cmd": "cp candidate -> canonical",
                      "bytes": len(b), "ms": ms})
        _run(["git", "-C", str(repo), "init", "-q"])
        _run(["git", "-C", str(repo), "add", CANON_REL])
        b, ms = _run(["git", "-C", str(repo), "-c", "user.name=agent",
                      "-c", "user.email=a@b.c", "commit", "-qm",
                      "update ada command", "--", CANON_REL])
        calls.append({"cmd": "git add+commit", "bytes": len(b), "ms": ms})

    tmp = deploy.with_name(deploy.name + ".new-manual")
    _run(["cp", str(candidate), str(tmp)])
    b, ms = _run(["mv", "-f", str(tmp), str(deploy)])
    calls.append({"cmd": "cp+mv deploy", "bytes": len(b), "ms": ms})

    b, ms = _run(["sha256sum", str(deploy)])
    calls.append({"cmd": "sha256sum verify", "bytes": len(b), "ms": ms})
    b, ms = _run(["sha256sum", str(canon)])
    calls.append({"cmd": "sha256sum canonical", "bytes": len(b), "ms": ms})

    ok = deploy.read_bytes() == canon.read_bytes()
    return {"calls": calls, "n_calls": len(calls),
            "response_bytes": sum(c["bytes"] for c in calls),
            "verified": ok}


def tool_lane(oc, name: str, candidate_text: str,
              publish: bool) -> dict:
    calls = []

    def call(op, **kw):
        body = {"op": op, "name": name, **kw}
        t0 = perf_counter()
        res = oc.handle(body, commit_hook=lambda p: None)
        ms = (perf_counter() - t0) * 1000
        calls.append({"op": op,
                      "request_bytes": len(json.dumps(body).encode()),
                      "response_bytes": len(json.dumps(res).encode()),
                      "ms": ms})
        return res

    prev = call("preview")
    sha = prev["canonical_sha"]
    if publish:
        call("validate", content=candidate_text)
        pub = call("publish", content=candidate_text, confirm=True,
                   expect_sha=hashlib.sha256(
                       candidate_text.encode()).hexdigest())
        sha = pub["canonical_sha"]
    call("sync", confirm=True, expect_sha=sha)
    ver = call("verify")
    return {"calls": calls, "n_calls": len(calls),
            "request_bytes": sum(c["request_bytes"] for c in calls),
            "response_bytes": sum(c["response_bytes"] for c in calls),
            "verified": bool(ver.get("match"))}


def _est_tok(nbytes: int, n_calls: int) -> int:
    return round(nbytes / 4 + n_calls * CALL_ENVELOPE_CHARS)


def run_scenario(oc, root: Path, name: str, canon_init: str,
                 old_text: str, new_text: str, publish: bool,
                 reps: int) -> dict:
    tag = name.replace("-", "_")
    repo = root / f"repo-{tag}"
    canon = repo / CANON_REL
    canon.parent.mkdir(parents=True)
    deploy = root / f"ws-{tag}" / ".opencode/commands/ada.md"
    deploy.parent.mkdir(parents=True)
    candidate = root / f"candidate-{tag}.md"
    candidate.write_text(new_text)

    env = dict(os.environ)
    os.environ["OPENCODE_COMMAND_REPO"] = str(repo)
    os.environ["OPENCODE_COMMAND_LOCAL"] = "1"
    saved = dict(oc.COMMANDS["ada"])
    oc.COMMANDS["ada"]["deploy_path"] = str(deploy)
    try:
        ms_m, ms_t = [], []
        man = tool = None
        for _ in range(reps):
            # identical starting state each rep
            deploy.write_text(old_text)
            canon.write_text(old_text if canon_init == "old"
                             else new_text)
            m = manual_lane(repo, deploy, candidate, publish)
            deploy.write_text(old_text)
            canon.write_text(old_text if canon_init == "old"
                             else new_text)
            t = tool_lane(oc, "ada", new_text, publish)
            ms_m.append(sum(c["ms"] for c in m["calls"]))
            ms_t.append(sum(c["ms"] for c in t["calls"]))
            man, tool = m, t
        man["median_ms"] = round(statistics.median(ms_m), 1)
        tool["median_ms"] = round(statistics.median(ms_t), 1)
        man["tokens_est"] = _est_tok(man["response_bytes"],
                                     man["n_calls"])
        tool["tokens_est"] = _est_tok(tool["response_bytes"],
                                      tool["n_calls"])
        man_b, new_b = man["response_bytes"], tool["response_bytes"]
        return {
            "scenario": name,
            "manual": man, "tool": tool,
            "delta": {
                "response_bytes_pct":
                    round(100 * (1 - new_b / man_b), 2),
                "calls": man["n_calls"] - tool["n_calls"],
                "tokens_pct": round(
                    100 * (1 - tool["tokens_est"] / man["tokens_est"]), 2)},
            "evidence_equal": man["verified"] and tool["verified"]}
    finally:
        oc.COMMANDS["ada"].update(saved)
        os.environ.clear()
        os.environ.update(env)


def run(canon_src: Path, deploy_src: Path, reps: int) -> list:
    oc = _load()
    old_text = deploy_src.read_text()   # pre-menu live copy
    new_text = canon_src.read_text()    # menu-restored canonical
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out = [
            run_scenario(oc, root, "publish-update", "old",
                         old_text, new_text, publish=True, reps=reps),
            run_scenario(oc, root, "drift-repair", "new",
                         old_text, new_text, publish=False, reps=reps),
        ]
    return out


def render_md(results: list, date: str, reps: int,
              canon_src: Path, deploy_src: Path) -> str:
    lines = [
        "# opencode-command publisher bench — manual shell vs /opencode-command",
        "",
        f"- date: {date}",
        "- card: ada-opencode-command-publisher-20261108 (ADA-1224)",
        f"- fixture: canonical `{canon_src}` "
        f"({canon_src.stat().st_size:,}B, menu-restored) vs deployed "
        f"`{deploy_src}` ({deploy_src.stat().st_size:,}B, pre-menu live "
        "copy) — the real files",
        f"- reps: {reps} per lane per scenario, identical tmp fixture each rep",
        "- token estimate: chars/4 + 60-char call envelope "
        "(mcp-files-bench / board_read_bench convention)",
        "",
        "| scenario | manual calls | manual resp B | tool calls | "
        "tool resp B | Δbytes | Δcalls | Δtok-est | verified |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        m, t, d = r["manual"], r["tool"], r["delta"]
        lines.append(
            f"| {r['scenario']} | {m['n_calls']} | "
            f"{m['response_bytes']:,} | {t['n_calls']} | "
            f"{t['response_bytes']:,} (+{t['request_bytes']:,} req) | "
            f"{d['response_bytes_pct']}% | {d['calls']} | "
            f"{d['tokens_pct']}% | "
            f"{'yes' if r['evidence_equal'] else 'NO'} |")
    lines += [
        "",
        f"Authoring the new command text (~{canon_src.stat().st_size:,}B) "
        "is identical in both lanes and excluded. `+req` is request-side "
        "JSON (publish carries the full candidate once — that is authored "
        "output, not ingested context).",
        "",
        "Reading: the manual lane's dominant cost is `cat deployed` — "
        "the agent must ingest the whole command file to hand-diff and "
        "hand-verify. The tool's `preview` returns the bounded diff "
        "instead; `publish`/`sync`/`verify` receipts are ~0.5KB each "
        "and the sha gates make silent drift (the ADA0186 loss) a hard "
        "error rather than an unnoticed state.",
        "",
        "## Per-call ledgers", "",
    ]
    for r in results:
        lines.append(f"### {r['scenario']}")
        lines += ["", "| manual cmd | bytes |", "|---|---|"]
        for c in r["manual"]["calls"]:
            lines.append(f"| `{c['cmd']}` | {c['bytes']:,} |")
        lines += ["", "| tool op | req B | resp B |", "|---|---|---|"]
        for c in r["tool"]["calls"]:
            lines.append(f"| `{c['op']}` | {c['request_bytes']:,} | "
                         f"{c['response_bytes']:,} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--canonical",
                    default=str(REPO / "stacks/idc02/ada-code/commands/"
                                "ada.md"))
    ap.add_argument("--deployed", default=DEPLOYED_FIXTURE)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--date", default="2026-11-20")
    ap.add_argument("--json")
    ap.add_argument("--md")
    a = ap.parse_args()

    canon_src, deploy_src = Path(a.canonical), Path(a.deployed)
    results = run(canon_src, deploy_src, a.reps)
    md = render_md(results, a.date, a.reps, canon_src, deploy_src)
    out = {"meta": {"date": a.date, "reps": a.reps,
                    "canonical": str(canon_src),
                    "deployed": str(deploy_src)},
           "results": results}
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    if a.md:
        Path(a.md).write_text(md)
    print(md)
    if not all(r["evidence_equal"] for r in results):
        print("EVIDENCE MISMATCH", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
