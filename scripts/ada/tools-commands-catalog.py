#!/usr/bin/env python3
"""tools-commands-catalog — generated Ada tools command reference.

Card ada-tools-command-reference (REPO work, two parts). This is part 1:
parse the Ada tool declarations and emit a reviewable catalog — one row
per tool: name, purpose, trigger phrases, backend, token/cost note,
last-changed. Generated, never handwritten.

Outputs (relative to this chaba checkout):
  docs/kb/ada-tools-commands.md   — human-reviewable tables, do-not-edit
  docs/kb/ada-tools-commands.json — machine snapshot; the "Ada verb"
                                  read path (part 2) consumes THIS file,
                                  never recomputes. Contract:
                                  docs/kb/ada-tools-verb-contract.md

Sources (all parsed, nothing executed — ada-voice checkout via
ADA_VOICE_REPO / ADA_PI_REPO env, default <repo-parent>/ada-voice):
  backend/realtime_provider.py        builtin + CHABA (guest) decls (AST)
  backend/tools.d/*.py + manifest.yml drop-in decls, policy, timeout
  backend/tool_guide.yml              error-path guide presence
  backend/tool_runner/common.py       _ALIASES absorbed-name table (AST)
  docs/ssot/ssot.tool-surface.yml     merge families, schema tier, debt
  tests/scenarios-live/*.yml          real trigger utterances per tool
  docs/ssot/infrastructure/ssot.tools.yml (chaba) canonical backend map

`--check` regenerates and diffs against the committed outputs (ignoring
the volatile Generated line) — the regen gate to run when a declaration
changes (tool-lint / CI / deploy gate tie-in).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # chaba checkout
ADA_VOICE = Path(
    os.environ.get("ADA_VOICE_REPO")
    or os.environ.get("ADA_PI_REPO")
    or REPO.parent / "ada-voice"
)
PROVIDER = ADA_VOICE / "backend" / "realtime_provider.py"
TOOLS_D = ADA_VOICE / "backend" / "tools.d"
MANIFEST = TOOLS_D / "manifest.yml"
TOOL_GUIDE = ADA_VOICE / "backend" / "tool_guide.yml"
ALIAS_FILE = ADA_VOICE / "backend" / "tool_runner" / "common.py"
SURFACE_YML = ADA_VOICE / "docs" / "ssot" / "ssot.tool-surface.yml"
SCEN_DIR = ADA_VOICE / "tests" / "scenarios-live"
REGISTRY = REPO / "docs" / "ssot" / "infrastructure" / "ssot.tools.yml"

OUT_MD = REPO / "docs" / "kb" / "ada-tools-commands.md"
OUT_JSON = REPO / "docs" / "kb" / "ada-tools-commands.json"

GEN_LINE_RE = re.compile(r"^Generated:.*$", re.M)
GEN_JSON_RE = re.compile(r'"generated_at":\s*"[^"]*"')


# ---------------------------------------------------------------- AST

def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _name_desc(node):
    """Dict node -> (name, description, name_value_lineno) or None."""
    if not isinstance(node, ast.Dict):
        return None
    name = desc = None
    name_lineno = node.lineno
    for k, v in zip(node.keys, node.values):
        key = _literal(k)
        if key == "name" and isinstance(_literal(v), str):
            name, name_lineno = _literal(v), v.lineno
        elif key == "description" and isinstance(_literal(v), str):
            desc = _literal(v)
    if isinstance(name, str) and isinstance(desc, str):
        return name, desc.strip(), name_lineno
    return None


def _assign_spans(tree, wanted):
    """lineno spans of top-level assignments to any name in `wanted`."""
    spans = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in wanted for t in node.targets
        ):
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


def _in_spans(lineno, spans):
    return any(lo <= lineno <= hi for lo, hi in spans)


def parse_provider():
    """Builtin + guest (CHABA_DECLARATIONS) tool decls.

    Returns {name: {"desc": str, "span": (lo, hi), "layer": "builtin"|
    "guest"}}. A name may hold BOTH layers (CHABA_DECLARATIONS re-declares
    canonical names guest-scoped) — key by (name, layer) internally.
    """
    tree = ast.parse(PROVIDER.read_text())
    guest_spans = _assign_spans(tree, {"CHABA_DECLARATIONS"})
    rows = {}
    for node in ast.walk(tree):
        hit = _name_desc(node)
        if not hit:
            continue
        name, desc, name_lineno = hit
        layer = "guest" if _in_spans(node.lineno, guest_spans) else "builtin"
        key = (name, layer)
        # first dict literal wins on dupes (same name re-declared later is
        # not a second tool — the surface ships one seat per name+layer)
        rows.setdefault(
            key,
            {
                "name": name,
                "desc": desc,
                "span": (node.lineno, node.end_lineno or node.lineno),
                "name_lineno": name_lineno,
                "layer": layer,
                "source": PROVIDER,
            },
        )
    return rows


def parse_tools_d():
    """Drop-in decls: every dict literal with name+description in
    tools.d/*.py, keyed (name, 'dropin'), plus manifest policy."""
    rows = {}
    for path in sorted(TOOLS_D.glob("*.py")):
        if path.name.startswith("__"):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            hit = _name_desc(node)
            if not hit:
                continue
            name, desc, name_lineno = hit
            rows.setdefault(
                (name, "dropin"),
                {
                    "name": name,
                    "desc": desc,
                    "span": (node.lineno, node.end_lineno or node.lineno),
                    "name_lineno": name_lineno,
                    "layer": "dropin",
                    "source": path,
                    "module": path.stem,
                },
            )
    return rows


def _yaml(path, default):
    try:
        import yaml

        return yaml.safe_load(path.read_text()) or default
    except Exception:
        return default


def parse_manifest():
    data = _yaml(MANIFEST, {})
    return data.get("tools") or {}


def parse_tool_guide():
    data = _yaml(TOOL_GUIDE, {})
    return {k for k, v in data.items() if isinstance(v, str) and v.strip()}


def parse_aliases():
    """tool_runner/common.py::_ALIASES -> {absorbed: canonical}."""
    try:
        tree = ast.parse(ALIAS_FILE.read_text())
    except Exception:
        return {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "_ALIASES" for t in targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except Exception:
            return {}
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
    return {}


def parse_surface():
    data = _yaml(SURFACE_YML, {})
    lazy = data.get("lazy_schemas") or {}
    return {
        "families": data.get("families") or {},
        "full_schema": set(lazy.get("full_schema_tools") or []),
        "coverage_debt": list(data.get("coverage_debt") or []),
        "count_cap": data.get("count_cap"),
        "target_count": data.get("target_count"),
    }


def parse_scenario_triggers():
    """scenario turns: uttered `user` line -> names in expect.calls.

    Returns {tool_name: [utterance, ...]} deduped, first-seen order."""
    trig = {}
    if not SCEN_DIR.is_dir():
        return trig
    import yaml

    for path in sorted(list(SCEN_DIR.glob("*.yml")) + list(SCEN_DIR.glob("*.yaml"))):
        try:
            docs = list(yaml.safe_load_all(path.read_text()))
        except Exception:
            continue
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            turns = doc.get("turns") or []
            if not isinstance(turns, list):
                continue
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                user = turn.get("user") or turn.get("say") or ""
                expect = turn.get("expect") or {}
                calls = expect.get("calls") or expect.get("tools") or []
                if isinstance(calls, str):
                    calls = [calls]
                for name in calls:
                    if not isinstance(name, str) or not isinstance(user, str):
                        continue
                    utt = " ".join(user.split())
                    if utt and utt not in trig.setdefault(name, []):
                        trig[name].append(utt)
    return trig


def parse_registry():
    """chaba ssot.tools.yml -> {ada_voice_surface_name: row}."""
    data = _yaml(REGISTRY, {})
    by_surface = {}
    for row in data.get("tools") or []:
        if not isinstance(row, dict):
            continue
        surfaces = row.get("surfaces") or {}
        ada_name = surfaces.get("ada-voice")
        if isinstance(ada_name, str):
            by_surface.setdefault(ada_name, row)
    return by_surface


# ------------------------------------------------------------ last-changed

def blame_dates(path):
    """lineno -> 'YYYY-MM-DD' via one `git blame --porcelain` call;
    uncommitted lines map to 'worktree'."""
    out = {}
    try:
        proc = subprocess.run(
            ["git", "-C", str(ADA_VOICE), "blame", "--porcelain",
             "--", str(path.relative_to(ADA_VOICE))],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except Exception:
        return out
    if proc.returncode != 0:
        return out
    # Porcelain: each block starts `sha orig_lineno final_lineno [count]`;
    # full headers (incl. committer-time) print only on a commit's FIRST
    # block, so epochs must be keyed by sha, not by block position.
    ranges = []          # (final_lineno, count, sha)
    epochs = {}          # sha -> committer epoch
    cur_sha = None
    for line in proc.stdout.splitlines():
        head = line.split(" ")
        if (len(head) >= 3 and re.fullmatch(r"[0-9a-f]{40}", head[0])
                and head[1].isdigit() and head[2].isdigit()):
            cur_sha = head[0]
            ranges.append((int(head[2]),
                           int(head[3]) if len(head) > 3 else 1, cur_sha))
        elif line.startswith("committer-time ") and cur_sha:
            try:
                epochs[cur_sha] = int(line.split()[1])
            except (IndexError, ValueError):
                pass
        elif line.startswith("filename "):
            cur_sha = None
    for final_lineno, count, sha in ranges:
        if set(sha) == {"0"}:
            date = "worktree"
        elif sha in epochs:
            date = datetime.fromtimestamp(
                epochs[sha], tz=timezone.utc).strftime("%Y-%m-%d")
        else:
            date = "?"
        for ln in range(final_lineno, final_lineno + count):
            out[ln] = date
    return out


def last_changed(path, span, blame_cache):
    """Newest blame date across the declaration's line span."""
    if path not in blame_cache:
        blame_cache[path] = blame_dates(path)
    dates = [d for ln in range(span[0], span[1] + 1)
             if (d := blame_cache[path].get(ln))]
    if not dates:
        try:
            return datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        except OSError:
            return "?"
    return "worktree" if "worktree" in dates else max(dates)


def source_rev():
    """HEAD sha/date of the ada-voice checkout + upstream lag."""
    def _git(*args):
        try:
            p = subprocess.run(["git", "-C", str(ADA_VOICE), *args],
                               capture_output=True, text=True, timeout=10)
            return p.stdout.strip() if p.returncode == 0 else ""
        except Exception:
            return ""

    return {
        "repo": "ada-voice",
        "path": str(ADA_VOICE),
        "head": _git("rev-parse", "--short", "HEAD") or "?",
        "head_date": _git("log", "-1", "--format=%cs") or "?",
        "behind": _git("rev-list", "--count", "HEAD..@{upstream}") or "?",
    }


# ------------------------------------------------------------------ join

def _backend_label(raw):
    if not raw:
        return "exec"
    low = str(raw).lower()
    if "board-api" in low or "board_api" in low:
        return "board-api"
    if "mddb" in low:
        return "mddb"
    if "mcp" in low:
        return "mcp"
    if "wp" in low or "wordpress" in low:
        return "wp-boards"
    if "home assistant" in low or "ha-mcp" in low or low.startswith("ha"):
        return "ha"
    if any(k in low for k in ("exec", "in-process", "in-session", "local")):
        return "exec"
    return str(raw).split()[0]


def _module_backend(path):
    """Fallback for drop-ins missing a registry row — source markers."""
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return "exec"
    if "board_client" in text or "board_api" in text:
        return "board-api"
    if "mcp" in text.lower():
        return "mcp"
    return "exec"


def _first_sentence(text, limit=150):
    flat = " ".join(str(text).split())
    for sep in (". ", "; "):
        if sep in flat:
            flat = flat.split(sep, 1)[0] + sep.strip()[0]
            break
    return flat[: limit - 3] + "..." if len(flat) > limit else flat


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", "<br>")


def collect():
    surface = parse_surface()
    manifest = parse_manifest()
    guide = parse_tool_guide()
    aliases = parse_aliases()
    triggers = parse_scenario_triggers()
    registry = parse_registry()
    blame_cache = {}
    rev = source_rev()

    rows = []
    for (name, layer), rec in sorted(
            {**parse_provider(), **parse_tools_d()}.items()):
        man = manifest.get(name) or {}
        reg = registry.get(name) or {}
        if layer == "dropin":
            backend = _backend_label(reg.get("backend")) if reg.get("backend") \
                else _module_backend(rec["source"])
            policy = man.get("policy") or reg.get("policy") or "read"
            timeout = man.get("timeout_s")
            secondary = bool(man.get("secondary_allowed"))
        else:
            backend = _backend_label(reg.get("backend"))
            policy = reg.get("policy") or ""
            timeout = None
            secondary = bool(reg.get("secondary"))
        fam = next(
            (f for f, spec in surface["families"].items()
             if isinstance(spec, dict) and spec.get("canonical") == name), "")
        rows.append({
            "name": name,
            "layer": layer,
            "purpose": _first_sentence(rec["desc"]),
            "description": " ".join(rec["desc"].split()),
            "backend": backend,
            "registry": reg.get("name") or "",
            "policy": policy,
            "timeout_s": timeout,
            "secondary": secondary,
            "schema": ("full" if name in surface["full_schema"]
                       else ("lazy" if layer == "builtin" else "")),
            "guide": name in guide,
            "triggers": triggers.get(name, [])[:3],
            "last_changed": last_changed(rec["source"], rec["span"], blame_cache),
            "family": fam,
            "source_file": str(rec["source"].relative_to(ADA_VOICE)),
        })

    # merge-family status: absorbed name off the surface must live in
    # _ALIASES (tool-lint enforces); still-declared = merge pending.
    declared = {(r["name"], r["layer"]) for r in rows}
    declared_names = {r["name"] for r in rows}
    families = {}
    for fname, spec in surface["families"].items():
        if not isinstance(spec, dict):
            continue
        absorbed = list(spec.get("absorbed") or [])
        gone = [a for a in absorbed
              if a not in declared_names and aliases.get(a)]
        families[fname] = {
            "canonical": spec.get("canonical") or "",
            "absorbed": absorbed,
            "merge_card": spec.get("merge_card") or "",
            "scenario": spec.get("scenario") or "",
            "status": ("merged" if len(gone) == len(absorbed) and absorbed
                       else ("partial" if gone else "pending")),
        }

    drift = {
        "unregistered_tools": sorted(
            r["name"] for r in rows
            if r["layer"] != "guest" and not r["registry"]),
        "stale_registry_surfaces": sorted(
            n for n in registry if n not in declared_names),
        "coverage_debt": surface["coverage_debt"],
        "guide_without_tool": sorted(guide - declared_names),
        "alias_targets_undeclared": sorted(
            {c for c in aliases.values()
             if c not in {n for (n, l) in declared if l != "guest"}}),
    }
    counts = {
        "builtin": sum(1 for r in rows if r["layer"] == "builtin"),
        "dropin": sum(1 for r in rows if r["layer"] == "dropin"),
        "guest": sum(1 for r in rows if r["layer"] == "guest"),
        "aliases": len(aliases),
        "families": len(families),
        "count_cap": surface["count_cap"],
        "target_count": surface["target_count"],
    }
    return {"rows": rows, "aliases": aliases, "families": families,
            "drift": drift, "counts": counts, "source": rev}


# ----------------------------------------------------------------- render

def _trig_cell(trigs):
    if not trigs:
        return "—"
    return _cell("<br>".join(
        t[:57] + "…" if len(t) > 60 else t for t in trigs[:2]))


def _cost_cell(r):
    parts = []
    if r["policy"]:
        parts.append(r["policy"])
    if r["timeout_s"]:
        parts.append(f"{r['timeout_s']}s")
    if r["layer"] == "dropin" and r["secondary"]:
        parts.append("2nd-ok")
    if r["schema"]:
        parts.append(f"{r['schema']}-schema")
    if r["guide"]:
        parts.append("+guide")
    return " · ".join(parts) or "—"


def _table(rows):
    out = ["| tool | purpose | triggers (scenario utterances) | backend |"
           " cost/policy | last changed |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        fam = f" ‡{r['family']}" if r["family"] else ""
        out.append(
            f"| `{r['name']}`{fam} | {_cell(r['purpose'])} | "
            f"{_trig_cell(r['triggers'])} | {r['backend']} | "
            f"{_cost_cell(r)} | {r['last_changed']} |")
    return out


def render_md(data, now):
    c = data["counts"]
    src = data["source"]
    stale = ""
    if str(src["behind"]).isdigit() and int(src["behind"]):
        stale = (f" — ⚠ ada-voice checkout is {src['behind']} commit(s) "
                 "behind origin/main; pull and regen for a live surface")
    lines = [
        "# Ada tools command reference",
        "",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M %Z')} by "
        "`scripts/ada/tools-commands-catalog.py` — **do not edit**. "
        "Regenerate after any tool-declaration change "
        "(`backend/realtime_provider.py`, `backend/tools.d/*`, "
        "`manifest.yml`, `tool_guide.yml`, `_ALIASES`, "
        "`ssot.tool-surface.yml`, scenarios):",
        "",
        "```",
        "python3 scripts/ada/tools-commands-catalog.py          # write",
        "python3 scripts/ada/tools-commands-catalog.py --check  # CI gate",
        "```",
        "",
        "<!-- tools-commands:auto -->",
        "",
        f"Source: ada-voice@{src['head']} ({src['head_date']}){stale}. "
        f"Surface: **{c['builtin']}** builtin · **{c['dropin']}** drop-in · "
        f"**{c['guest']}** guest (Chaba) · **{c['aliases']}** absorbed "
        f"aliases across **{c['families']}** merge families "
        f"(cap {c['count_cap']}, consolidation target {c['target_count']}).",
        "",
        "Companion machine snapshot: `docs/kb/ada-tools-commands.json` "
        "(the Ada *what-can-you-do* verb reads that file — contract in "
        "`docs/kb/ada-tools-verb-contract.md`). `‡` marks the canonical "
        "seat of a tools-merge-* family.",
        "",
    ]
    for title, layer, blurb in (
        ("Builtin tools", "builtin",
         "Declared inline in `backend/realtime_provider.py` — ship on the "
         "Gemini Live wire every session (lazy = name+blurb+skeleton only)."),
        ("Drop-in tools", "dropin",
         "`backend/tools.d/` modules gated by `manifest.yml` "
         "(policy/timeout/secondary)."),
        ("Guest (Chaba) surface", "guest",
         "`CHABA_DECLARATIONS` — guest-scoped re-declarations of canonical "
         "names for the visitor surface; params pinned (e.g. "
         "kind='guest')."),
    ):
        rows = [r for r in data["rows"] if r["layer"] == layer]
        lines += [f"## {title} ({len(rows)})", "", blurb, ""]
        lines += _table(rows) if rows else ["*none parsed*"]
        lines += [""]

    lines += ["## Merge families (tools-merge-*)", "",
              "Absorbed names route to the canonical seat through "
              "`tool_runner._ALIASES`; `pending` = absorbed name still "
              "declared on the surface.", "",
              "| family | canonical | absorbed | status | card | scenario |",
              "|---|---|---|---|---|---|"]
    for fname, spec in data["families"].items():
        lines.append(
            f"| {fname} | `{spec['canonical']}` | "
            f"{_cell(', '.join(f'`{a}`' for a in spec['absorbed']))} | "
            f"{spec['status']} | {spec['merge_card']} | "
            f"{spec['scenario']} |")
    lines += ["", "## Absorbed-name surface (`_ALIASES`)", "",
              "Retired decl names still routable — the model's stale call "
              "lands on the canonical tool.", "",
              "| alias | routes to |", "|---|---|"]
    for a, tgt in sorted(data["aliases"].items()):
        lines.append(f"| `{a}` | `{tgt}` |")

    d = data["drift"]
    lines += ["", "## Drift notes", ""]
    lines.append(f"- tools declared but missing an `ssot.tools.yml` "
                 f"registry row ({len(d['unregistered_tools'])}): "
                 + (", ".join(f"`{n}`" for n in d["unregistered_tools"][:40])
                    or "none"))
    lines.append(f"- registry `ada-voice` surfaces not on the live "
                 f"surface ({len(d['stale_registry_surfaces'])}): "
                 + (", ".join(f"`{n}`" for n in d["stale_registry_surfaces"][:40])
                    or "none"))
    lines.append(f"- `coverage_debt` — declared tools with no scenario "
                 f"reference ({len(d['coverage_debt'])}): "
                 + (", ".join(f"`{n}`" for n in d["coverage_debt"][:40])
                    or "none"))
    if d["alias_targets_undeclared"]:
        lines.append(f"- **broken aliases** — `_ALIASES` targets not "
                     f"declared: "
                     + ", ".join(f"`{n}`" for n in d["alias_targets_undeclared"]))
    if d["guide_without_tool"]:
        lines.append(f"- `tool_guide.yml` entries for undeclared tools: "
                     + ", ".join(f"`{n}`" for n in d["guide_without_tool"]))
    lines += [
        "",
        "<!-- /tools-commands:auto -->",
        "",
        "*Sources: ada-voice `backend/realtime_provider.py`, "
        "`backend/tools.d/*` + `manifest.yml`, `backend/tool_guide.yml`, "
        "`tool_runner/common.py::_ALIASES`, "
        "`docs/ssot/ssot.tool-surface.yml`, `tests/scenarios-live/*` — "
        "joined with chaba `docs/ssot/infrastructure/ssot.tools.yml`. "
        "Last-changed = `git blame` span of each declaration.*",
    ]
    return "\n".join(lines) + "\n"


def render_json(data, now):
    return json.dumps({
        "schema": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "source": data["source"],
        "counts": data["counts"],
        "tools": data["rows"],
        "aliases": data["aliases"],
        "families": data["families"],
        "drift": data["drift"],
    }, indent=1, sort_keys=False) + "\n"


def _stable(text):
    return GEN_JSON_RE.sub(
        '"generated_at": "<normalized>"',
        GEN_LINE_RE.sub("Generated: <normalized>", text))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    check = "--check" in argv
    if not PROVIDER.is_file():
        sys.exit(f"no ada-voice checkout at {ADA_VOICE} — "
                 "set ADA_VOICE_REPO")
    now = datetime.now(timezone.utc)
    data = collect()
    md = render_md(data, now)
    js = render_json(data, now)
    if check:
        ok = True
        for path, new in ((OUT_MD, md), (OUT_JSON, js)):
            if not path.is_file():
                print(f"MISSING {path} — run tools-commands-catalog.py")
                ok = False
            elif _stable(path.read_text()) != _stable(new):
                print(f"STALE {path} — regenerate")
                ok = False
        if ok:
            print("ada-tools-commands outputs up to date")
        return 0 if ok else 1
    OUT_MD.write_text(md)
    OUT_JSON.write_text(js)
    c = data["counts"]
    print(f"wrote {OUT_MD} + {OUT_JSON}: "
          f"{c['builtin']} builtin, {c['dropin']} drop-in, "
          f"{c['guest']} guest, {c['aliases']} aliases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
