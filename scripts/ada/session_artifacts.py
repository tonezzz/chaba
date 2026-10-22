#!/usr/bin/env python3
"""session_artifacts — deterministic "## Artifacts" extractor for
devin-session T1 docs (card session-mddb-recall-benchmark).

Bench 2026-10-22 showed the per-session distilled doc in
ada-ha-bank-devin-tony answers only ~42% of teammate recall questions —
the prose summary drops exactly the things people later ask for:
absolute paths, commands run, commit hashes, card ids, hosts/ports,
collection names, counts, and error strings. An LLM re-distill is not
needed for those: they are verbatim facts already in the transcript.
This module mines them deterministically and renders a compact
markdown section that sync-devin-summaries.py appends to the T1 doc
(or bench-recall uses to build v2 docs).

  from session_artifacts import artifacts_section
  md = artifacts_section(transcript_text)

CLI: session_artifacts.py <transcript.md>   # prints the section
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

# ---- caps: keep the section small — T1's whole value is bytes/session.
MAX_PATHS = 40
MAX_CMDS = 30
MAX_IDS = 50
MAX_ERRORS = 15
MAX_LINE = 180

_URL_RE = re.compile(r"https?://[^\s)\]>'\"`]+")
_PATH_RE = re.compile(r"(?<![\w/.:-])((?:~|\.{1,2})?/[\w.][\w./+-]{2,}[\w./-])")
_REL_PATH_RE = re.compile(
    r"(?<![\w./:-])((?:docs|scripts|apps|stacks|systemd|tests|fixtures|"
    r"reports|web|public|mcp|mcp-servers|edge|data|workflows|notebooks|"
    r"experiments|docker|integrations|frigate|esp32|src|lib|bin|etc)/"
    r"[\w./+-]{2,}[\w.-])")
# A plausible command line: starts a line (after optional prompt) with a
# known binary. Long pipelines are truncated, not dropped.
_CMD_RE = re.compile(
    r"^[ \t]*[$#>%]?[ \t]*((?:sudo[ \t]+)?(?:env[ \t]+\w+=\S+[ \t]+)*"
    r"(?:git|curl|wget|systemctl|journalctl|python\d*|bash|sh|ssh|scp|"
    r"rsync|nlm|podman|docker|sqlite3|npm|npx|node|pip\d*|jq|tar|"
    r"chmod|chown|chattr|mkdir|rmdir|rm|mv|cp|ln|grep|rg|find|fd|sed|"
    r"awk|xargs|make|just|ninja|cmake|go|cargo|kubectl|helm|caddy|"
    r"certbot|tailscale|ping|dig|nslookup|ss|lsof|fuser|df|du|ls|cat|"
    r"head|tail|tee|touch|hostname|uname|date|flock|ps|kill|pkill|"
    r"pgrep|timeout|watch|tmux|screen|crontab|at|openssl|md5sum|"
    r"sha256sum|diff|patch|gcc|g\+\+|clang|ffmpeg|ffprobe|convert|"
    r"rsnapshot|restic|rclone|gh|glab|hugo|vite|esbuild|tsc|eslint|"
    r"prettier|pytest|jest|vitest|playwright|ansible|terraform|"
    r"report-note\.py|lesson-add\.py|sync-[\w.-]+\.py|bench-[\w.-]+\.py|"
    r"devin[ \t]+(?:rm|ls|new|resume|run|login|status|ps|exec|ssh|acp|"
    r"upload|secrets?|watch|attach|--help|-h|-p)\b|"
    r"[a-zA-Z_][\w.-]*\.(?:py|sh|mjs|js|ts))(?=\s|$)[^\n|;&]{0,170})",
    re.M)
_FULL_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")
_SHORT_SHA_RE = re.compile(r"\b[0-9a-f]{7,10}\b")
_BRANCH_RE = re.compile(
    r"(?<![\w/~.-])(?:dispatch|origin|feature|fix|hotfix|release)/[\w.-]+")
_MDDBKEY_RE = re.compile(
    r"(?<![\w/~.-])(?:devin-session/[\w.-]+|devin/[\w.-]{5,}|job/[\w.-]{4,})")
_CARD_RE = re.compile(r"\b[A-Z]{2,6}-\d{3,5}\b")
_TASKID_RE = re.compile(r"\b\d{6,8}-\d{6}-[\w-]{4,}\b")
_HOST_RE = re.compile(
    r"\b(tony-dell|tony-omen|tony-macbook|tony-ha|idc0\d|idc\d+|mn01|"
    r"con01|ada-ha|michael-dev|michael-ha|tony-test)\b")
_COLLECTION_RE = re.compile(r"\bada-[\w-]*bank[\w-]*\b")
_PORT_RE = re.compile(r"\b(?:127\.0\.0\.1|localhost|0\.0\.0\.0|\d{1,3}(?:\.\d{1,3}){3}|[\w-]+(?:\.[\w-]+)+):(\d{4,5})\b")
_SIZE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB|KiB|MiB|GiB|TiB|%|percent)\b")
_FRACTION_RE = re.compile(r"\b\d+/\d+\b")
_ERROR_RE = re.compile(
    r"^[^\n]{0,170}?(?:Traceback|\bERROR\b|\bError\b|error:|failed\b|"
    r"\bFAILED\b|Exception|errno|denied|refused|timed out|"
    r"corrupt|malformed)[^\n]{0,30}$", re.M | re.I)
_ERROR_NOISE = re.compile(
    r"^(?:Input:|Output:|Observ|\{|\"|\[|//|#|<!--)|\"timeout\"|"
    r"error_(?:code|message|type)_?[\"']?\s*[:=]|\"error\"\s*:", re.I)

# Noise: paths that appear in every session and carry no recall value.
_PATH_NOISE = re.compile(
    r"^/(?:proc|sys|dev|usr/(?:lib|share|include|src)|lib(?:64)?|bin|sbin|"
    r"etc/(?:ssl|passwd|group|hosts)|run/user|tmp/devin-overflows|"
    r"var/(?:lib|log|cache)/(?:apt|dpkg|systemd))")


def _clip(s: str, n: int = MAX_LINE) -> str:
    s = re.sub(r"\s+", " ", s).strip().rstrip("\\`")
    return s if len(s) <= n else s[: n - 1] + "…"


def _top(counter: Counter, cap: int) -> list[str]:
    return [item for item, _ in counter.most_common(cap)]


def extract(transcript: str) -> dict[str, list[str]]:
    """Mine artifact classes from raw session transcript text."""
    text = _URL_RE.sub(" ", transcript)  # keep URLs separate from paths

    paths = Counter()
    for m in _PATH_RE.finditer(text):
        p = m.group(1).rstrip(".,;:!?)\"'`]")
        if len(p) < 4 or p.startswith("//") or _PATH_NOISE.match(p):
            continue
        if re.match(r"^/\d+(/\d+|\.\d+)*$", p):
            continue
        paths[_clip(p)] += 1
    for m in _REL_PATH_RE.finditer(text):
        p = m.group(1).rstrip(".,;:!?)\"'`]")
        if len(p) >= 8:
            paths[_clip(p)] += 1

    cmds = Counter()
    for m in _CMD_RE.finditer(transcript):
        c = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(c) >= 8 and not c.startswith(("cat ", "echo ")):
            cmds[_clip(c)] += 1

    ids = Counter()
    for sha in _FULL_SHA_RE.findall(transcript):
        ids[f"commit:{sha[:12]}"] += 1
    git_ctx = re.findall(
        r"(?:commit|committing|committed|HEAD|checkout|merge|cherry-pick|"
        r"rebase|sha|rev)[^\n]{0,60}", transcript)
    ctx_blob = "\n".join(git_ctx)
    for sha in _SHORT_SHA_RE.findall(ctx_blob):
        if not re.fullmatch(r"\d{7,10}", sha):  # skip pure numbers
            ids.setdefault(f"commit:{sha}", 0)
            ids[f"commit:{sha}"] += 1
    for b in _BRANCH_RE.findall(transcript):
        if re.fullmatch(r"[\w.-]+", b) and len(b) > 8:
            ids[f"branch:{b}"] += 1
    for k in _MDDBKEY_RE.findall(transcript):
        ids[f"key:{k}"] += 1
    for c in _CARD_RE.findall(transcript):
        ids[f"card:{c}"] += 1
    for t in _TASKID_RE.findall(transcript):
        ids[f"task:{t}"] += 1
    for h in _HOST_RE.findall(transcript):
        ids[f"host:{h}"] += 1
    for c in _COLLECTION_RE.findall(transcript):
        ids[f"collection:{c}"] += 1
    for u in _URL_RE.findall(transcript):
        ids[f"url:{_clip(u, 120)}"] += 1
    for s in _SIZE_RE.findall(transcript):
        ids[f"size:{s}"] += 1
    for f in _FRACTION_RE.findall(transcript):
        ids[f"count:{f}"] += 1

    errors = Counter()
    for m in _ERROR_RE.finditer(transcript):
        e = _clip(m.group(0))
        if len(e) >= 15 and not _ERROR_NOISE.match(e):
            errors[e] += 1

    return {"paths": _top(paths, MAX_PATHS),
            "commands": _top(cmds, MAX_CMDS),
            "identifiers": _top(ids, MAX_IDS),
            "errors": _top(errors, MAX_ERRORS)}


def artifacts_section(transcript: str) -> str:
    """Render the mined artifacts as a markdown section for the T1 doc."""
    a = extract(transcript)
    if not any(a.values()):
        return ""
    out = ["\n\n## Artifacts", ""]
    if a["paths"]:
        out += ["### Files & paths", ""]
        out += [f"- `{p}`" for p in a["paths"]]
        out += [""]
    if a["commands"]:
        out += ["### Commands run", ""]
        out += [f"- `{c}`" for c in a["commands"]]
        out += [""]
    if a["identifiers"]:
        out += ["### Identifiers", ""]
        groups: dict[str, list[str]] = {}
        for i in a["identifiers"]:
            k, _, v = i.partition(":")
            groups.setdefault(k, []).append(v)
        for k, vs in groups.items():
            out.append(f"- **{k}**: " + ", ".join(f"`{v}`" for v in vs))
        out += [""]
    if a["errors"]:
        out += ["### Errors seen", ""]
        out += [f"- `{e}`" for e in a["errors"]]
        out += [""]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    text = Path(sys.argv[1]).read_text(errors="replace")
    sys.stdout.write(artifacts_section(text) or "(no artifacts found)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
