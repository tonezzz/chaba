#!/usr/bin/env python3
"""Stage-2: per-session report from an Ada voice transcript (one LLM call).

Consumes a raw transcript .md (written by ada-pi conversation_memory.py)
and produces a structured JSON report that serves two consumers:

  memory feed : report["memory_block"] — a compact "## date session" entry
                for rolling-log session-memory.md files (render-memory.py
                format: entries split on '## ' headings, min_chars gate)
  audit       : report["audit"] — missed actions, recall failures, tool
                issues, noise turns. Review-only, never injected.

Per the ada-memory-banks language_policy: the raw transcript keeps the
original language; this report is the canonical English index layer.

Usage:
  session-report.py TRANSCRIPT.md [--out reports/] [--emit-session-log FILE]
  GEMINI_API_KEY read from env or ~/.config/secrets/ada-pi-pwa.env
  Model: $ADA_REPORT_MODEL (default gemini-3.5-flash-lite)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

DEFAULT_MODEL = os.environ.get("ADA_REPORT_MODEL", "gemini-3.5-flash-lite")
SECRETS = Path.home() / ".config/secrets/ada-pi-pwa.env"

SCHEMA_HINT = """{
  "summary": "1-2 sentence English digest of the session",
  "focus": ["short-kebab-tag", "..."],
  "topics": ["..."],
  "actions_taken": ["things Ada confirmed doing"],
  "actions_proposed_pending": ["offers made but not confirmed"],
  "open_loops": ["unresolved threads the user may return to"],
  "people": ["names mentioned"],
  "audit": {
    "missed_actions": ["user asked, Ada did not act or offer"],
    "recall_failures": ["questions Ada should have answered from memory but could not"],
    "tool_issues": ["wrong/missing/excessive tool use, if evident"],
    "prompt_gaps": ["behavior suggesting the system prompt needs a rule"],
    "noise_or_asr_issues": ["turns that look like ambient noise or ASR garbage"],
    "notes": "one line overall quality note"
  },
  "memory_block": "markdown starting with '## YYYY-MM-DD <session_id>' — 3-6 short lines: what was discussed, what was done, what is open. English. This block is injected into future session context, so write it for an assistant reading it cold."
}"""

PROMPT = """You are auditing one Ada voice-assistant session transcript.

SESSION META (authoritative — use exactly in memory_block heading):
  file: %s
  date: %s
  session_id: %s

Rules:
- Reply with ONE JSON object only, no prose, matching this shape:
%s
- Transcript text is original-language (mostly Thai; Ada = assistant).
  Write ALL report fields in English (canonical index layer).
- focus tags: 1-3 emergent project/thread labels (e.g. "washer-repair",
  "ada-dev", "roof-leak") — reused across sessions for rollup grouping.
- Be precise in audit: only list findings actually visible in the text.
- If turns look like foreign-language ambient noise (Korean/Japanese/
  Chinese utterances in a Thai session), flag them in noise_or_asr_issues.
- memory_block MUST start with exactly: ## {date} {session_id}

TRANSCRIPT:
%s"""


def _load_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    try:
        for line in SECRETS.read_text().splitlines():
            if line.startswith(("GEMINI_API_KEY=", "GOOGLE_API_KEY=")):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def gemini_json(prompt: str, model: str, key: str) -> dict:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--out", type=Path, default=None,
                    help="report dir (default <transcript-dir>/../reports)")
    ap.add_argument("--emit-session-log", type=Path, default=None,
                    help="append memory_block to this rolling-log file")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    key = _load_key()
    if not key:
        print("no GEMINI_API_KEY/GOOGLE_API_KEY in env or secrets",
              file=sys.stderr)
        return 1

    date = args.transcript.stem[:10]
    session_id = args.transcript.stem.split("-", 3)[-1]
    text = args.transcript.read_text(encoding="utf-8")
    report = gemini_json(
        PROMPT % (args.transcript.name, date, session_id, SCHEMA_HINT, text),
        args.model, key)
    report["file"] = args.transcript.name
    report["date"] = date
    report["session_id"] = session_id
    report["model"] = args.model

    # Normalize memory_block heading — models drift on dates; the heading
    # is the rolling-log key so it must be exact.
    block = report.get("memory_block", "").strip()
    if block:
        body = block.split("\n", 1)[1] if "\n" in block else ""
        report["memory_block"] = f"## {date} {session_id}\n{body}".rstrip()

    outdir = args.out or (args.transcript.parent.parent / "reports")
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (args.transcript.stem + ".json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"wrote {out}")

    block = report.get("memory_block", "")
    if args.emit_session_log and block:
        log = args.emit_session_log.expanduser()
        prev = log.read_text(encoding="utf-8") if log.exists() else ""
        if not prev.endswith("\n"):
            prev += "\n"
        log.write_text(prev + "\n" + block.strip() + "\n", encoding="utf-8")
        print(f"appended memory_block -> {log}")

    print("\n--- memory_block preview ---")
    print(block or "(none)")
    print("\n--- audit ---")
    print(json.dumps(report.get("audit", {}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
