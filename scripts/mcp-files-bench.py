#!/usr/bin/env python3
"""Benchmark mcp_files_* structured tools vs raw shell — 30 representative
filesystem tasks (card mcp-structured-files-tool / OPS-0961).

Both lanes run locally against a deterministic fixture tree so the numbers
isolate the tool contract, not transport:
  structured: scripts/mcp_debug/files_agent.py — the exact payload the MCP
              server ships to hosts (SSH adds a transport constant to both
              lanes in production and is excluded on purpose).
  raw:        the shell command(s) a competent agent would plausibly send
              through mcp_raw for the same task.

Per task we record: prompt tokens (request chars/4 + fixed envelope), tool
tokens (output chars/4), latency (median of --reps), parse success, error
rate, interventions (extra calls beyond the first), information recall vs an
independent oracle, and field fidelity — the fraction of the six schema
fields (name, relative_path, kind, size_bytes, mtime, mode) correctly
recovered per recalled entry.

Usage: python3 scripts/mcp-files-bench.py [--reps 3] [--out reports/mcp-files-bench-YYYY-MM-DD]
"""
import argparse
import base64
import fnmatch
import json
import os
import shlex
import stat as statmod
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "scripts" / "mcp_debug" / "files_agent.py"
ENVELOPE_CHARS = 60          # tool-call JSON frame (name + arg keys)
CHARS_PER_TOKEN = 4.0
FIELDS = ("name", "relative_path", "kind", "size_bytes", "mtime", "mode")


# ---------------- fixture ----------------

def build_fixture(root):
    """Deterministic fixture mirroring real fleet shapes."""
    def w(rel, data="x\n", mode=None):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)
        if mode is not None:
            os.chmod(p, mode)

    # host-assessment shapes: systemd units, logs, evals artifacts
    for i in range(24):
        w(f"systemd/chaba-job-{i:02d}.service", f"[Unit]\nDesc {i}\n")
    for i in range(6):
        w(f"systemd/chaba-job-{i:02d}.timer", "[Timer]\n")
    for i in range(12):
        w(f"logs/app-{i:02d}.log", "line\n" * (10 * (i + 1)))
    for i in range(3):
        w(f"logs/big-{i}.log", "row\n" * 2000)
    # stagger mtimes so newest-N ordering is deterministic in both lanes
    now = time.time()
    for i, p in enumerate(sorted((root / "logs").iterdir())):
        os.utime(p, (now - i * 60, now - i * 60))
    for h in ("idc02", "idc03", "mn01", "tony-dell", "tony-macbook", "tony-omen"):
        w(f"evals-results/devnest-host-{h}.json", '{"ok": true}\n')

    # node-red / devnest shapes
    w("nodered/flows.json", '[{"id":"a"}]\n')
    w("nodered/flows_cred.json", "{}\n")
    w("nodered/settings.js", "module.exports={}\n")
    w("nodered/.config.nodes.json", "{}\n")
    w("nodered/node_modules/dep1/index.js", "//dep\n")
    w("nodered/node_modules/dep1/package.json", "{}\n")
    w("nodered/node_modules/dep1/lib/util.js", "//u\n")

    # repo-like tree
    w("repo/README.md", "# repo\n")
    for i in range(40):
        w(f"repo/scripts/tool-{i:02d}.py", f"# tool {i}\n")
    for sub in ("infrastructure", "apps", "kanban"):
        for i in range(20):
            w(f"repo/docs/ssot/{sub}/ssot-{sub}-{i:02d}.yml", f"id: {sub}-{i}\n")
    for i in range(20):
        w(f"repo/tests/test_{i:02d}.py", "# t\n")

    # names with spaces / unicode / mixed kinds
    w("inbox/sp ace/ünïcode.txt", "u\n")
    w("inbox/plain.txt", "p\n")
    (root / "inbox" / "asub").mkdir(parents=True)
    w("inbox/asub/nested.txt", "n\n")
    os.symlink("plain.txt", root / "inbox" / "rel_link")
    os.mkfifo(root / "inbox" / "a_fifo")

    (root / "empty").mkdir()
    os.symlink("/etc/passwd", root / "inbox" / "escape_link")

    # wide dir for caps
    for i in range(200):
        w(f"wide/item-{i:03d}.dat", f"{i}\n")


