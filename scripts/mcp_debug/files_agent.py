#!/usr/bin/env python3
"""mcp_debug remote filesystem agent.

Self-contained (stdlib only). mcp_debug.files ships this file to the target
host as a base64 payload and executes it as:

    printf %s <agent_b64> | base64 -d | "$(command -v python3 || command -v python)" - <op> <params_b64>

Ops: list, stat, search, tree.

Params (JSON, base64-encoded argv[2]):
    path            absolute path, must resolve under allowed_roots
    allowed_roots   list of absolute prefixes the server vetted for this host
    pattern         fnmatch glob on entry name ('/' in pattern -> match
                    relative_path instead). search requires it; list/tree may
                    use it as a filter.
    depth           levels below root (list=1 fixed; tree/search honour it)
    max_entries     cap on returned entries
    sort            name | size | mtime | kind   (default name)
    order           asc | desc                   (default asc)
    kind            any | file | dir | symlink   (filter, default any)
    max_output_bytes  cap on the serialized response
    max_errors      cap on collected errors

Emits exactly one JSON line on stdout. Every failure is reported in-band via
{"ok": false, "error": ...} or per-entry records in "errors"; nothing useful
is ever written to stderr.

Stable output schema (also see ssot.mcp-debug.files.yml -> files):
    ok, tool, root, resolved_root, entries[], truncated, truncated_reason,
    errors[], errors_truncated, observed_at, counts{files,dirs,symlinks,other},
    scanned, depth, pattern, sort, order
Entry: name, relative_path, kind, size_bytes, mtime, mode
       (+ depth on search/tree entries, link_target + link_escape on symlinks)
"""
import base64
import fnmatch
import json
import os
import stat as statmod
import sys
from datetime import datetime, timezone

OPS = ("list", "stat", "search", "tree")
SORTS = ("name", "size", "mtime", "kind")
KINDS = ("any", "file", "dir", "symlink", "other")
KIND_ORDER = {"dir": 0, "file": 1, "symlink": 2, "other": 3}

HARD = {
    "max_entries": 5000,
    "max_depth": 12,
    "max_output_bytes": 524288,
    "max_errors": 200,
    "max_scan": 200000,
    "path_length": 1024,
}


def _emit(obj):
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")


