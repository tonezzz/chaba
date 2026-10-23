#!/usr/bin/env python3
"""Offline lesson miner — Ada voice transcripts -> WP lesson CPT.

Card lesson-transcript-miner: periodic batch job (idc03) that scans Ada
session transcripts for Tony's knowledge-Q&A turns, drafts lesson HTML
from the full transcript (richer than the live voice answer), and files
each topic via scripts/lesson-add.py (slug-upsert + automatic Thai
translation). Zero per-session prompt tokens, zero voice latency.

Pipeline per run:
  1. scan     — transcripts newer/changed since last run (state file)
  2. filter   — mechanical question-turn detection (no LLM)
  3. classify — ONE LLM call for the whole batch: which candidates are
                durable knowledge lessons vs commands/chit-chat
  4. draft    — one LLM call per kept topic (capped): standalone HTML
                lesson built from the full transcript context
  5. file     — subprocess scripts/lesson-add.py --source voice

Cost model: free-first. Model = $LESSON_MINER_MODEL (default
gemini-3.5-flash-lite). Key resolution: env GEMINI_API_KEY_FREE /
GEMINI_API_KEY / GOOGLE_API_KEY, then ~/.config/secrets/mddb-gemini.env,
gemini-keys.env, ada-pi-pwa.env. GEMINI_BASE_URL honored via
gemini_rest — point it at the LiteLLM gateway to ride the routed
fallback chain instead of the raw free tier.

Dedup: state file (~/.local/share/ada/lesson-miner-state.json) records
scanned transcripts {name: size} and filed lesson slugs — a topic Tony
re-asks does not burn another draft call (lesson-add.py would upsert in
place anyway; --reprocess/--refile override).

Safety: transcripts are private — excerpts go only to the LLM and the
lesson CPT (private posts). The draft prompt instructs the model to
strip personal specifics (names, addresses, schedules).

Usage:
  lesson-miner.py                          # mine new/changed transcripts
  lesson-miner.py --dry-run                # show candidates+drafts, file nothing
  lesson-miner.py --dir ~/.local/share/ada-review/transcripts --since 2026-10-10
  lesson-miner.py --card lesson-transcript-miner   # post run summary to board
  lesson-miner.py --reprocess              # ignore size dedup, rescan window
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_rest  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
LESSON_ADD = REPO / "scripts" / "lesson-add.py"
DEFAULT_DIR = Path.home() / ".local/share/ada/transcripts"
DEFAULT_STATE = Path.home() / ".local/share/ada/lesson-miner-state.json"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
BOARD_API = "https://tony-dell.taila0626a.ts.net/apps/board-api/comment"

TURN_RE = re.compile(r"^## (Ada|User)(?: \[(\d{2}):(\d{2}):(\d{2})\])?\s*$")
SESSION_RE = re.compile(r"^# Ada voice session (\S+)")

# Mechanical pre-filter — recall-biased; the LLM classify pass drops the
# false positives (commands, chit-chat, private asks).
QUESTION_START = re.compile(
    r"^(?:hey ada[, ]+|ada[, ]+)?"
    r"(?:what|what's|whats|how|why|when|where|which|who|whose|explain|"
    r"tell me|can you explain|do you know|what does|what is|"
    r"difference between|compare|is it true|does|is there)\b", re.I)
COMMAND_START = re.compile(
    r"^(?:hey ada[, ]+|ada[, ]+)?"
    r"(?:turn|switch|set|open|close|play|stop|start|remind|send|call|"
    r"text|add|create|put|take|navigate|volume|dim|lock|unlock|"
    r"restart|reboot|show me the|lights?)\b", re.I)
THAI_QUESTION = re.compile(r"(อะไร|ทำไม|ยังไง|คืออะไร|หมายถึงอะไร|ไหม|หรือ)")
MIN_Q_CHARS = 15

CLASSIFY_SCHEMA = """{"keep": [{"i": 1, "topic": "short topic title",
"level": "intro|working|deep"}]}"""

CLASSIFY_PROMPT = """You are mining an Ada voice-assistant transcript for
durable knowledge lessons — questions the user asked that deserve a
permanent explainer page (definitions, comparisons, how-things-work,
concepts, troubleshooting knowledge).

KEEP: genuine knowledge questions with a substantive answer.
DROP: device/smart-home commands, reminders, scheduling, chit-chat,
small talk, private/personal matters, questions Ada could not answer,
questions whose answer is only valid for one moment in time.

For each kept item give a short topic title (3-8 words, no dates) and a
level: intro (new concept), working (practical how-to), deep (internals).

Transcript may be Thai or mixed-language; topics/lessons are English.