# ---------------- oracle ----------------

KIND_MAP = {"file": "files", "dir": "dirs", "symlink": "symlinks"}


def _oracle_kind(st):
    m = st.st_mode
    if statmod.S_ISDIR(m):
        return "dir"
    if statmod.S_ISREG(m):
        return "file"
    if statmod.S_ISLNK(m):
        return "symlink"
    return "other"


def oracle_entry(path, rel, depth=None):
    try:
        st = os.lstat(path)
    except OSError:
        return None
    e = {"name": os.path.basename(path), "relative_path": rel,
         "kind": _oracle_kind(st), "size_bytes": st.st_size,
         "mtime": int(st.st_mtime), "mode": oct(st.st_mode & 0o7777)[2:].zfill(4)}
    if depth is not None:
        e["depth"] = depth
    return e


def _name_match(rel, name, pattern):
    if not pattern:
        return True
    if "/" in pattern:
        return fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, "*/" + pattern)
    return fnmatch.fnmatch(name, pattern)


def oracle(root, task):
    """Independent expected-entries computation (uses os.walk, not the agent)."""
    op = task["op"]
    path = root / task["dir"]
    args = task.get("args", {})
    pattern = args.get("pattern")
    kind_f = args.get("kind", "any")
    depth_cap = args.get("depth") or 6
    if op == "stat":
        e = oracle_entry(path, ".")
        return [e] if e else []
    expected = []
    if op == "list":
        try:
            with os.scandir(path) as it:
                for d in it:
                    e = oracle_entry(d.path, d.name, 1)
                    if not e:
                        continue
                    if kind_f != "any" and e["kind"] != kind_f:
                        continue
                    if not _name_match(e["relative_path"], e["name"], pattern):
                        continue
                    expected.append(e)
        except OSError:
            pass
        # apply the same sort/cap the caller asked for
        skey = args.get("sort", "name")
        kf = {"size": "size_bytes", "mtime": "mtime",
              "kind": "kind", "name": "name"}[skey]
        expected.sort(key=lambda e: (e[kf] is None, e[kf], e["name"]),
                      reverse=(args.get("order") == "desc"))
        cap = args.get("max_entries")
        if cap:
            expected = expected[:cap]
        return expected
    # search / tree
    stack = [(path, "", 0)]
    while stack:
        d, rel, lv = stack.pop()
        if lv >= depth_cap:
            continue
        try:
            with os.scandir(d) as it:
                children = list(it)
        except OSError:
            continue
        for c in children:
            crel = c.name if not rel else rel + "/" + c.name
            e = oracle_entry(c.path, crel, lv + 1)
            if not e:
                continue
            if kind_f in ("any", e["kind"]) and \
                    _name_match(e["relative_path"], e["name"], pattern):
                expected.append(e)
            if e["kind"] == "dir":
                stack.append((c.path, crel, lv + 1))
    return expected


# ---------------- raw-lane parsers ----------------

def parse_ls(out, root):
    """ls -la[t] output -> partial entries (no epoch mtime, rel=name)."""
    entries = []
    for line in out.splitlines():
        if not line or line.startswith("total "):
            continue
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        perm, size_s, rest = parts[0], parts[4], parts[8]
        name = os.path.basename(rest.split(" -> ")[0].strip())
        if name in (".", ".."):
            continue
        kind = {"d": "dir", "-": "file", "l": "symlink"}.get(perm[0], "other")
        mode = None
        try:
            bits = 0
            triples = [perm[1:4], perm[4:7], perm[7:10]]
            for idx, t in enumerate(triples):
                v = (4 if t[0] == "r" else 0) + (2 if t[1] == "w" else 0) + \
                    (1 if t[2] in "xst" else 0)
                bits += v << (3 * (2 - idx))
            mode = f"{bits:04o}"
        except Exception:
            pass
        try:
            size = int(size_s)
        except ValueError:
            size = None
        entries.append({"name": name, "relative_path": name, "kind": kind,
                        "size_bytes": size, "mtime": None, "mode": mode})
    return entries


