#!/usr/bin/env python3
"""Scan Chaba backlog cards tagged for the Cline lane and dispatch them
through bridge.py one at a time, then report back via board-api.

Card opt-in convention (both required):
  tags: [..., cline]          — selects this lane
  cline:
    deliverable: file.md      # required: artifact the task must produce
    sentinel: SOME_TOKEN      # optional: text that must appear in the file
    provider: ollama          # optional (default ollama)
    model: qwen2.5:7b         # optional (default qwen2.5:7b)
    timeout_s: 600            # optional (default 600)

Board-api-created cards can use spec lines instead of the block:
  cline-deliverable: file.md / cline-sentinel: T / cline-model: ollama/qwen2.5:7b

Only `column: backlog` cards are picked up; successful tasks move the
card to `review` with the patch summary commented. Runs serially.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path, PurePosixPath

import yaml

CARDS_DIR = Path.home() / "CascadeProjects/chaba/docs/ssot/kanban/cards"
BOARD_API = os.environ.get(
    "BOARD_API", "https://tony-dell.taila0626a.ts.net/apps/board-api"
).rstrip("/")
BRIDGE = Path(__file__).with_name("bridge.py")
OUT_ROOT = Path(__file__).resolve().parent / "out" / "intake"
LANE_TAG = "cline"
DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "qwen2.5:7b"
JOB_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,59}$")
ACTOR = "cline-intake"
SPEC_CHARS = 3000

PROMPT_TEMPLATE = """You are completing Chaba kanban card "{title}" in a disposable workspace.

Card spec:
{spec}

Write the deliverable as a single self-contained markdown file named {deliverable}. Cover the spec faithfully; where it names real systems, paths, units, or env vars use them verbatim and do not invent tooling that is not in the spec. Do not commit, push, or open a PR. Verify the file exists and report the changed path."""


def load_cards(cards_dir):
    cards = []
    for path in sorted(cards_dir.glob("*.yml")):
        try:
            card = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if isinstance(card, dict) and card.get("id"):
            cards.append(card)
    return cards


def lane_candidates(cards):
    out = []
    for card in cards:
        if card.get("column") != "backlog":
            continue
        if LANE_TAG not in (card.get("tags") or []):
            continue
        out.append(card)
    return out


SPEC_CFG_RE = re.compile(
    r"cline-(deliverable|sentinel|model|provider|timeout_s)\s*:\s*(\S+)")


def card_to_spec(card):
    cid = str(card.get("id") or "").strip()
    spec_text = str(card.get("spec") or "").strip()
    if not spec_text:
        raise ValueError(f"{cid}: card has no spec to prompt from")
    # `cline:` YAML block wins; `cline-<key>:` spec lines fill gaps so
    # board-api-created cards (spec-only) can opt in too.
    cfg = dict(SPEC_CFG_RE.findall(spec_text))
    block = card.get("cline")
    if isinstance(block, dict):
        cfg.update(block)
    pm = str(cfg.get("model") or "").strip()
    if "/" in pm and "provider" not in cfg:
        cfg["provider"], cfg["model"] = pm.split("/", 1)
    deliverable = str(cfg.get("deliverable") or "").strip()
    if not deliverable:
        raise ValueError(f"{cid}: cline.deliverable is required")
    path = PurePosixPath(deliverable)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{cid}: deliverable must be a relative path")
    title = str(card.get("title") or cid).strip()
    job_key = f"cline-{cid}"[:60]
    if not JOB_KEY_RE.fullmatch(job_key):
        raise ValueError(f"{cid}: cannot form a valid job_key")
    clean_spec = SPEC_CFG_RE.sub("", spec_text)
    envelope = {
        "job_key": job_key,
        "target_host": "con01",
        "execute": True,
        "title": title[:120],
        "project_path": "/workspace",
        "base_ref": "main",
        "agent_id": "cline",
        "provider_id": str(cfg.get("provider") or DEFAULT_PROVIDER),
        "model_id": str(cfg.get("model") or DEFAULT_MODEL),
        "timeout_s": int(cfg.get("timeout_s") or 600),
        "expected_file": deliverable,
        "prompt": PROMPT_TEMPLATE.format(
            title=title, spec=clean_spec[:SPEC_CHARS], deliverable=deliverable),
    }
    sentinel = str(cfg.get("sentinel") or "").strip()
    if sentinel:
        envelope["expected_text"] = sentinel
    return envelope


def board_api(path, body, timeout=30):
    req = urllib.request.Request(
        f"{BOARD_API}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read()[:200]!r}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def comment(card_id, text):
    return board_api("/comment", {"id": card_id, "from": ACTOR, "text": text})


def move_to_review(card_id):
    return board_api("/action", {
        "id": card_id, "do": "move", "column": "review", "from": ACTOR})


def run_card(card, dry_run):
    cid = card["id"]
    try:
        envelope = card_to_spec(card)
    except ValueError as exc:
        return {"card": cid, "status": "skipped", "reason": str(exc)}
    if dry_run:
        return {"card": cid, "status": "dry-run", "envelope": envelope}

    out_dir = OUT_ROOT / envelope["job_key"]
    out_dir.mkdir(parents=True, exist_ok=True)
    input_path = out_dir / "task.json"
    output_path = out_dir / "result.json"
    patch_path = out_dir / "task.patch"
    input_path.write_text(json.dumps(envelope, indent=2) + "\n")

    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(BRIDGE), "--input", str(input_path),
         "--output", str(output_path), "--patch", str(patch_path)],
        capture_output=True, text=True,
        timeout=envelope["timeout_s"] + 120)
    elapsed = int(time.time() - started)

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip().splitlines()
        detail = err[-1][:400] if err else f"exit {proc.returncode}"
        res = comment(
            cid,
            f"{ACTOR}: bridge failed after {elapsed}s — {detail}. "
            f"Card left in backlog; job_key {envelope['job_key']}.")
        return {"card": cid, "status": "failed", "error": detail,
                "comment": res}

    result = json.loads(output_path.read_text())
    res = comment(
        cid,
        f"{ACTOR}: task {result['task_id']} review-ready — "
        f"{result['expected_file']} verified, {result['patch_bytes']}B patch "
        f"({', '.join(result['changed_files'])}), "
        f"provider {envelope['provider_id']}/{envelope['model_id']}. "
        f"Patch: {patch_path}. Moving to review.")
    move = move_to_review(cid)
    return {"card": cid, "status": "done", "result": result,
            "comment": res, "move": move}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards-dir", type=Path, default=CARDS_DIR)
    ap.add_argument("--card", help="only this card id")
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--execute", action="store_true",
                    help="actually dispatch; default is dry-run")
    args = ap.parse_args()

    cards = load_cards(args.cards_dir)
    if args.card:
        candidates = [c for c in cards if c.get("id") == args.card]
        if not candidates:
            print(f"card {args.card} not found", file=sys.stderr)
            return 1
    else:
        candidates = lane_candidates(cards)

    results = []
    for card in candidates[: args.limit]:
        res = run_card(card, dry_run=not args.execute)
        results.append(res)
        print(json.dumps(res, indent=2, default=str), flush=True)
    if not results:
        print("no backlog cards tagged for the cline lane")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