Candidates (Q = user question, A = Ada's answer):
%s

Reply with ONE JSON object only, matching: %s
Empty result = {"keep": []}."""

DRAFT_PROMPT = """You are writing a durable lesson page from an Ada
voice-assistant transcript.

The user asked: "%s"

Write a standalone HTML fragment (use only <h3>, <h4>, <p>, <ul>, <ol>,
<li>, <code>, <pre>, <strong>, <em>, <a> — NO <html>/<head>/<body>/<h1>/
<h2>) that teaches the topic clearly:
- Start with a direct answer in 1-2 sentences, then expand.
- Use the transcript for what Ada actually explained, but correct ASR
  garble, fill obvious gaps, and organize it better than speech.
- Strip personal specifics (names, addresses, schedules, devices).
- If the transcript answer was partly wrong or uncertain, say so in a
  <p><em>Note: ...</em></p> rather than asserting it.
- ~150-400 words. English.

FULL TRANSCRIPT (context — the relevant exchange is around the quoted
question; other turns may add related detail):

%s

Output ONLY the HTML fragment."""


def parse_transcript(path: Path) -> tuple[str, str, list[dict]]:
    """-> (session_id, date, turns[{role,stamp,text}]). Same turn format
    as transcript-index.py ('## Ada|## User [HH:MM:SS]')."""
    session_id = path.stem.split("-", 3)[-1]
    date = path.stem[:10]
    turns: list[dict] = []
    cur: dict | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = SESSION_RE.match(line)
        if m:
            session_id = m.group(1)
            continue
        m = TURN_RE.match(line)
        if m:
            if cur is not None:
                turns.append(cur)
            stamp = (f"{m.group(2)}:{m.group(3)}:{m.group(4)}"
                     if m.group(2) else None)
            cur = {"role": "user" if m.group(1) == "User" else "ada",
                   "stamp": stamp, "text": []}
            continue
        if cur is not None:
            cur["text"].append(line)
    if cur is not None:
        turns.append(cur)
    for t in turns:
        t["text"] = "\n".join(t["text"]).strip()
    return session_id, date, turns


def is_question_turn(text: str) -> bool:
    if len(text) < MIN_Q_CHARS:
        return False
    if COMMAND_START.match(text):
        return False
    return bool("?" in text or QUESTION_START.match(text)
                or THAI_QUESTION.search(text))


def find_candidates(turns: list[dict], max_q: int = 600,
                    max_a: int = 1500) -> list[dict]:
    """Pair each knowledge-question user turn with the following Ada
    turn(s) as its answer."""
    out = []
    for i, t in enumerate(turns):
        if t["role"] != "user" or not is_question_turn(t["text"]):
            continue
        ans = []
        for nxt in turns[i + 1:]:
            if nxt["role"] == "user":
                break
            if nxt["text"]:
                ans.append(nxt["text"])
        answer = "\n".join(ans).strip()
        if not answer:
            continue
        out.append({"q": t["text"][:max_q], "a": answer[:max_a],
                    "stamp": t["stamp"]})
    return out


def lesson_slug(topic: str) -> str:
    return "lesson-" + hashlib.md5(
        topic.strip().lower().encode()).hexdigest()[:12]


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {"scanned": {}, "filed": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def load_key() -> str | None:
    for var in ("GEMINI_API_KEY_FREE", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    for f in ("~/.config/secrets/mddb-gemini.env",
              "~/.config/secrets/gemini-keys.env",
              "~/.config/secrets/ada-pi-pwa.env"):
        try:
            for ln in open(os.path.expanduser(f)):
                m = re.match(
                    r"^(GEMINI_API_KEY_FREE|GEMINI_API_KEY|GOOGLE_API_KEY)=(.*)$",
                    ln.strip())
                if m:
                    return m.group(2).strip().strip('"').strip("'")
        except OSError:
            pass
    return None


def classify(candidates: list[dict], model: str, key: str) -> list[dict]:
    """One JSON-mode call over the whole batch -> kept items with
    topic/level attached."""
    body = "\n\n".join(
        f"{i + 1}. Q: {c['q']}\n   A: {c['a']}"
        for i, c in enumerate(candidates))
    try:
        r = gemini_rest.generate_json(
            CLASSIFY_PROMPT % (body, CLASSIFY_SCHEMA), model, key=key)
    except ValueError as e:
        print(f"  classify: unparseable JSON ({e})", file=sys.stderr)
        return []
    if not r:
        return []
    kept = []
    for k in r.get("keep") or []:
        try:
            c = dict(candidates[int(k["i"]) - 1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        c["topic"] = str(k.get("topic", "")).strip() or c["q"][:60]
        c["level"] = k.get("level") if k.get("level") in (
            "intro", "working", "deep") else "intro"
        kept.append(c)
    return kept


def draft_lesson(transcript_text: str, qna: dict, model: str,
                 key: str) -> str | None:
    html = gemini_rest.generate(
        DRAFT_PROMPT % (qna["q"], transcript_text), model, key=key)
    if not html:
        return None
    # strip markdown fences if the model wraps anyway
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", html.strip(),
                  flags=re.M).strip()
    return html or None


def file_lesson(topic: str, level: str, html: str) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile(
            "w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    r = subprocess.run(
        [sys.executable, str(LESSON_ADD), "--topic", topic,
         "--level", level, "--source", "voice", "--content-file", tmp],
        capture_output=True, text=True, timeout=180)
    Path(tmp).unlink(missing_ok=True)
    ok = r.returncode == 0
    return ok, (r.stdout + r.stderr).strip()


def post_comment(card: str, text: str) -> None:
    payload = json.dumps({"id": card, "from": "lesson-miner", "text": text})
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", BOARD_API,
         "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        print(f"warn: board-api comment failed: {r.stderr.strip()}",
              file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR,
                    help="transcript dir (default ~/.local/share/ada/"
                         "transcripts — idc03 runtime host)")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--since", default=None,
                    help="only transcripts dated >= YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=30,
                    help="max transcripts per run")
    ap.add_argument("--max-candidates", type=int, default=40,
                    help="cap Q&A pairs sent to the classify call")
    ap.add_argument("--max-lessons", type=int, default=4,
                    help="cap draft calls per run")
    ap.add_argument("--model", default=None,
                    help="default $LESSON_MINER_MODEL or "
                         + DEFAULT_MODEL)
    ap.add_argument("--card", default=None,
                    help="post a run summary to this kanban card")
    ap.add_argument("--dry-run", action="store_true",
                    help="classify+draft but file nothing")
    ap.add_argument("--no-draft", action="store_true",
                    help="classify only — no draft calls (free pass)")
    ap.add_argument("--reprocess", action="store_true",
                    help="ignore transcript-size dedup")
    ap.add_argument("--refile", action="store_true",
                    help="allow re-drafting already-filed topics")
    args = ap.parse_args()

    model = args.model or os.environ.get("LESSON_MINER_MODEL",
                                         DEFAULT_MODEL)
    tdir = args.dir.expanduser()
    state = load_state(args.state.expanduser())
    state.setdefault("scanned", {})
    state.setdefault("filed", {})

    files = sorted(p for p in tdir.glob("*.md") if p.is_file())
    if args.since:
        files = [p for p in files if p.name >= args.since]
    files = files[-args.limit:]

    new_files = []
    for p in files:
        size = p.stat().st_size
        if args.reprocess or state["scanned"].get(p.name) != size:
            new_files.append(p)
    if not new_files:
        print("lesson-miner: no new/changed transcripts")
        return 0

    key = load_key()
    if not key:
        print("no GEMINI key in env or secrets — cannot classify",
              file=sys.stderr)
        return 1

    all_candidates: list[dict] = []
    transcripts: dict[str, tuple[str, str, str, list[dict]]] = {}
    for p in new_files:
        text = p.read_text(encoding="utf-8")
        sid, sdate, turns = parse_transcript(p)
        cands = find_candidates(turns)
        transcripts[p.name] = (text, sid, sdate, turns)
        for c in cands:
            c["file"] = p.name
        all_candidates.extend(cands)
        print(f"{p.name}: {len(turns)} turns, "
              f"{len(cands)} question candidates")

    overflow = max(0, len(all_candidates) - args.max_candidates)
    all_candidates = all_candidates[: args.max_candidates]
    if overflow:
        print(f"note: {overflow} candidates over --max-candidates, "
              "deferred to next run", file=sys.stderr)
        # leave transcripts carrying overflow candidates un-scanned so
        # they are picked up next run
        seen_files = {c["file"] for c in all_candidates}
        new_files = [p for p in new_files if p.name in seen_files]

    kept: list[dict] = []
    if all_candidates:
        kept = classify(all_candidates, model, key)
    print(f"classify: {len(all_candidates)} candidates -> "
          f"{len(kept)} lesson-worthy")

    filed, attempted = [], 0
    for c in kept[: args.max_lessons]:
        slug = lesson_slug(c["topic"])
        if slug in state["filed"] and not args.refile:
            print(f"  skip {c['topic']!r} — already filed "
                  f"{state['filed'][slug].get('at')}")
            continue
        attempted += 1
        text, sid, sdate, _ = transcripts[c["file"]]
        html = None if args.no_draft else draft_lesson(text, c, model, key)
        if args.dry_run or args.no_draft:
            print(f"\n--- draft {c['topic']!r} ({c['level']}) "
                  f"from {c['file']} [{c.get('stamp')}] ---")
            print(html or "(no-draft)")
            continue
        if not html:
            print(f"  draft failed for {c['topic']!r}", file=sys.stderr)
            continue
        ok, out = file_lesson(c["topic"], c["level"], html)
        print(f"  {'filed' if ok else 'FAILED'} {c['topic']!r}: {out}")
        if ok:
            state["filed"][slug] = {
                "topic": c["topic"], "at": sdate, "file": c["file"],
                "level": c["level"]}
            filed.append(c["topic"])

    if not (args.dry_run or args.no_draft):
        for p in new_files:
            state["scanned"][p.name] = p.stat().st_size
        save_state(args.state.expanduser(), state)

    summary = (f"lesson-miner {date.today()}: "
               f"scanned {len(new_files)} transcripts, "
               f"{len(all_candidates)} candidates, "
               f"{len(kept)} kept, filed {len(filed)}"
               + (f" ({', '.join(filed)})" if filed else "")
               + (" [dry-run]" if args.dry_run else ""))
    print(summary)
    # quiet-when-empty: the daily job only comments when it filed, or
    # when drafting/filing was attempted and everything failed
    if args.card and (filed or (attempted and not filed
                                and not args.dry_run and not args.no_draft)):
        post_comment(args.card, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