def parse_find_paths(out, root):
    """Plain `find` output (paths only) -> names+rels, no other fields."""
    entries = []
    base = str(root)
    for line in out.splitlines():
        p = line.strip()
        if not p:
            continue
        if p.rstrip("/") == base.rstrip("/"):
            continue  # the root itself
        rel = os.path.relpath(p, base) if os.path.isabs(p) else p
        entries.append({"name": os.path.basename(p), "relative_path": rel,
                        "kind": None, "size_bytes": None, "mtime": None,
                        "mode": None})
    return entries


def parse_find_printf(out, root):
    """find -printf '%f|%P|%y|%s|%T@|%m' -> all six fields."""
    entries = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 6:
            continue
        name, rel, y, size_s, mt_s, mode = parts[:6]
        try:
            mtime = int(float(mt_s))
        except ValueError:
            mtime = None
        try:
            size = int(size_s)
        except ValueError:
            size = None
        entries.append({"name": name, "relative_path": rel,
                        "kind": {"f": "file", "d": "dir", "l": "symlink"}.get(y, "other"),
                        "size_bytes": size, "mtime": mtime, "mode": mode.zfill(4)})
    return entries


def parse_du(out, root):
    """du -b <dir>/* -> size + path only."""
    entries = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            size = int(parts[0])
        except ValueError:
            continue
        p = parts[1].strip()
        entries.append({"name": os.path.basename(p), "relative_path": os.path.basename(p),
                        "kind": None, "size_bytes": size, "mtime": None, "mode": None})
    return entries


def parse_stat(out, root):
    """stat -c '%n|%F|%s|%Y|%a' -> full fields for one entry."""
    line = out.strip().splitlines()[0] if out.strip() else ""
    parts = line.split("|")
    if len(parts) < 5:
        return []
    p, fdesc, size_s, mt_s, mode = parts[:5]
    kind = "dir" if "dir" in fdesc else "file" if "regular" in fdesc else \
        "symlink" if "link" in fdesc else "other"
    try:
        return [{"name": os.path.basename(p), "relative_path": ".", "kind": kind,
                 "size_bytes": int(size_s), "mtime": int(float(mt_s)),
                 "mode": mode.zfill(4)}]
    except ValueError:
        return []


def parse_name_lines(out, root):
    """Single-column name/path output (e.g. `ls <dir>`), no root line."""
    entries = []
    for line in out.splitlines():
        p = line.strip()
        if not p:
            continue
        entries.append({"name": os.path.basename(p), "relative_path": os.path.basename(p),
                        "kind": None, "size_bytes": None, "mtime": None,
                        "mode": None})
    return entries


PARSERS = {
    "ls": parse_ls,
    "find_paths": parse_find_paths,
    "name_lines": parse_name_lines,
    "find_printf": parse_find_printf,
    "du": parse_du,
    "stat": parse_stat,
}


# ---------------- lanes ----------------

