#!/usr/bin/env python3
"""render-memory.py — render Chaba memory context from ssot.chaba.memory.yml.

String-level only: YAML dotted-key lookups with `*` wildcards, markdown
heading extraction, glob/rolling-log reads, and ${ssot("file","key")}
interpolation. No MDDB, no AI, no network.

Outputs (per profile, under render.dir):
  <profile.output>   injected context file (bounded by budgets)
  <profile.report>   pull-only detail file for `more` catalog entries
  memory-report.json sizes/truncations/drops per section (always written)

Usage:
  render-memory.py [--config PATH] [--check] [--if-stale] [--verbose]
"""
import argparse
import glob
import json
import os
import re
import sys
import time

import yaml

DEFAULT_CONFIG = "docs/ssot/chaba/ssot.chaba.memory.yml"
SSOT_RE = re.compile(r'\$\{ssot\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)\}')


# ---------- primitives ----------

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def navigate(data, key):
    """Dotted path over dicts/lists; `*` expands containers. Returns list of matches."""
    if not key:
        return [data]
    cur = [data]
    for part in str(key).split("."):
        nxt = []
        for node in cur:
            if part == "*":
                if isinstance(node, dict):
                    nxt.extend(node.values())
                elif isinstance(node, list):
                    nxt.extend(node)
            elif isinstance(node, dict) and part in node:
                nxt.append(node[part])
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                nxt.append(node[int(part)])
        cur = nxt
        if not cur:
            break
    return cur


def resolve_ssot_refs(text, repo_root, cache, errors):
    """Expand ${ssot("file","key.path")} inside rendered strings."""

    def _sub(m):
        path, k = m.group(1), m.group(2)
        try:
            if path not in cache:
                cache[path] = load_yaml(os.path.join(repo_root, path))
            vals = navigate(cache[path], k)
            if not vals:
                raise KeyError(k)
            return str(vals[0])
        except Exception as e:
            errors.append(f"ssot ref {path}:{k}: {e}")
            return m.group(0)

    return SSOT_RE.sub(_sub, text)


def extract_md_section(path, heading):
    """Lines under '## <heading>' until next heading of same-or-higher level."""
    try:
        lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
    except OSError as e:
        return None, str(e)
    want = heading.strip().lstrip("#").strip()
    out, active, level = [], False, 0
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            lvl, title = len(m.group(1)), m.group(2).strip()
            if active and lvl <= level:
                break
            if not active and title == want:
                active, level = True, lvl
                continue
        if active:
            out.append(line)
    if not active:
        return None, f"heading '{want}' not found in {path}"
    return "\n".join(out).strip("\n"), None


def fmt_item(item, fmt):
    if fmt and isinstance(item, dict):
        try:
            return fmt.format(**{k: ("" if v is None else v) for k, v in item.items()})
        except (KeyError, IndexError):
            pass
    if isinstance(item, str):
        return item if item.startswith("-") else f"- {item}"
    if isinstance(item, dict):
        for k in ("label", "title", "name", "key", "text"):
            if k in item:
                extra = f" [{item['status']}]" if "status" in item else ""
                return f"- {item[k]}{extra}"
        return "- " + ", ".join(f"{k}: {v}" for k, v in list(item.items())[:4])
    return f"- {item}"


def flatten_lines(value, fmt=None, max_items=None):
    """Convert a query result (any YAML value) into display lines."""
    lines = []
    if isinstance(value, list):
        for it in value:
            if isinstance(it, (dict, list)):
                lines.append(fmt_item(it, fmt))
            else:
                lines.append(str(it) if str(it).startswith("-") else f"- {it}")
    elif isinstance(value, dict):
        if fmt and value and all(isinstance(v, dict) for v in value.values()):
            # map-of-dicts: apply fmt per entry, parent key available as {_key}
            for k, v in value.items():
                fields = {kk: ("" if vv is None else vv) for kk, vv in v.items()}
                fields["_key"] = k
                try:
                    lines.append(fmt.format(**fields))
                except (KeyError, IndexError):
                    lines.append(f"- {k}: {fmt_item(v, None).lstrip('- ')}")
        elif fmt:
            lines.append(fmt_item(value, fmt))
        else:
            for k, v in value.items():
                if isinstance(v, dict):
                    first = fmt_item(v, None).lstrip("- ")
                    lines.append(f"- {first}" if first != k else f"- {k}: {first}")
                elif isinstance(v, list):
                    lines.append(f"- {k}: {len(v)} items")
                else:
                    lines.append(f"- {k}: {v}")
    else:
        lines.append(str(value))
    if max_items and len(lines) > max_items:
        lines = lines[:max_items] + [f"…({len(lines) - max_items} more)"]
    return lines


