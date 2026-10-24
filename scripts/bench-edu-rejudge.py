#!/usr/bin/env python3
"""Re-grade saved education benchmark HTML without rerunning a model lane.

Input files are completed or partial bench-edu-manage result JSONs. The
script reads filings from tasks[].filings[].content and writes a separate
judge artifact; it never changes the source result. Default key source is
the free Gemini slot in ~/.config/secrets/gemini-keys.env. Tokens and
tokenized URLs are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

AXES = ("direct_answer", "accuracy", "structure", "hygiene", "length")
MODEL = "gemini-3.5-flash-lite"
KEY_FILE = Path("~/.config/secrets/gemini-keys.env").expanduser()


def load_key() -> str | None:
    if os.environ.get("GEMINI_API_KEY_FREE"):
        return os.environ["GEMINI_API_KEY_FREE"]
    try:
        for line in KEY_FILE.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY_FREE="):
                value = line.partition("=")[2].strip().strip('"').strip("'")
                return value or None
    except OSError:
        pass
    return None


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def collect_drafts(result: dict, corpus: dict, source: str) -> list[dict]:
    by_id = {task["id"]: task for task in corpus.get("tasks", [])}
    out = []
    for lane, records in (result.get("tasks") or {}).items():
        for record in records:
            task = by_id.get(record.get("task"), {})
            for filing in record.get("filings") or []:
                html = str(filing.get("content") or "")
                if len(html.strip()) < 30:
                    continue
                matches = [
                    match
                    for keep in task.get("keep", [])
                    if any(norm(candidate) in norm(filing.get("topic", ""))
                           or norm(filing.get("topic", "")) in norm(candidate)
                           for candidate in keep.get("match", []))
                    for match in keep.get("match", [])
                ]
                out.append({
                    "source": source,
                    "lane": lane,
                    "rep": record.get("rep"),
                    "task": record.get("task", ""),
                    "slug": filing.get("slug", ""),
                    "topic": filing.get("topic", ""),
                    "question": matches[0] if matches else
                                str(filing.get("topic") or record.get("task")),
                    "html": html,
                })
    return out


def parse_scores(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    out = {}
    for axis in AXES:
        value = data.get(axis)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not 0 <= float(value) <= 5:
            return None
        out[axis] = float(value)
    out["mean"] = sum(out[a] for a in AXES) / len(AXES)
    return out


def request_grade(draft: dict, key: str, model: str) -> tuple[dict | None, str]:
    prompt = (
        "Grade this lesson draft for a personal education ledger. "
        f"Source question: {draft['question']!r}\n\n"
        "Score each axis from 0 to 5: direct_answer, accuracy, structure, "
        "hygiene, length. Accuracy means the lesson is coherent and "
        "factually sound. Structure means a clean standalone HTML lesson "
        "fragment. Hygiene means no private/personal specifics. Length "
        "means approximately 150-400 words. Return one JSON object with "
        "exactly those five numeric keys.\n\nDRAFT:\n" + draft["html"][:6000]
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    }).encode()
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent",
        data=body,
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return None, f"http-{exc.code}"
    except Exception as exc:
        return None, type(exc).__name__.lower()
    text = "".join(
        part.get("text", "")
        for part in (payload.get("candidates") or [{}])[0]
        .get("content", {}).get("parts", [])
    )
    scores = parse_scores(text)
    return (scores, "") if scores else (None, "invalid-json-score")


def summarize(rows: list[dict]) -> dict:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        scores = row.get("scores")
        if scores:
            groups[row["lane"]].append(scores["mean"])
    return {
        lane: {
            "n": len(values),
            "mean": round(sum(values) / len(values), 3),
        }
        for lane, values in groups.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path(
        __file__).resolve().parent / "bench-edu-corpus.json")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("results", nargs="+", type=Path,
                        help="saved bench-edu-manage result JSONs")
    args = parser.parse_args()

    key = load_key()
    if not key:
        print("no GEMINI_API_KEY_FREE in environment or gemini-keys.env",
              file=sys.stderr)
        return 2
    corpus = json.loads(args.corpus.read_text())
    drafts = []
    for path in args.results:
        result = json.loads(path.read_text())
        drafts.extend(collect_drafts(result, corpus, path.name))
    if not drafts:
        print("no saved HTML filings found", file=sys.stderr)
        return 2

    rows = []
    for i, draft in enumerate(drafts, 1):
        scores, error = request_grade(draft, key, args.model)
        row = {k: v for k, v in draft.items() if k != "html"}
        row.update(scores=scores, error=error or None)
        rows.append(row)
        print(f"[{i}/{len(drafts)}] {draft['source']} "
              f"{draft['lane']} {draft['task']} "
              f"{'mean='+str(round(scores['mean'], 2)) if scores else error}",
              flush=True)
        if error == "http-429":
            for later in drafts[i:]:
                row = {k: v for k, v in later.items() if k != "html"}
                row.update(scores=None, error="not-attempted-after-429")
                rows.append(row)
            break
        time.sleep(0.25)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "at": datetime.now(timezone.utc).isoformat(),
        "judge": args.model,
        "judge_source": "GEMINI_API_KEY_FREE",
        "input_results": [str(p) for p in args.results],
        "drafts": rows,
        "summary": summarize(rows),
    }
    args.out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