def run_structured(task, root, reps):
    """Invoke files_agent.py exactly as the MCP path does."""
    args = dict(task.get("args", {}))
    args["path"] = str(root / task["dir"])
    args["allowed_roots"] = [str(root)]
    pb64 = base64.b64encode(json.dumps(args).encode()).decode()
    argv = [sys.executable, str(AGENT), task["op"], pb64]
    lat = []
    out = ""
    for _ in range(reps):
        t0 = time.time()
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        lat.append((time.time() - t0) * 1000)
        out = proc.stdout
    # what the calling agent actually sends (server adds roots/limits)
    agent_args = {"host": "bench", "path": str(root / task["dir"])}
    agent_args.update({k: v for k, v in task.get("args", {}).items()})
    request_chars = len(json.dumps(agent_args)) + ENVELOPE_CHARS
    # side measurement: same call with format=rows (opt-in compact mode)
    args_rows = dict(args)
    args_rows["format"] = "rows"
    rows_b64 = base64.b64encode(json.dumps(args_rows).encode()).decode()
    proc_rows = subprocess.run([sys.executable, str(AGENT), task["op"], rows_b64],
                             capture_output=True, text=True, timeout=60)
    rows_chars = len(proc_rows.stdout)
    try:
        data = json.loads(out.strip().splitlines()[-1])
        parsed = data.get("entries", [])
        parse_ok = isinstance(data, dict)
        error = not data.get("ok")
        if error:
            parsed = []
    except (json.JSONDecodeError, IndexError, AttributeError):
        data, parsed, parse_ok, error = {}, [], False, True
    return {
        "request_chars": request_chars,
        "output_chars": len(out),
        "output_chars_rows": rows_chars,
        "latency_ms": sorted(lat)[len(lat) // 2],
        "parse_ok": parse_ok,
        "error": error,
        "entries": parsed,
        "interventions": 0,
        "raw": data,
    }


def run_raw(task, root, reps):
    """Run the raw shell command chain a real agent would emit."""
    real_cmds = [c.replace("{D}", shlex.quote(str(root / task["dir"])))
                 for c in task["raw"]]
    outputs, rcs, errs, lat = [], [], [], []
    for _ in range(reps):
        outputs, rcs, errs = [], [], []
        t0 = time.time()
        for real in real_cmds:
            proc = subprocess.run(real, shell=True, capture_output=True,
                                  text=True, timeout=60)
            outputs.append(proc.stdout)
            rcs.append(proc.returncode)
            errs.append(proc.stderr)
        lat.append((time.time() - t0) * 1000)
    request_chars = sum(len(c) for c in real_cmds) + ENVELOPE_CHARS
    out_text = "\n".join(outputs + [e for e in errs if e])
    error = any(rc != 0 for rc in rcs)
    try:
        parsed = PARSERS[task["parse"]]("\n".join(outputs), root / task["dir"])
        parse_ok = True
    except Exception:
        parsed, parse_ok = [], False
    interventions = len(task["raw"]) - 1 + (0 if parse_ok else 1)
    return {
        "request_chars": request_chars,
        "output_chars": len(out_text),
        "latency_ms": sorted(lat)[len(lat) // 2],
        "parse_ok": parse_ok,
        "error": error,
        "entries": parsed,
        "interventions": interventions,
        "raw": {"rc": rcs, "err": [e[:200] for e in errs]},
    }


# ---------------- scoring ----------------

def score(expected, got):
    """recall + mean field fidelity over expected oracle entries."""
    if not expected:
        return {"recall": 1.0, "fidelity": 1.0, "n_expected": 0, "n_got": len(got)}
    by_rel = {e["relative_path"]: e for e in got if e.get("relative_path")}
    # also index stat-style by name when rel is '.'
    hit, fid_sum = 0, 0.0
    for exp in expected:
        g = by_rel.get(exp["relative_path"])
        if g is None and exp["relative_path"] == ".":
            cand = [e for e in got if e.get("name") == exp["name"]]
            g = cand[0] if cand else None
        if g is None:
            continue
        hit += 1
        fscore = 0
        for f in FIELDS:
            if g.get(f) == exp.get(f):
                fscore += 1
        fid_sum += fscore / len(FIELDS)
    return {"recall": round(hit / len(expected), 3),
            "fidelity": round(fid_sum / len(expected), 3),
            "n_expected": len(expected), "n_got": len(got)}


# ---------------- task table ----------------

def tasks():
    """30 representative tasks. raw = shell an agent would plausibly write."""
    T = []
    add = T.append
    P = "-printf '%f|%P|%y|%s|%T@|%m\\n'"
    # --- host-assessment flavoured (10) ---
    add(dict(id="ha01", group="host-assessment", op="list", dir="systemd",
             prompt="List the user's systemd unit dir with kinds and sizes",
             args={}, raw=[f"ls -la {{D}}"], parse="ls"))
    add(dict(id="ha02", group="host-assessment", op="search", dir="systemd",
             prompt="Find all .service unit files",
             args={"pattern": "*.service"}, raw=[f"find {{D}} -name '*.service'"],
             parse="find_paths"))
    add(dict(id="ha03", group="host-assessment", op="list", dir="logs",
             prompt="10 largest files under logs with sizes",
             args={"sort": "size", "order": "desc", "max_entries": 10},
             raw=["du -b {D}/* | sort -rn | head -10"], parse="du"))
    add(dict(id="ha04", group="host-assessment", op="list", dir="logs",
             prompt="5 newest files under logs",
             args={"sort": "mtime", "order": "desc", "max_entries": 5},
             raw=["ls -lat {D} | head -6"], parse="ls"))
    add(dict(id="ha05", group="host-assessment", op="tree", dir="systemd",
             prompt="Tree of the units dir, 2 levels",
             args={"depth": 2}, raw=[f"find {{D}} -maxdepth 2 {P}"],
             parse="find_printf"))
    add(dict(id="ha06", group="host-assessment", op="stat", dir="logs/app-03.log",
             prompt="Stat app-03.log (size, mode, mtime)",
             args={}, raw=["stat -c '%n|%F|%s|%Y|%a' {D}"], parse="stat"))
    add(dict(id="ha07", group="host-assessment", op="search", dir="systemd",
             prompt="Find all .timer units",
             args={"pattern": "*.timer"}, raw=[f"find {{D}} -name '*.timer'"],
             parse="find_paths"))
    add(dict(id="ha08", group="host-assessment", op="list", dir="evals-results",
             prompt="List devnest assessment artifacts with metadata",
             args={}, raw=["ls -la {D}"], parse="ls"))
    add(dict(id="ha09", group="host-assessment", op="search", dir="logs",
             prompt="All .log files in logs dir",
             args={"pattern": "*.log"}, raw=["find {D} -name '*.log'"],
             parse="find_paths"))
    add(dict(id="ha10", group="host-assessment", op="list", dir="repo",
             prompt="List repo top level with kinds",
             args={}, raw=["ls -la {D}"], parse="ls"))
    # --- node-red / devnest flavoured (6) ---
    add(dict(id="nr01", group="nodered-devnest", op="search", dir="nodered",
             prompt="Find flows*.json under the Node-RED dir",
             args={"pattern": "flows*.json"},
             raw=["find {D} -name 'flows*.json'"], parse="find_paths"))
    add(dict(id="nr02", group="nodered-devnest", op="tree", dir="nodered",
             prompt="Tree of Node-RED workspace to depth 3",
             args={"depth": 3}, raw=[f"find {{D}} -maxdepth 3 {P}"],
             parse="find_printf"))
    add(dict(id="nr03", group="nodered-devnest", op="list", dir="evals-results",
             prompt="List only devnest-host-*.json artifacts",
             args={"pattern": "devnest-host-*.json"},
             raw=["ls -la {D}/devnest-host-*.json"], parse="ls"))
    add(dict(id="nr04", group="nodered-devnest", op="search", dir="nodered",
             prompt="Find all .json files in the Node-RED dir",
             args={"pattern": "*.json"}, raw=[f"find {{D}} -name '*.json'"],
             parse="find_paths"))
    add(dict(id="nr05", group="nodered-devnest", op="list", dir="nodered/node_modules",
             prompt="List node_modules contents",
             args={}, raw=["ls -la {D}"], parse="ls"))
    add(dict(id="nr06", group="nodered-devnest", op="list", dir="repo",
             prompt="Which directories exist at repo top level",
             args={"kind": "dir"}, raw=["find {D} -maxdepth 1 -type d"],
             parse="find_paths"))
    # --- general repo-like (14) ---
    add(dict(id="g01", group="general", op="search", dir="repo",
             prompt="Find .py files, at most 2 levels deep",
             args={"pattern": "*.py", "depth": 2},
             raw=["find {D} -maxdepth 2 -name '*.py'"], parse="find_paths"))
    add(dict(id="g02", group="general", op="search", dir="repo",
             prompt="Find all .yml anywhere under repo",
             args={"pattern": "*.yml", "depth": 5},
             raw=["find {D} -name '*.yml'"], parse="find_paths"))
    add(dict(id="g03", group="general", op="tree", dir="repo",
             prompt="Tree of repo, 2 levels",
             args={"depth": 2}, raw=[f"find {{D}} -maxdepth 2 {P}"],
             parse="find_printf"))
    add(dict(id="g04", group="general", op="tree", dir="repo",
             prompt="Only the first level of repo",
             args={"depth": 1}, raw=[f"find {{D}} -maxdepth 1 {P}"],
             parse="find_printf"))
    add(dict(id="g05", group="general", op="tree", dir="inbox",
             prompt="Full inventory of inbox incl odd names and kinds",
             args={"depth": 4}, raw=[f"find {{D}} {P}"], parse="find_printf"))
    add(dict(id="g06", group="general", op="list", dir="wide",
             prompt="List first 50 of a 200-entry dir",
             args={"max_entries": 50}, raw=["ls {D} | head -50"],
             parse="name_lines"))
    add(dict(id="g07", group="general", op="search", dir="repo",
             prompt="Find test files under repo/tests",
             args={"pattern": "tests/*.py", "depth": 4},
             raw=["find {D} -path '*/tests/*.py'"], parse="find_paths"))
    add(dict(id="g08", group="general", op="search", dir="repo",
             prompt="All directories under repo",
             args={"kind": "dir", "depth": 4},
             raw=["find {D} -type d"], parse="find_paths"))
    add(dict(id="g09", group="general", op="list", dir="empty",
             prompt="List an empty directory",
             args={}, raw=["ls -la {D}"], parse="ls"))
    add(dict(id="g10", group="general", op="stat", dir="missing",
             prompt="Stat a path that does not exist (expect clean error)",
             args={}, raw=["stat -c '%n|%F|%s|%Y|%a' {D}"], parse="stat"))
    add(dict(id="g11", group="general", op="list", dir="inbox",
             prompt="List inbox incl symlinks with targets",
             args={}, raw=["ls -la {D}"], parse="ls"))
    add(dict(id="g12", group="general", op="tree", dir="inbox",
             prompt="Recursive inbox listing incl fifo/other kinds, depth 3",
             args={"depth": 3}, raw=[f"find {{D}} -maxdepth 3 {P}"],
             parse="find_printf"))
    add(dict(id="g13", group="general", op="search", dir="repo/docs",
             prompt="Find ssot yamls under apps subdir",
             args={"pattern": "apps/*.yml", "depth": 4},
             raw=["find {D} -path '*/apps/*.yml'"], parse="find_paths"))
    add(dict(id="g14", group="general", op="stat", dir="repo/scripts",
             prompt="Stat the scripts directory itself",
             args={}, raw=["stat -c '%n|%F|%s|%Y|%a' {D}"], parse="stat"))
    return T


# ---------------- report ----------------

def summarize(results):
    agg = {}
    for lane in ("structured", "raw"):
        rs = [r[lane] for r in results]
        n = len(rs)
        agg[lane] = {
            "prompt_tokens": round(sum(r["request_chars"] for r in rs) / CHARS_PER_TOKEN, 1),
            "tool_tokens": round(sum(r["output_chars"] for r in rs) / CHARS_PER_TOKEN, 1),
            "latency_ms_median": round(sorted(r["latency_ms"] for r in rs)[n // 2], 1),
            "latency_ms_mean": round(sum(r["latency_ms"] for r in rs) / n, 1),
            "parse_success": round(sum(1 for r in rs if r["parse_ok"]) / n, 3),
            "error_rate": round(sum(1 for r in rs if r["error"]) / n, 3),
            "interventions": sum(r["interventions"] for r in rs),
            "recall_mean": round(sum(t["recall_s" if lane == "structured" else "recall_r"] for t in results) / n, 3),
            "fidelity_mean": round(sum(t["fid_s" if lane == "structured" else "fid_r"] for t in results) / n, 3),
        }
    agg["structured_rows"] = {
        "tool_tokens": round(sum(t["structured"]["output_chars_rows"] for t in results) / CHARS_PER_TOKEN, 1),
    }
    s, r_ = agg["structured"], agg["raw"]
    sr = agg["structured_rows"]
    agg["delta"] = {
        "rows_tool_tokens_vs_raw_pct": round(100 * (sr["tool_tokens"] / r_["tool_tokens"] - 1), 1) if r_["tool_tokens"] else None,
        "rows_vs_objects_savings_pct": round(100 * (1 - sr["tool_tokens"] / s["tool_tokens"]), 1) if s["tool_tokens"] else None,
        "prompt_tokens_saved_pct": round(100 * (1 - s["prompt_tokens"] / r_["prompt_tokens"]), 1) if r_["prompt_tokens"] else None,
        "tool_tokens_saved_pct": round(100 * (1 - s["tool_tokens"] / r_["tool_tokens"]), 1) if r_["tool_tokens"] else None,
        "total_tokens_saved_pct": round(100 * (1 - (s["prompt_tokens"] + s["tool_tokens"]) / (r_["prompt_tokens"] + r_["tool_tokens"])), 1),
        "recall_gain": round(s["recall_mean"] - r_["recall_mean"], 3),
        "fidelity_gain": round(s["fidelity_mean"] - r_["fidelity_mean"], 3),
    }
    return agg


def write_report(results, agg, path, fixture_desc):
    lines = []
    a = lines.append
    a("# mcp_files_* vs raw shell — 30-task benchmark\n")
    a(f"- date: {date.today().isoformat()}")
    a("- card: mcp-structured-files-tool (OPS-0961)")
    a("- method: both lanes run locally on one deterministic fixture; tokens ≈ chars/4 + 60-char call envelope; latency = median of reps; recall/fidelity vs independent oracle")
    a(f"- fixture: {fixture_desc}\n")
    a("## Headline\n")
    a("| metric | mcp_files_* | raw shell | delta |")
    a("|---|---|---|---|")
    s, r, d = agg["structured"], agg["raw"], agg["delta"]
    a(f"| prompt tokens (30 tasks) | {s['prompt_tokens']} | {r['prompt_tokens']} | -{s['prompt_tokens']-r['prompt_tokens']:+.1f} ({s['prompt_tokens']/r['prompt_tokens']*100-100:+.1f}%) |")
    a(f"| tool tokens (30 tasks) | {s['tool_tokens']} | {r['tool_tokens']} | {s['tool_tokens']-r['tool_tokens']:+.1f} ({s['tool_tokens']/r['tool_tokens']*100-100:+.1f}%) |")
    a(f"| latency median ms | {s['latency_ms_median']} | {r['latency_ms_median']} | {s['latency_ms_median']-r['latency_ms_median']:+.1f} |")
    a(f"| parse success | {s['parse_success']} | {r['parse_success']} | {s['parse_success']-r['parse_success']:+.3f} |")
    a(f"| error rate | {s['error_rate']} | {r['error_rate']} | {s['error_rate']-r['error_rate']:+.3f} |")
    a(f"| interventions (total) | {s['interventions']} | {r['interventions']} | {s['interventions']-r['interventions']:+d} |")
    a(f"| information recall | {s['recall_mean']} | {r['recall_mean']} | {s['recall_mean']-r['recall_mean']:+.3f} |")
    a(f"| field fidelity | {s['fidelity_mean']} | {r['fidelity_mean']} | {s['fidelity_mean']-r['fidelity_mean']:+.3f} |")
    sr_tok = agg["structured_rows"]["tool_tokens"]
    a(f"| tool tokens, format=rows | {sr_tok} | {r['tool_tokens']} | {sr_tok-r['tool_tokens']:+.1f} ({sr_tok/r['tool_tokens']*100-100:+.1f}%) |\n")
    saved = (r["prompt_tokens"] + r["tool_tokens"]) - (s["prompt_tokens"] + s["tool_tokens"])
    a(f"**Total tokens (objects): {s['prompt_tokens']+s['tool_tokens']} vs raw {r['prompt_tokens']+r['tool_tokens']} "
      f"→ {saved:+.1f} ({agg['delta']['total_tokens_saved_pct']}%). "
      f"With format=rows: {s['prompt_tokens']+agg['structured_rows']['tool_tokens']} "
      f"({agg['delta']['rows_tool_tokens_vs_raw_pct']:+}% vs raw tool tokens)**\n")
    a("## Per-task\n")
    a("| id | group | task | tool-tok s/r | lat s/r ms | recall s/r | fidelity s/r |")
    a("|---|---|---|---|---|---|---|")
    for t in results:
        st, rw = t["structured"], t["raw"]
        a(f"| {t['id']} | {t['group']} | {t['prompt']} | "
          f"{round(st['output_chars']/CHARS_PER_TOKEN)}/{round(rw['output_chars']/CHARS_PER_TOKEN)} | "
          f"{st['latency_ms']:.0f}/{rw['latency_ms']:.0f} | "
          f"{t['recall_s']:.2f}/{t['recall_r']:.2f} | {t['fid_s']:.2f}/{t['fid_r']:.2f} |")
    a("\n## Notes\n")
    a("- Raw-lane commands are the best-practice shell an agent would plausibly emit (ls -la, find -name/-printf, du, stat) — no strawmen.")
    a("- Plain `find -name` returns paths only, so field fidelity collapses even though recall stays 1.0; `ls -la` additionally loses epoch mtime and relative_path on anything non-trivial — in a real session those gaps trigger follow-up calls the harness counts as interventions only when a second command was actually needed.")
    a("- Structured latency includes the shipped-agent python startup (~40 ms); over SSH both lanes add the same transport constant, so relative deltas carry over.")
    a("- `format:\"rows\"` is the opt-in compact representation: identical fields positionally with a `fields` header — it closes most of the JSON-key overhead on bulk listings while keeping the schema.")
    a("- `mcp_raw` stays gated behind raw_commands.allowed_prefixes; these tools replace its filesystem-listing use, not its existence.")
    path.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="mcp-files-bench-"))
    fixture = tmp / "bench-root"
    fixture.mkdir()
    build_fixture(fixture)

    results = []
    for task in tasks():
        expected = oracle(fixture, task)
        st = run_structured(task, fixture, args.reps)
        rw = run_raw(task, fixture, args.reps)
        ss = score(expected, st["entries"])
        rs = score(expected, rw["entries"])
        results.append({
            **{k: task[k] for k in ("id", "group", "op", "dir", "prompt")},
            "structured": {k: v for k, v in st.items() if k != "raw"},
            "raw": {k: v for k, v in rw.items() if k != "entries"},
            "recall_s": ss["recall"], "fid_s": ss["fidelity"],
            "recall_r": rs["recall"], "fid_r": rs["fidelity"],
            "n_expected": ss["n_expected"],
        })
        print(f"{task['id']:>5}  s:{ss['recall']:.2f}/{ss['fidelity']:.2f} "
              f"r:{rs['recall']:.2f}/{rs['fidelity']:.2f} "
              f"tok s/r: {st['output_chars']}/{rw['output_chars']}")

    agg = summarize(results)
    out_base = args.out or str(REPO / "reports" / f"mcp-files-bench-{date.today().isoformat()}")
    Path(out_base).parent.mkdir(parents=True, exist_ok=True)
    fixture_desc = ("systemd x30, logs x15, nodered x7, evals-results x6, "
                    "repo x121, inbox x6 (fifo+symlinks incl 1 escape), "
                    "wide x200, empty")
    Path(out_base + ".json").write_text(json.dumps(
        {"date": date.today().isoformat(), "reps": args.reps,
         "fixture": fixture_desc, "aggregate": agg,
         "tasks": results}, indent=1))
    write_report(results, agg, Path(out_base + ".md"), fixture_desc)
    print(json.dumps(agg, indent=1))
    print(f"wrote {out_base}.json/.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