# ---------- render ----------

def run_query(q, repo_root, errors, warnings):
    file = q.get("file", "")
    path = os.path.join(repo_root, file)
    if "section" in q:
        text, err = extract_md_section(path, q["section"])
        if err:
            errors.append(f"{file}: {err}")
            return []
        return text.splitlines()
    try:
        data = load_yaml(path)
    except Exception as e:
        errors.append(f"{file}: {e}")
        return []
    vals = navigate(data, q.get("key", ""))
    if not vals:
        warnings.append(f"{file}: key '{q.get('key')}' produced no matches")
        return []
    lines = []
    for v in vals:
        lines.extend(flatten_lines(v, q.get("format"), q.get("max_items")))
    return lines


def run_source(src, render_dir, repo_root, errors):
    kind = src.get("kind")
    if kind == "inline":
        return [l for l in src.get("text", "").splitlines() if l.strip()]
    if kind == "rolling-log":
        path = os.path.expanduser(src.get("file", ""))
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError as e:
            errors.append(f"rolling-log {src.get('file')}: {e}")
            return []
        min_chars = src.get("min_chars", 0)
        entries = []
        for e in re.split(r"\n(?=## )", text):
            e = e.strip()
            if not e or len(e) < min_chars:
                continue
            entries.append(e)
        keep = src.get("max_entries", 3)
        # demote every heading in each entry so they nest under '## <section>'
        return [re.sub(r"^(#+)", r"#\1", e, flags=re.M) for e in entries[-keep:]]
    if kind == "dir":
        bases = src.get("file", "")
        if isinstance(bases, str):
            bases = [bases]
        paths = []
        for base in bases:
            paths.extend(glob.glob(os.path.join(render_dir, os.path.expanduser(base))))
        pick, fmt = src.get("pick"), src.get("format")
        lines = []
        for p in sorted(paths):
            try:
                doc = load_yaml(p) or {}
            except Exception as e:
                errors.append(f"{p}: {e}")
                continue
            items = doc.get(pick, []) if pick else [doc]
            name = doc.get("name", os.path.splitext(os.path.basename(p))[0])
            for it in items:
                if isinstance(it, dict):
                    it = {**it, "name": name}
                    lines.append(fmt_item(it, fmt))
                else:
                    lines.append(f"- ({name}) {it}")
        return lines
    if kind == "immediate":
        path = os.path.expanduser(src.get("file", ""))
        try:
            doc = load_yaml(path) or {}
        except Exception as e:
            errors.append(f"immediate {src.get('file')}: {e}")
            return []
        import datetime
        now = datetime.datetime.now().astimezone()
        default_ttl = src.get("ttl_hours", 72)
        lines = []
        n_entries = 0
        for e in doc.get("entries", []) or []:
            if not isinstance(e, dict) or not e.get("session"):
                continue
            try:
                ts = datetime.datetime.fromisoformat(str(e.get("ts", "")))
                ttl = e.get("ttl_hours", default_ttl)
                if ts.tzinfo and (now - ts).total_seconds() > ttl * 3600:
                    continue  # expired — "immediate" means immediate
            except ValueError:
                continue  # unparseable ts — drop
            lines.append(f"- {e['session']} ({str(e.get('ts',''))[:16]}): {e.get('task','(no task)')}")
            detail = ", ".join(
                p for p in (
                    f"branch {e['branch']}" if e.get("branch") else "",
                    str(e.get("last_commit") or ""),
                ) if p
            )
            if detail:
                lines.append(f"  {detail}")
            for o in e.get("open") or []:
                lines.append(f"  open: {o}")
            if e.get("next"):
                lines.append(f"  next: {e['next']}")
            if e.get("pointer"):
                lines.append(f"  → {e['pointer']}")
            n_entries += 1
            if n_entries >= src.get("max_entries", 3):
                break
        return lines
    errors.append(f"unknown source kind: {kind}")
    return []


