#!/usr/bin/env python3
"""Backfill the `brief` field on kanban cards (kanban-card-brief).

A brief is 2-3 plain-language sentences for the operator: the situation
first, then the expected action. New cards should ship with one — this
script is the catch-up pass for cards written before the convention.

Insertion is textual (a `brief: "..."` line added just before `column:`)
rather than a YAML re-dump, so untouched fields keep their formatting and
the git diff stays one line per card.

Usage: backfill-briefs.py [--dry-run] [--force] [--glob PATTERN]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent.parent
CARD_DIR = REPO / "docs/ssot/kanban/cards"
CARD_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# leading datelines like "Tony ask (2026-10-06):" or "2026-10-06:" add
# no situation value — drop them so the brief starts on content
DATELINE_RE = re.compile(
    r"^(?:[A-Z][^(\n]{0,40}\(\d{4}-\d{2}-\d{2}[^)]*\)|(?:\w+\s+)?"
    r"\d{4}-\d{2}-\d{2})\s*:\s*")

# Hand-written briefs for cards whose note/title can't yield plain
# language on their own (empty note, path/file-list openers, heavy
# jargon). The whole point of `brief` is operator readability — a bad
# auto-brief is worse than the template fallback.
OVERRIDES = {
    "ada-remember-confirm-flake":
        "Ada sometimes said \"saved\" when a memory write had actually "
        "failed. The fix for that is done — check the result and close "
        "the card if it looks right.",
    "ada-market-tool":
        "When you ask Ada about gold, exchange rates, or Thai stocks she "
        "often guesses instead of looking up real numbers. The plan is a "
        "lookup tool backed by the trade database — waiting in the "
        "backlog, no action needed.",
    "chaba-nest-models":
        "Idea: give every small node its own tiny AI model that gets "
        "smarter when the nodes connect. It's a vision card sitting in "
        "the backlog — no action needed yet.",
    "device-tracking":
        "All the pieces to locate a lost device already exist — this "
        "adds one place that pulls them together. Waiting in the "
        "backlog — no action needed.",
    "dev-ha-edge":
        "Adds the two development Home Assistant sites to the same "
        "public-edge setup the live ones already use. Queued — a worker "
        "session will pick it up; no action needed.",
    "edge-ha-restructure-subdomain-cloudflare-4ff3ad":
        "The public edge works but every box is a single point of "
        "failure and names are inconsistent across three places. It "
        "needs a decision — read the note and pick a direction.",
    "edge-route-registry":
        "Route rules were being written in five different places, which "
        "is how stale paths sneak in. There's now one registry that "
        "generates them all — check the result and close the card.",
    "flood-hub-integration":
        "Waiting on Google's waitlist for the flood-forecast API, which "
        "reportedly takes months. Nothing to do until the approval "
        "email arrives.",
    "gev-program-design":
        "Tracker card that maps all the God's-Eye-View work and the "
        "order to do it in. For orientation — no action needed.",
    "google-token-loud-fail":
        "Calendar and task lookups on one host were silently returning "
        "empty results when the Google login expired. A fix is done — "
        "check it and close the card.",
    "idc03-vault-checkout-drift":
        "One server's copy of this repo was thousands of commits "
        "behind, so the memory services on it were running stale code. "
        "Fixed — check the result and close the card.",
    "lab-gold-thb-causality":
        "An experiment collecting gold, baht, and dollar prices to see "
        "which moves first. Data is still gathering — a keep-or-close "
        "decision is due 2026-10-18.",
    "lab-mddb-quantized":
        "An experiment to shrink the memory database's vectors so "
        "lookups get cheaper; it's now testable on the spare node. "
        "Sitting in the backlog — no action needed.",
    "lab-meshtastic-th":
        "An experiment listening to the Thai Meshtastic radio mesh and "
        "mapping what it hears. Keep-or-close decision due 2026-10-18.",
    "lab-yolo-ha-detect":
        "An experiment to run object detection on the home camera "
        "feeds. Sitting in the backlog — no action needed.",
    "logs-digest-program":
        "Umbrella card for turning raw logs into a readable digest — "
        "detection and daily reports are already live. It tracks the "
        "remaining lanes; no action needed.",
    "logs-drain-rate":
        "The log shipper reads logs faster than it sends them, so some "
        "hosts fall days behind. Waiting in the backlog — no action "
        "needed yet.",
    "mddb-follower-stall":
        "One memory-database replica quietly stops copying new data "
        "while still looking connected — no errors anywhere. Waiting in "
        "the backlog — no action needed yet.",
    "monitoring-standard":
        "A standing rulebook for how every service reports health, plus "
        "an action-first attention report. The draft is done — check it "
        "and close the card if it looks right.",
    "nest-collective-bench":
        "Exploring whether many small AI models working together beat "
        "one big one. Work is in progress — nothing needed unless a "
        "question appears on the card.",
    "nest-edge-vision":
        "A page that shows a camera feed and draws object labels on it "
        "right in the browser, castable to the TV. Waiting in the "
        "backlog — no action needed.",
    "nest-micro-training":
        "The small-model training loop that already turned a weak model "
        "into a good one needs an owner to keep improving it. Waiting "
        "in the backlog — no action needed.",
    "openclaw-bench-per-model-scorecard-acros-3df00d":
        "Plan to grade each free AI model on speed and whether it calls "
        "tools correctly. Waiting in the backlog — no action needed yet.",
    "ops-kanban-commit-guard":
        "The board's auto-committer stopped itself because the live "
        "checkout has a half-finished merge — it's protecting the repo, "
        "not broken. Read the note and resolve the merge, or close the "
        "card if it's already cleared.",
    "precommit-warning-baseline":
        "The commit-time SSOT check fails on warnings that were already "
        "filed as known debt, which blocks merges. Plan: keep a baseline "
        "and fail only on new warnings. In the backlog — no action "
        "needed.",
    "report-graph-standard":
        "A sweep found the health and report pages don't all follow the "
        "agreed layered format. Standardizing them is in progress — "
        "nothing needed unless a question appears.",
    "report-session-loop":
        "From a report page you should be able to kick off a work "
        "session that tracks itself on a card and keeps the report "
        "updated. Waiting in the backlog — no action needed.",
    "request-lifecycle":
        "Makes sure your requests don't die inside a chat — they get "
        "captured, turned into cards, built, and verified. Waiting in "
        "the backlog — no action needed.",
    "service-onboarding-standard":
        "A checklist for adding new services cleanly was drafted after "
        "recent migrations missed steps. It needs a decision — read the "
        "note and pick a direction.",
    "speaker-profile-tool":
        "KK's voice wasn't being recognized and re-enrolling her looped "
        "for six minutes without finishing. The tool fix is done — check "
        "the result and close the card.",
    "vcast-input-bridge":
        "Keeps the phone-cast feature's remote-control lane healthy so "
        "casts don't fight each other. Queued — a worker session will "
        "pick it up.",
    "vcast-program-design":
        "Tracker card that maps all the TV-casting work and the order "
        "to do it in. For orientation — no action needed.",
    "veo-video-render":
        "Gives Ada the ability to generate short video clips and play "
        "them on screens or send them in chat. Queued — a worker "
        "session will pick it up.",
    "verify-gdrive-offload-tier":
        "The nightly memory-database backup should now keep only the "
        "newest dump locally and push older ones to cloud storage. "
        "After the next 3:30am run, confirm it worked.",
    "yt-dub-liam-e2e":
        "End-to-end test: ask Ada to find a Liam-and-Noel interview "
        "clip, dub it, and play it on the TV. Waiting in the backlog — "
        "no action needed.",
    "yt-voice-dub-cuefit":
        "Polish left over from the voice-dub test — mostly making "
        "dubbed speech fit its time slots. It can't start until related "
        "dub work lands — the blocker is named on the card.",
    "yt-voice-dub-mode":
        "Adds a switch on the cast link so you can pick the dub's voice "
        "style before playing. The work is done — check the result and "
        "close the card.",
    "yt-voice-dub-qc":
        "The dubbing pipeline's worst defects came from bad captions, "
        "not the voices — this adds a caption quality gate first. "
        "Queued — a worker session will pick it up.",
    "yt-voice-dub-scenarios":
        "Adds automated checks so dubbing quality is measured every "
        "run instead of by ear. It can't start until related dub work "
        "lands — the blocker is named on the card.",
    "yt-voice-dub-speakers":
        "Lets the dubbing pipeline handle interviews with more than "
        "two speakers. Queued — a worker session will pick it up.",
}


def first_sentences(text: str, limit: int = 170) -> str:
    flat = " ".join(str(text).split())
    flat = DATELINE_RE.sub("", flat)
    if not flat:
        return ""
    flat = flat[0].upper() + flat[1:]
    parts = SENTENCE_RE.split(flat)
    out = parts[0]
    # a very short first "sentence" is usually a dateline — keep going
    i = 1
    while len(out) < 45 and i < len(parts):
        out += " " + parts[i]
        i += 1
    if len(out) > limit:
        out = out[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out


def open_requests(card: dict) -> list:
    return [r for r in (card.get("requests") or [])
            if r.get("status") != "answered"]


def expected_action(card: dict) -> str:
    col = card.get("column") or "backlog"
    act = card.get("action") or {}
    status = act.get("status") or ""
    blocked = card.get("blocked_by")

    if open_requests(card):
        return "It's waiting on your answer — reply right on the card."
    if card.get("review_kind") == "decide":
        return "It needs a decision — read the note and pick a direction."
    if col == "doing":
        if status in ("running", "queued"):
            return ("A worker session is on it — nothing needed from you "
                    "unless it posts a question.")
        return ("Work is in progress — nothing needed unless a question "
                "appears on the card.")
    if col == "review":
        rk = card.get("review_kind")
        if rk == "decide":
            return "It needs a decision — read the note and pick a direction."
        if rk == "triage":
            return ("Routine sweep finding — glance at it and close it if "
                    "it looks fine.")
        return ("The work is done — check the result and close the card "
                "if it looks right.")
    if col == "lab":
        due = (card.get("lab") or {}).get("review_by")
        tail = f" — the decision is due {due}" if due else ""
        return ("It's an experiment — decide whether to keep it running or "
                f"close it{tail}.")
    # backlog / todo / anything else
    if blocked:
        if CARD_ID_RE.match(str(blocked)):
            return ("It can't start until other work lands — the blocker "
                    "is named on the card.")
        return f"It can't start yet — blocked by {blocked}."
    if status == "running":
        return ("A worker session is on it — nothing needed unless it "
                "posts a question.")
    if act.get("type") == "dispatch":
        if status == "failed":
            return ("The last automated run failed — retry it or read the "
                    "card's comms for why.")
        return "Queued — a worker session will pick it up; no action needed."
    return "Waiting in the backlog — no action needed yet."


def make_brief(card: dict) -> str:
    if card.get("id") in OVERRIDES:
        return OVERRIDES[card["id"]]
    sit = first_sentences(card.get("note") or "") or \
        first_sentences(card.get("title") or "", limit=120)
    sit = sit.rstrip()
    if sit and sit[-1] not in ".!?…":
        sit += "."
    return f"{sit} {expected_action(card)}".strip()


def insert_brief(path: Path, brief: str, force: bool) -> bool:
    lines = path.read_text().splitlines(keepends=True)
    if force:
        lines = [l for l in lines if not l.startswith("brief:")]
    # brief sits in the header block, right before `column:` (required key)
    for i, l in enumerate(lines):
        if l.startswith("column:"):
            lines.insert(i, "brief: " + json.dumps(brief,
                                                   ensure_ascii=False) + "\n")
            path.write_text("".join(lines))
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="rewrite existing single-line briefs")
    ap.add_argument("--glob", default="*.yml")
    args = ap.parse_args()

    done, skipped, failed = 0, 0, []
    for p in sorted(CARD_DIR.glob(args.glob)):
        card = yaml.safe_load(p.read_text()) or {}
        if (card.get("column") or "backlog") == "done":
            skipped += 1
            continue
        if card.get("brief") and not args.force:
            skipped += 1
            continue
        brief = make_brief(card)
        if args.dry_run:
            print(f"{p.name}\n  {brief}\n")
            done += 1
            continue
        if insert_brief(p, brief, args.force):
            done += 1
        else:
            failed.append(p.name)
    print(f"{'would update' if args.dry_run else 'updated'} {done} cards, "
          f"skipped {skipped}", file=sys.stderr)
    for f in failed:
        print(f"NO column: LINE — not touched: {f}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
