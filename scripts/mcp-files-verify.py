#!/usr/bin/env python3
"""Verifier for mcp_files_{list,stat,search,tree} (card mcp-structured-files-tool).

Levels:
  1. files_agent.py direct (subprocess): ops, schema, caps, security matrix.
  2. Tool layer (in-process, injected local host): full run_on_host path.
  3. MCP stdio: tools/list exposes the 4 tools; error envelope parses.

Exit 0 only if every check passes.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

AGENT = REPO / "scripts" / "mcp_debug" / "files_agent.py"
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:200]})
    return bool(ok)


def run_agent(op, params):
    pb64 = base64.b64encode(json.dumps(params).encode()).decode()
    proc = subprocess.run(
        [sys.executable, str(AGENT), op, pb64],
        capture_output=True, text=True, timeout=30)
    line = (proc.stdout or "").strip().splitlines()
    try:
        return json.loads(line[-1]) if line else {"ok": False, "error": "no output", "err": proc.stderr[:200]}
    except json.JSONDecodeError:
        return {"ok": False, "error": "not json", "out": proc.stdout[:200], "err": proc.stderr[:200]}


def build_fixture(root):
    """Deterministic fixture tree under root."""
    (root / "dir_a" / "sub" / "deeper").mkdir(parents=True)
    (root / "dir_b").mkdir()
    (root / "wide").mkdir()
    (root / "noaccess").mkdir()
    (root / "sp ace").mkdir()
    for i in (1, 2, 3):
        (root / "dir_a" / f"f{i}.txt").write_text(f"x{i}\n")
    (root / "dir_a" / "sub" / "deep.md").write_text("deep\n")
    (root / "dir_a" / "sub" / "deeper" / "x.md").write_text("x\n")
    (root / "dir_b" / "big.bin").write_bytes(b"\0" * 3000)
    for i in range(30):
        (root / "wide" / f"f{i:02d}.txt").write_text("f\n")
    (root / "noaccess" / "secret.txt").write_text("s\n")
    os.chmod(root / "noaccess", 0)
    (root / "sp ace" / "ünïcode.txt").write_text("u\n")
    os.symlink("/etc/passwd", root / "escape_link")
    os.symlink("dir_a/f1.txt", root / "ok_link")
    os.symlink(".", root / "loop_link")


SCHEMA_KEYS = {"name", "relative_path", "kind", "size_bytes", "mtime", "mode"}
ENVELOPE_KEYS = {"ok", "tool", "root", "entries", "truncated", "errors", "observed_at"}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="mcp-files-verify-"))
    fix = tmp / "fixture"
    fix.mkdir()
    build_fixture(fix)
    roots = [str(fix)]
    base = {"allowed_roots": roots}

    def params(path, **kw):
        p = dict(base)
        p["path"] = path
        p.update(kw)
        return p

    # ---------- level 1: agent direct ----------
    r = run_agent("list", params(str(fix)))
    check("agent.list.ok", r.get("ok"), r.get("error"))
    check("agent.list.envelope", ENVELOPE_KEYS <= set(r), sorted(r)[:20])
    entries = r.get("entries", [])
    check("agent.list.entry_schema",
          all(SCHEMA_KEYS <= set(e) for e in entries), len(entries))
    names = {e["name"] for e in entries}
    check("agent.list.entries", {"dir_a", "dir_b", "wide", "escape_link"} <= names,
          sorted(names))
    check("agent.list.link_escape_flagged",
          any(e.get("link_escape") for e in entries if e["name"] == "escape_link"),
          [e for e in entries if e["name"] == "escape_link"])
    check("agent.list.errors_has_escape",
          any("escape" in e.get("error", "") for e in r.get("errors", [])),
          r.get("errors"))

    r = run_agent("stat", params(str(fix / "dir_a" / "f1.txt")))
    e0 = (r.get("entries") or [{}])[0]
    check("agent.stat.single", r.get("ok") and len(r.get("entries", [])) == 1)
    check("agent.stat.fields", e0.get("kind") == "file" and e0.get("size_bytes") == 3
          and str(e0.get("mode", "")).startswith("0"), e0)

    r = run_agent("search", params(str(fix), pattern="*.txt", depth=6))
    found = {e["relative_path"] for e in r.get("entries", [])}
    check("agent.search.glob", "dir_a/f1.txt" in found and
          "dir_b/big.bin" not in found and "wide/f07.txt" in found,
          sorted(found))
    r = run_agent("search", params(str(fix), pattern="*.md", depth=6))
    found = {e["relative_path"] for e in r.get("entries", [])}
    check("agent.search.recurses", {"dir_a/sub/deep.md", "dir_a/sub/deeper/x.md"} <= found,
          sorted(found))

    r = run_agent("search", params(str(fix), pattern="sub/*.md", depth=6))
    found = {e["relative_path"] for e in r.get("entries", [])}
    check("agent.search.path_pattern", found == {"dir_a/sub/deep.md", "dir_a/sub/deeper/x.md"},
          sorted(found))

    r = run_agent("tree", params(str(fix), depth=1))
    rels = {e["relative_path"] for e in r.get("entries", [])}
    check("agent.tree.depth1", "dir_a/f1.txt" not in rels and "dir_a" in rels,
          sorted(rels))
    r = run_agent("tree", params(str(fix), depth=3))
    rels = {e["relative_path"] for e in r.get("entries", [])}
    check("agent.tree.depth3", "dir_a/sub/deep.md" in rels and
          "dir_a/sub/deeper/x.md" not in rels, sorted(rels))
    check("agent.tree.no_noaccess_descent",
          not any(e["relative_path"].startswith("noaccess/") for e in r["entries"]), "")
    check("agent.tree.perm_error_recorded",
          any("noaccess" in e.get("path", "") for e in r.get("errors", [])),
          r.get("errors"))
    check("agent.tree.loop_safe", r.get("ok") and
          not any(e["relative_path"].startswith("loop_link/") for e in r["entries"]), "")

    r = run_agent("list", params(str(fix / "wide"), max_entries=5))
    check("agent.list.max_entries", len(r.get("entries", [])) == 5 and r.get("truncated"),
          (len(r.get("entries", [])), r.get("truncated_reason")))

    r = run_agent("list", params(str(fix), format="rows"))
    check("agent.list.rows_format",
          r.get("ok") and r.get("format") == "rows" and
          r.get("fields")[:6] == ["name", "relative_path", "kind", "size_bytes", "mtime", "mode"] and
          all(isinstance(row, list) and len(row) == len(r["fields"]) for row in r["entries"]),
          r.get("fields"))
    objs = run_agent("list", params(str(fix)))
    check("agent.list.rows_smaller",
          len(json.dumps(r)) < len(json.dumps(objs)),
          (len(json.dumps(r)), len(json.dumps(objs))))
    check("agent.list.rows_same_data",
          {row[0] for row in r["entries"]} == {e["name"] for e in objs["entries"]}, "")

    r = run_agent("list", params(str(fix / "wide"), sort="name", order="desc"))
    names = [e["name"] for e in r.get("entries", [])]
    check("agent.list.sort_desc", names == sorted(names, reverse=True), names[:5])

    # security matrix
    r = run_agent("list", params(str(fix / ".." / "fixture")))
    check("sec.dotdot_rejected", not r.get("ok") and ".." in r.get("error", ""), r.get("error"))
    r = run_agent("list", params("/etc"))
    check("sec.outside_roots_rejected", not r.get("ok"), r.get("error"))
    r = run_agent("list", params(str(fix / "escape_link")))
    check("sec.symlink_root_rejected", not r.get("ok"), r.get("error"))
    r = run_agent("stat", params(str(fix / "escape_link")))
    check("sec.symlink_stat_rejected", not r.get("ok"), r.get("error"))
    r = run_agent("list", params(str(fix / "ok_link")))
    check("sec.symlink_dir_not_dir", not r.get("ok") and "not a directory" in r.get("error", ""),
          r.get("error"))
    r = run_agent("list", params(str(fix / "missing")))
    check("sec.missing_clean_error", not r.get("ok") and "not found" in r.get("error", ""),
          r.get("error"))
    r = run_agent("bogus", params(str(fix)))
    check("sec.bad_op", not r.get("ok"), r.get("error"))
    r = run_agent("tree", params(str(fix), depth=99))
    check("sec.depth_hard_clamped", r.get("ok") and r.get("depth") == 12 and
          all(e.get("depth", 0) <= 12 for e in r.get("entries", [])),
          r.get("depth"))

    # ---------- level 2: tool layer (injected local host) ----------
    try:
        from mcp_debug.config import HOSTS, FILE_LIMITS
        from mcp_debug import files as mfiles
        HOSTS["_local_verify"] = {"local": True, "hostname": "localhost"}
        FILE_LIMITS.setdefault("allowed_path_prefixes", {})["_local_verify"] = roots
        r = mfiles.mcp_files_list("_local_verify", str(fix))
        check("tool.list.e2e", r.get("ok") and r.get("host") == "_local_verify"
              and r.get("tool") == "mcp_files_list", r.get("error"))
        check("tool.list.same_entries",
              {e["name"] for e in r.get("entries", [])} >= {"dir_a", "wide"}, "")
        r = mfiles.mcp_files_search("_local_verify", str(fix), "*.md", depth=4)
        check("tool.search.e2e", r.get("ok") and
              len(r.get("entries", [])) == 2, r.get("entries"))
        r = mfiles.mcp_files_stat("_local_verify", str(fix / "dir_a" / "f1.txt"))
        check("tool.stat.e2e", r.get("ok") and r["entries"][0]["size_bytes"] == 3)
        r = mfiles.mcp_files_tree("_local_verify", str(fix), depth=2)
        check("tool.tree.e2e", r.get("ok") and r.get("counts", {}).get("dirs") >= 4,
              r.get("counts"))
        r = mfiles.mcp_files_list("_local_verify", "/etc")
        check("tool.outside_allowlist", not r.get("ok"), r.get("error"))
        r = mfiles.mcp_files_list("_bogus_host", str(fix))
        check("tool.unknown_host", not r.get("ok") and "unknown host" in r.get("error", ""),
              r.get("error"))
        r = mfiles.mcp_files_list("_local_verify", str(fix / ".." / "x"))
        check("tool.dotdot_rejected", not r.get("ok"), r.get("error"))
    except Exception as exc:
        check("tool.layer.exception", False, repr(exc))

    # ---------- level 3: MCP stdio ----------
    try:
        env = dict(os.environ, PYTHONPATH=str(REPO / "scripts"))
        proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_debug.server"],
            cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)

        def rpc(method, params_, rid):
            proc.stdin.write(json.dumps(
                {"jsonrpc": "2.0", "id": rid, "method": method, "params": params_}) + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())

        rpc("initialize", {"protocolVersion": "2024-11-05",
                           "capabilities": {}, "clientInfo": {"name": "v", "version": "0"}}, 1)
        tools = rpc("tools/list", {}, 2)
        names = {t["name"] for t in tools["result"]["tools"]}
        want = {"mcp_files_list", "mcp_files_stat", "mcp_files_search", "mcp_files_tree"}
        check("stdio.tools_list", want <= names, sorted(want & names))
        resp = rpc("tools/call", {"name": "mcp_files_list",
                                  "arguments": {"host": "nobody", "path": "/tmp"}}, 3)
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        check("stdio.error_envelope", data.get("ok") is False and "unknown host" in data.get("error", ""),
              data.get("error"))
        proc.terminate()
    except Exception as exc:
        check("stdio.exception", False, repr(exc))

    # cleanup chmod so tempdir can be removed later
    try:
        os.chmod(fix / "noaccess", 0o755)
    except OSError:
        pass

    n_ok = sum(1 for c in CHECKS if c["ok"])
    print(json.dumps({"ok": n_ok == len(CHECKS), "passed": n_ok,
                      "total": len(CHECKS), "checks": CHECKS}, indent=1))
    return 0 if n_ok == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