def apply_budget(lines, soft, hard):
    """Returns (kept_lines, truncated_count)."""
    if not soft and not hard:
        return lines, 0
    cap = soft or hard
    out, total = [], 0
    for ln in lines:
        if total + len(ln) + 1 > cap and out:
            return out + [f"…(truncated — {len(lines) - len(out)} more lines in source)"], len(lines) - len(out)
        out.append(ln)
        total += len(ln) + 1
    joined = "\n".join(out)
    if hard and len(joined) > hard:
        joined = joined[: hard - 60] + "\n…(hard-truncated)"
        return joined.splitlines(), len(lines) - len(out) + 1
    return joined.splitlines(), 0


def render_profile(cfg, profile_name, profile, repo_root, render_dir, report):
    sections_cfg = cfg.get("sections", {})
    report_data = {}
    blocks, sizes = [], {}
    for sname in profile.get("sections", []):
        s = sections_cfg.get(sname)
        if not s:
            report["errors"].append(f"{profile_name}: unknown section '{sname}'")
            continue
        key = "guest_include" if (profile_name == "guest" and "guest_include" in s) else "include"
        lines = []
        for q in s.get(key, []):
            lines.extend(run_query(q, repo_root, report["errors"], report["warnings"]))
        sources = s.get("source")
        if isinstance(sources, dict):
            sources = [sources]
        for src in sources or []:
            lines.extend(run_source(src, render_dir, repo_root, report["errors"]))
        lines = [resolve_ssot_refs(l, repo_root, _cache, report["errors"]) for l in lines]
        lim = s.get("limits", {})
        kept, truncated = apply_budget(lines, lim.get("soft"), lim.get("hard"))
        sizes[sname] = {"chars": sum(len(l) + 1 for l in kept), "truncated": truncated}
        if not kept and s.get("required"):
            report["errors"].append(f"{profile_name}: required section '{sname}' produced no content")
        desc = (s.get("description") or "").strip().splitlines()
        head = f"## {sname}\n" + (f"_{desc[0]}_\n\n" if desc else "\n")
        body = "\n".join(kept) if kept else "_(empty)_"
        more = [m for m in s.get("more", []) if profile_name != "guest" or m.get("guest")]
        if more:
            body += "\n\nDeeper (pull on demand):"
            for m in more:
                rkey = m["key"]
                body += f"\n- {m['label']} → report key `{rkey}`"
                src = m.get("source", {})
                if "section" in src:
                    text, err = extract_md_section(os.path.join(repo_root, src["file"]), src["section"])
                    if err:
                        report["warnings"].append(f"more {rkey}: {err}")
                        continue
                    vals = text
                else:
                    try:
                        vals = load_yaml(os.path.join(repo_root, src["file"]))
                        vals = navigate(vals, src.get("key", ""))
                        vals = vals[0] if len(vals) == 1 else vals
                    except Exception as e:
                        report["warnings"].append(f"more {rkey}: {e}")
                        continue
                report_data[rkey] = {"label": m["label"], "data": vals}
        blocks.append(head + body)
    return blocks, sizes, report_data