def _fail(tool, error, **extra):
    out = {"ok": False, "tool": tool, "error": error,
           "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out.update(extra)
    _emit(out)
    return 0


def _kind_of(mode):
    if statmod.S_ISDIR(mode):
        return "dir"
    if statmod.S_ISREG(mode):
        return "file"
    if statmod.S_ISLNK(mode):
        return "symlink"
    return "other"


def _under(path, roots):
    for r in roots:
        if path == r or path.startswith(r + os.sep):
            return True
    return False


def _clamp_int(params, key, default, hard):
    try:
        n = int(params.get(key, default))
    except (TypeError, ValueError):
        n = default
    if n < 0:
        n = 0
    return min(n, hard)


def _match(rel, name, pattern):
    if not pattern:
        return True
    if "/" in pattern:
        # path patterns anchor at the root or any deeper level
        return fnmatch.fnmatch(rel, pattern) or \
            fnmatch.fnmatch(rel, "*/" + pattern)
    return fnmatch.fnmatch(name, pattern)


def _sort_key(sort):
    if sort == "size":
        return lambda e: ((e["size_bytes"] or 0), e["name"].lower())
    if sort == "mtime":
        return lambda e: ((e["mtime"] or 0), e["name"].lower())
    if sort == "kind":
        return lambda e: (KIND_ORDER.get(e["kind"], 9), e["name"].lower())
    return lambda e: e["name"].lower()


def _entry(abs_path, name, rel, depth, roots, errors):
    """Build one entry; stat failures yield null fields plus an errors record."""
    e = {"name": name, "relative_path": rel, "kind": "other",
         "size_bytes": None, "mtime": None, "mode": None}
    if depth is not None:
        e["depth"] = depth
    try:
        st = os.lstat(abs_path)
        e["kind"] = _kind_of(st.st_mode)
        e["size_bytes"] = st.st_size
        e["mtime"] = int(st.st_mtime)
        e["mode"] = oct(st.st_mode & 0o7777)[2:].zfill(4)
    except OSError as exc:
        errors.append({"path": rel, "error": f"stat: {exc.strerror or exc}"})
        return e, False
    if e["kind"] == "symlink":
        try:
            target = os.readlink(abs_path)
            e["link_target"] = target
            if not _under(os.path.realpath(abs_path), roots):
                e["link_escape"] = True
                errors.append({"path": rel, "error": "symlink target escapes allowed roots"})
        except OSError as exc:
            errors.append({"path": rel, "error": f"readlink: {exc.strerror or exc}"})
    return e, True


def _scan_dir(abs_dir, rel_dir, depth, roots, errors):
    """Return sorted children entries of one directory (or [] + error record)."""
    try:
        it = os.scandir(abs_dir)
    except OSError as exc:
        errors.append({"path": rel_dir or ".",
                       "error": f"scandir: {exc.strerror or exc}"})
        return []
    with it:
        children = []
        for dent in it:
            rel = dent.name if not rel_dir else rel_dir + "/" + dent.name
            e, _ = _entry(dent.path, dent.name, rel, depth, roots, errors)
            children.append(e)
    return children


def _walk(tool, root, params, roots, errors, max_depth):
    """DFS walk returning (entries, scanned, truncated_reason)."""
    max_entries = _clamp_int(params, "max_entries", 500, HARD["max_entries"])
    pattern = params.get("pattern")
    kind_f = params.get("kind", "any")
    sort = params.get("sort", "name")
    order = params.get("order", "asc")
    key = _sort_key(sort)
    entries, scanned = [], 0
    truncated_reason = None

    if tool == "list":
        children = _scan_dir(root, "", 1, roots, errors)
        scanned += len(children)
        for e in children:
            if kind_f != "any" and e["kind"] != kind_f:
                continue
            if not _match(e["relative_path"], e["name"], pattern):
                continue
            entries.append(e)
        entries.sort(key=key, reverse=(order == "desc"))
        if len(entries) > max_entries:
            entries = entries[:max_entries]
            truncated_reason = "max_entries"
        return entries, scanned, truncated_reason

    # search/tree: iterative DFS, pre-order, sorted siblings
    stack = [(root, "", 0)]
    while stack:
        abs_dir, rel_dir, depth = stack.pop()
        children = _scan_dir(abs_dir, rel_dir, depth + 1, roots, errors)
        scanned += len(children)
        if scanned > HARD["max_scan"]:
            truncated_reason = truncated_reason or "max_scan"
            break
        children.sort(key=key, reverse=(order == "desc"))
        descend = []
        for e in children:
            matched = (kind_f == "any" or e["kind"] == kind_f) and \
                _match(e["relative_path"], e["name"], pattern)
            if matched:
                entries.append(e)
                if len(entries) >= max_entries:
                    truncated_reason = truncated_reason or "max_entries"
                    break
            if e["kind"] == "dir" and depth + 1 < max_depth:
                descend.append((os.path.join(abs_dir, e["name"]), e["relative_path"], depth + 1))
        if truncated_reason:
            break
        for item in reversed(descend):
            stack.append(item)
    return entries, scanned, truncated_reason


def _stat(tool, root, params, roots, errors):
    real = os.path.realpath(root)
    name = os.path.basename(root.rstrip(os.sep)) or root
    e, _ = _entry(root, name, ".", None, roots, errors)
    return [e], 1, None


def main(argv):
    if len(argv) < 3:
        return _fail("unknown", "usage: files_agent.py <op> <params_b64>")
    tool, params_b64 = argv[1], argv[2]
    if tool not in OPS:
        return _fail(tool, f"unknown op: {tool}", allowed=list(OPS))
    try:
        params = json.loads(base64.b64decode(params_b64).decode("utf-8"))
    except Exception as exc:
        return _fail(tool, f"bad params: {exc}")
    if not isinstance(params, dict):
        return _fail(tool, "params must be a JSON object")

    path = params.get("path")
    roots = params.get("allowed_roots") or []
    if not path or not isinstance(path, str):
        return _fail(tool, "path is required")
    if "\x00" in path:
        return _fail(tool, "path contains NUL")
    if len(path) > HARD["path_length"]:
        return _fail(tool, "path exceeds max_path_length")
    if ".." in path.split(os.sep):
        return _fail(tool, "path contains '..'")
    if not path.startswith(os.sep):
        return _fail(tool, "path must be absolute")
    roots = [os.path.realpath(r) for r in roots if isinstance(r, str)]
    if not roots:
        return _fail(tool, "no allowed_roots supplied")

    real_root = os.path.realpath(path)
    if not _under(real_root, roots):
        return _fail(tool, "resolved path escapes allowed roots",
                     root=path, resolved_root=real_root)
    if not os.path.lexists(path):
        return _fail(tool, "path not found", root=path)
    if tool == "stat":
        pass
    elif not os.path.isdir(real_root):
        return _fail(tool, "path is not a directory", root=path)

    errors = []
    max_errors = _clamp_int(params, "max_errors", 50, HARD["max_errors"])
    max_out = _clamp_int(params, "max_output_bytes", 196608,
                         HARD["max_output_bytes"])

    eff_depth = 1 if tool == "list" else _clamp_int(
        params, "depth", 3 if tool == "tree" else 6, HARD["max_depth"])

    if tool == "stat":
        entries, scanned, trunc_reason = _stat(tool, real_root, params, roots, errors)
    else:
        entries, scanned, trunc_reason = _walk(tool, real_root, params, roots,
                                               errors, eff_depth)

    errors_truncated = False
    if len(errors) > max_errors:
        errors = errors[:max_errors]
        errors_truncated = True

    counts = {"files": 0, "dirs": 0, "symlinks": 0, "other": 0}
    for e in entries:
        counts[{"file": "files", "dir": "dirs",
                "symlink": "symlinks"}.get(e["kind"], "other")] += 1

    fmt = params.get("format", "objects")
    if fmt == "rows":
        # positional rows over the same schema; fields list declares order
        fields = ["name", "relative_path", "kind", "size_bytes", "mtime", "mode"]
        if any("depth" in e for e in entries):
            fields.append("depth")
        if any("link_target" in e for e in entries):
            fields.extend(["link_target", "link_escape"])
        rows = [[e.get(k) for k in fields] for e in entries]
    else:
        fields = None
        rows = None

    result = {
        "ok": True,
        "tool": tool,
        "root": path,
        "resolved_root": real_root,
        "entries": entries,
        "truncated": False,
        "truncated_reason": trunc_reason,
        "errors": errors,
        "errors_truncated": errors_truncated,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": counts,
        "scanned": scanned,
        "depth": eff_depth if tool != "stat" else None,
        "pattern": params.get("pattern"),
        "sort": params.get("sort", "name"),
        "order": params.get("order", "asc"),
    }
    if fields is not None:
        result["fields"] = fields
        result["entries"] = rows
        result["format"] = "rows"

    out = json.dumps(result, separators=(",", ":"))
    while result["entries"] and len(out) > max_out:
        result["entries"].pop()
        result["truncated"] = True
        result["truncated_reason"] = "max_output_bytes"
        out = json.dumps(result, separators=(",", ":"))
    if trunc_reason:
        result["truncated"] = True
        out = json.dumps(result, separators=(",", ":"))
    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
