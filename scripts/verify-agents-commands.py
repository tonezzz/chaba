#!/usr/bin/env python3
"""Verify that fenced bash commands in AGENTS.md resolve to real executables/files."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

AGENTS = Path.home() / "CascadeProjects" / "chaba" / "AGENTS.md"
REPO = AGENTS.parent


def _find_command(tokens):
    """Find the first executable or script path in a shell command."""
    for t in tokens:
        if t.startswith("(") or t.startswith("{"):
            continue
        if t in ("cd", "ssh", "scp", "curl", "systemctl", "git", "make", "nlm", "nlmq"):
            return t
        if Path(t).is_file() or shutil.which(t):
            return t
    return None


KNOWN_CMDS = (
    "python3", "node", "nlm", "nlmq", "nlm-cite", "nlm-add", "nbapi", "chaba-ask",
    "ssh", "scp", "rsync", "systemctl", "make", "npm", "git", "curl", "rclone",
    "bash", "pgrep", "cd", "flock", "cp", "mv", "rm", "mkdir", "cat", "echo",
)


def _check(line: str):
    """Return (ok, detail) for a single command line."""
    line = line.strip().lstrip("$ ").strip()
    if not line or line.startswith("#") or line == "```":
        return True, ""

    # Skip prose/markdown bullets and backtick lines
    if re.match(r"^(\s*[-*]|\s*\d+\.|\s*\*\*|`|\s*<|\s*\[|\s*\!|\s*\|)", line):
        return True, ""

    # Split by unquoted spaces
    tokens = re.findall(r"[^\s\"']+|\"[^\"]*\"|'[^']*'", line)
    tokens = [t.strip("\"'") for t in tokens]
    if not tokens:
        return True, ""

    first = tokens[0]
    # Looks like prose / human sentence inside a code block
    if re.match(r"^[A-Z]", first) and not shutil.which(first) and not Path(first).is_file():
        return True, ""
    if first not in KNOWN_CMDS and not shutil.which(first) and not Path(first).is_file():
        return False, f"unrecognized executable: {line[:80]}"

    cmd = _find_command(tokens) or first

    # For python3/node scripts with a script argument, check the script exists
    if cmd in ("python3", "node") and len(tokens) >= 2:
        script = tokens[1]
        if script.startswith("-"):
            return True, f"ok ({cmd})"  # e.g. python3 --version
        p = (REPO / script) if not Path(script).is_absolute() else Path(script)
        if not p.is_file() and not shutil.which(script):
            return False, f"missing script: {script}"

    return True, f"ok ({cmd})"


def main():
    text = AGENTS.read_text(encoding="utf-8", errors="ignore")
    # Extract ```bash ... ``` blocks
    blocks = re.findall(r"```bash\n(.*?)\n```", text, re.DOTALL)

    fails = 0
    for block in blocks:
        # join \ line continuations first
        raw_lines = [r.strip() for r in block.splitlines()]
        merged = []
        buf = ""
        for raw in raw_lines:
            if raw.endswith("\\"):
                buf += raw[:-1].strip() + " "
            else:
                merged.append(buf + raw)
                buf = ""
        if buf:
            merged.append(buf)

        for line in merged:
            if not line or line.startswith("#") or line == "```":
                continue
            ok, detail = _check(line)
            if ok:
                print(f"  OK   {detail}: {line[:80]}")
            else:
                print(f"  FAIL {detail}: {line[:80]}")
                fails += 1

    print(f"\nVerified {len(blocks)} bash blocks; {fails} issues.")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