def enforce_global(blocks, sizes, sections_cfg, profile, report):
    order = profile.get("overflow_order", [])
    soft, hard = profile.get("limits", {}).get("soft"), profile.get("limits", {}).get("hard")
    dropped = []
    def total():
        return sum(len(b) + 2 for b in blocks)
    if soft:
        for sname in order:
            if total() <= soft:
                break
            for i, b in enumerate(blocks):
                if b.startswith(f"## {sname}\n") and not sections_cfg.get(sname, {}).get("required"):
                    dropped.append(sname)
                    del blocks[i]
                    break
    if dropped:
        report["warnings"].append(f"global soft overflow — dropped: {', '.join(dropped)}")
    text = "\n\n".join(blocks)
    over_hard = bool(hard and len(text) > hard)
    if over_hard:
        text = text[: hard - 80] + "\n\n…(global hard limit reached — truncated)\n"
    return text, dropped, over_hard


_cache = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--check", action="store_true", help="validate only; do not write context files")
    ap.add_argument("--if-stale", action="store_true", help="skip render when outputs are newer than inputs")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cfg = load_yaml(os.path.join(repo_root, args.config))
    render_dir = os.path.expanduser(cfg["render"]["dir"])
    report = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "errors": [], "warnings": [],
              "profiles": {}, "sections": {}, "dropped": [], "over_hard": []}

    # staleness: newest input vs oldest output
    inputs = [os.path.join(repo_root, args.config)]
    for s in cfg.get("sections", {}).values():
        for q in s.get("include", []) + s.get("guest_include", []):
            inputs.append(os.path.join(repo_root, q["file"]))
        srcs = s.get("source")
        if isinstance(srcs, dict):
            srcs = [srcs]
        for src in srcs or []:
            if src.get("file") and src.get("kind") != "dir":
                inputs.append(os.path.join(repo_root, os.path.expanduser(src["file"])))
        for m in s.get("more", []):
            if m.get("source", {}).get("file"):
                inputs.append(os.path.join(repo_root, m["source"]["file"]))
    inputs = [p for p in inputs if os.path.exists(os.path.expanduser(p))]
    newest_in = max(os.path.getmtime(os.path.expanduser(p)) for p in inputs) if inputs else 0

    os.makedirs(render_dir, exist_ok=True)
    profiles = cfg["render"]["profiles"]

    if args.if_stale:
        outs = [os.path.join(render_dir, p["output"]) for p in profiles.values()]
        outs += [os.path.join(render_dir, p["report"]) for p in profiles.values() if p.get("report")]
        if outs and all(os.path.exists(o) for o in outs):
            oldest_out = min(os.path.getmtime(o) for o in outs)
            if oldest_out >= newest_in:
                if args.verbose:
                    print("fresh — skipping render")
                return 0

    for pname, profile in profiles.items():
        blocks, sizes, rdata = render_profile(cfg, pname, profile, repo_root, render_dir, report)
        text, dropped, over_hard = enforce_global(blocks, sizes, cfg["sections"], profile, report)
        report["profiles"][pname] = {"chars": len(text)}
        report["sections"].update({f"{pname}.{k}": v for k, v in sizes.items()})
        report["dropped"].extend(dropped)
        if over_hard:
            report["over_hard"].append(pname)
        header = (f"# Chaba context — {pname}\n"
                  f"_Rendered {report['generated']} from {args.config}. "
                  f"Do not edit — regenerate with render-memory.py._\n")
        if not args.check:
            with open(os.path.join(render_dir, profile["output"]), "w", encoding="utf-8") as f:
                f.write(header + "\n" + text + "\n")
            if profile.get("report"):
                with open(os.path.join(render_dir, profile["report"]), "w", encoding="utf-8") as f:
                    yaml.safe_dump({"generated": report["generated"], "profile": pname, **rdata},
                                   f, allow_unicode=True, sort_keys=False)

    report_path = os.path.join(render_dir, cfg["render"].get("report_file", "memory-report.json"))
    if not args.check:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    for w in report["warnings"]:
        print(f"warn: {w}", file=sys.stderr)
    for e in report["errors"]:
        print(f"error: {e}", file=sys.stderr)
    if args.verbose or args.check:
        print(json.dumps(report["profiles"], indent=None))
        print(json.dumps(report["sections"], indent=2))
    if report["errors"] or report["over_hard"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
