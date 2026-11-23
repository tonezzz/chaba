#!/usr/bin/env python3
"""Arbiter label pass — dispatch-triage corpus
(card dispatch-triage-arbiter-label-pass, strategy (b) approved by Tony).

Iterates kanban card request texts (docs/ssot/kanban/cards/**/*.yml —
title, or title+brief head when the title alone is too short), verdicts
each into {code, docs, ops, research, clarify} — the ada-voice
tests/bench/domains.yml `triage` Choice surface — via the LiteLLM gateway
free-lane deployment (default `gemini-3.5-flash-lite-free`, which has NO
paid fallback leg, so the pass cannot spend money).

Outputs (all under this directory):

  ledger.jsonl                  every successful verdict, keyed by text
                                hash — the idempotency store; re-runs
                                skip already-verdicted texts
  labeled-corpus-<date>.jsonl   {text, source, label, confidence, model,
                                ts} — re-derived from the ledger
  review-queue-<date>.jsonl     low-confidence rows + stratified
                                spot-check sample (~--review-target rows)
                                — the ~100-row human check that doubles
                                as the golden-seed sample
  suite-append-<date>.jsonl     above-threshold rows in suite schema
                                {text, kind:triage, label, set:triage,
                                slice:harvest-<date>} for ada-voice
                                tests/bench/orch-triage-cases.jsonl —
                                APPEND HELD pending Tony's spot-check
                                (board answer 2026-11-21: check first,
                                then append). Apply with append-suite.py.

Texts identical to rows already in orch-triage-cases.jsonl are excluded
(hand-labeled ground truth — never re-labeled).

Credentials: LITELLM_URL + LITELLM_KEY env, else
~/.config/secrets/litellm-chaba.env (chaba virtual key — free-lane
allowlisted). Only model ids ending in "-free" or starting with
"or-free-"/"cf-"/"ollama" are accepted — hard free-lane guard.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CARDS = sorted(REPO.glob("docs/ssot/kanban/cards/*.yml")) + \
    sorted(REPO.glob("docs/ssot/kanban/cards/archive/*.yml"))
DEFAULT_CASES = os.path.expanduser(
    "~/CascadeProjects/ada-voice/tests/bench/orch-triage-cases.jsonl")
LEDGER = HERE / "ledger.jsonl"
DEFAULT_ENV = os.path.expanduser("~/.config/secrets/litellm-chaba.env")

MODEL = "gemini-3.5-flash-lite-free"
# hard free-lane allowlist — no paid upstream may ever be substituted
FREE_MODEL_RE = re.compile(r"(-free$|^or-free-|^cf-|^ollama|^chat-local$)")
LABELS = ("code", "docs", "ops", "research", "clarify")

CRITERIA = {
    "code": "change code in a repo — fix a bug, build a feature, refactor, "
            "add tests",
    "docs": "write or update documentation — SSOT entries, runbooks, "
            "kanban cards, reports",
    "ops": "operate the infrastructure — deploy, restart, check health, "
           "triage failed units, rotate secrets",
    "research": "investigate and report — answer a question, compare "
                "options, read logs, no file changes wanted",
    "clarify": "ambiguous or missing key information — park it and ask "
               "the operator before doing anything",
}

PROMPT_HEAD = (
    "You are labeling requests sent to a home-infrastructure task "
    "dispatcher. For each request pick the single best work lane:\n\n"
    + "\n".join(f"- {k}: {v}" for k, v in CRITERIA.items())
    + "\n\nRequests:\n")

PROMPT_TAIL = (
    "\nReply with ONE JSON array only — one object per request, in "
    "order, no prose:\n"
    '[{"i":1,"label":"ops","confidence":0.95}, ...]\n'
    "confidence is 0.0-1.0 — your honest certainty that this lane fits. "
    "Score below 0.7 whenever two lanes genuinely compete or the request "
    "is underspecified.")


def norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())


def thash(t: str) -> str:
    return hashlib.sha1(norm_text(t).encode()).hexdigest()[:16]


def load_env_file(path: str) -> dict:
    env = {}
    try:
        for ln in open(os.path.expanduser(path)):
            m = re.match(r"^([A-Z_]+)=(.*)$", ln.strip())
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def creds(env_file: str) -> tuple[str, str]:
    url = os.environ.get("LITELLM_URL", "")
    key = os.environ.get("LITELLM_KEY", "")
    if not (url and key):
        env = load_env_file(env_file)
        url = url or env.get("LITELLM_URL", "")
        key = key or env.get("LITELLM_KEY", "")
    url = url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url, key


def card_text(d: dict) -> str:
    t = (d.get("title") or "").strip()
    if len(t) >= 20:
        return t
    b = re.sub(r"\s+", " ", (d.get("brief") or "").strip())
    txt = (t + " — " + b[:200]).strip(" —") if (t or b) else ""
    return txt if len(txt) >= 20 else ""


def collect_texts(exclude: set[str]) -> list[dict]:
    rows, seen = [], set()
    for f in CARDS:
        try:
            d = yaml.safe_load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        txt = card_text(d)
        if not txt:
            continue
        h = norm_text(txt)
        if h in seen or h in exclude:
            continue
        seen.add(h)
        rows.append({"text": txt, "source": d.get("id") or f.stem})
    return rows


def load_ledger() -> dict:
    out = {}
    if LEDGER.exists():
        for ln in open(LEDGER):
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("label") in LABELS:
                out[r["h"]] = r
    return out


def ground_truth_texts(cases_file: str) -> set[str]:
    out = set()
    try:
        for ln in open(cases_file):
            try:
                out.add(norm_text(json.loads(ln)["text"]))
            except Exception:
                pass
    except OSError:
        pass
    return out


def chat(base: str, key: str, model: str, messages: list,
         timeout: int = 90, retries: int = 3,
         max_tokens: int = 1024) -> tuple[str | None, str | None]:
    body = {"model": model, "messages": messages,
            "temperature": 0, "max_tokens": max_tokens}
    err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                base + "/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                    "X-litellm-tags": "service=chaba,"
                                      "job=dispatch-triage-label",
                })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            msg = (d.get("choices") or [{}])[0].get("message") or {}
            return msg.get("content") or "", None
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read()[:300].decode("utf-8", "replace")
            except Exception:
                pass
            err = f"HTTP {e.code} {detail[:120]}"
            if e.code not in (408, 409, 429, 500, 502, 503, 504):
                break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        wait = min(90, 8 * (2 ** attempt))
        print(f"  retry {attempt + 1}/{retries} after {err} "
              f"(sleep {wait}s)", file=sys.stderr)
        time.sleep(wait)
    return None, err


def parse_verdicts(raw: str, n: int) -> list[dict] | None:
    """Extract a JSON array of {i,label,confidence} verdicts."""
    s = raw.strip()
    s = re.sub(r"^```(json)?|```$", "", s, flags=re.M).strip()
    m = re.search(r"\[.*\]", s, re.S)
    if not m:
        # accept {"verdicts":[...]} wrapper
        m2 = re.search(r"\{.*\}", s, re.S)
        if m2:
            try:
                obj = json.loads(m2.group(0))
                arr = obj.get("verdicts") or obj.get("results")
                if isinstance(arr, list):
                    return _fix(arr, n)
            except Exception:
                pass
        return None
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return _fix(arr, n)


def _fix(arr: list, n: int) -> list[dict] | None:
    if not isinstance(arr, list) or not arr:
        return None
    by_i = {}
    for j, v in enumerate(arr):
        if not isinstance(v, dict):
            return None
        i = v.get("i", j + 1)
        lab = str(v.get("label", "")).strip().lower()
        try:
            conf = float(v.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        if lab not in LABELS:
            return None
        by_i[int(i)] = {"label": lab, "confidence": max(0.0, min(1.0, conf))}
    if len(by_i) < n:
        return None
    return [by_i.get(i + 1) for i in range(n)]


def label_batch(base, key, model, batch) -> list[dict | None]:
    """One chat call for a batch of {text,...} -> [{label,confidence}|None]."""
    listing = "\n".join(f"{i + 1}. {r['text'][:400]}"
                        for i, r in enumerate(batch))
    raw, err = chat(base, key, model,
                    [{"role": "user",
                      "content": PROMPT_HEAD + listing + PROMPT_TAIL}])
    if raw:
        vs = parse_verdicts(raw, len(batch))
        if vs and all(vs):
            return vs
    # per-row fallback — a batch that fails wholesale must not lose rows
    out = []
    for r in batch:
        raw, err2 = chat(base, key, model,
                         [{"role": "user",
                           "content": PROMPT_HEAD + "1. "
                           + r["text"][:400] + PROMPT_TAIL}],
                         max_tokens=200)
        vs = parse_verdicts(raw, 1) if raw else None
        out.append(vs[0] if vs else None)
    return out


def derive(ledger: dict, threshold: float, review_target: int,
           date_str: str) -> dict:
    """Re-derive all output files from the ledger. Returns counts."""
    rows = sorted(ledger.values(), key=lambda r: r["h"])
    corpus = HERE / f"labeled-corpus-{date_str}.jsonl"
    suite = HERE / f"suite-append-{date_str}.jsonl"
    review = HERE / f"review-queue-{date_str}.jsonl"

    by_label = {}
    for r in rows:
        by_label.setdefault(r["label"], []).append(r)

    low = [r for r in rows if r["confidence"] < threshold]
    high = [r for r in rows if r["confidence"] >= threshold]

    # deterministic stratified spot-check: stable hash order per class,
    # proportional share of the remaining review budget
    remaining = max(0, review_target - len(low))
    spot = []
    classes = sorted(by_label.items())
    total = sum(len(v) for _, v in classes) or 1
    handed = 0
    for idx, (lab, rs) in enumerate(classes):
        pool = sorted((r for r in rs if r["confidence"] >= threshold),
                      key=lambda r: r["h"])
        share = remaining - handed if idx == len(classes) - 1 else min(
            len(pool), math.ceil(remaining * len(rs) / total))
        spot.extend(pool[:max(0, share)])
        handed += share

    review_h = {r["h"] for r in low} | {r["h"] for r in spot}
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with open(corpus, "w") as f:
        for r in rows:
            f.write(json.dumps({
                "text": r["text"], "source": r["source"],
                "label": r["label"], "confidence": r["confidence"],
                "model": r["model"], "ts": r["ts"]}) + "\n")
    with open(review, "w") as f:
        for r in low:
            f.write(json.dumps({
                "text": r["text"], "source": r["source"],
                "label": r["label"], "confidence": r["confidence"],
                "reason": "low_confidence", "ts": ts}) + "\n")
        for r in spot:
            f.write(json.dumps({
                "text": r["text"], "source": r["source"],
                "label": r["label"], "confidence": r["confidence"],
                "reason": "spot_check", "ts": ts}) + "\n")
    with open(suite, "w") as f:
        for r in rows:
            if r["h"] in review_h:
                continue  # held for human check — not auto-appended
            f.write(json.dumps({
                "text": r["text"], "kind": "triage", "label": r["label"],
                "set": "triage", "slice": f"harvest-{date_str}"}) + "\n")

    return {"corpus": len(rows), "review": len(low) + len(spot),
            "low_conf": len(low), "spot": len(spot),
            "suite_append": len(rows) - len(review_h),
            "by_label": {k: len(v) for k, v in sorted(by_label.items())},
            "conf_mean": round(sum(r["confidence"] for r in rows)
                               / max(1, len(rows)), 3),
            "files": {k: str(v.name) for k, v in
                      (("corpus", corpus), ("review", review),
                       ("suite_append", suite))}}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--env-file", default=DEFAULT_ENV)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0,
                    help="cap pending texts (smoke tests)")
    ap.add_argument("--threshold", type=float, default=0.7,
                    help="confidence floor — below goes to review queue")
    ap.add_argument("--review-target", type=int, default=100,
                    help="total review-queue size (low-conf + spot-check)")
    ap.add_argument("--cases-file", default=DEFAULT_CASES,
                    help="ground-truth suite cases to exclude")
    ap.add_argument("--date", default=None)
    ap.add_argument("--derive-only", action="store_true",
                    help="skip model calls; rebuild outputs from ledger")
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    if not FREE_MODEL_RE.search(args.model):
        sys.exit(f"refusing non-free model {args.model!r} — "
                 f"arbiter pass must spend $0")

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    ledger = load_ledger()
    rows = collect_texts(ground_truth_texts(args.cases_file))
    pending = [r for r in rows if thash(r["text"]) not in ledger]
    if args.limit:
        pending = pending[:args.limit]
    print(f"corpus={len(rows)} ledgered={len(ledger)} "
          f"pending={len(pending)}", file=sys.stderr)

    if pending and not args.derive_only:
        base, key = creds(args.env_file)
        if not (base and key):
            sys.exit("LITELLM_URL/LITELLM_KEY unresolved "
                     f"(env or {args.env_file})")
        t0, done, failed = time.time(), 0, 0
        lf = open(LEDGER, "a")
        for off in range(0, len(pending), args.batch_size):
            batch = pending[off:off + args.batch_size]
            vs = label_batch(base, key, args.model, batch)
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for r, v in zip(batch, vs):
                if v is None:
                    failed += 1
                    continue
                rec = {"h": thash(r["text"]), "text": r["text"],
                       "source": r["source"], "label": v["label"],
                       "confidence": v["confidence"],
                       "model": args.model, "ts": ts}
                lf.write(json.dumps(rec) + "\n")
                ledger[rec["h"]] = rec
                done += 1
            lf.flush()
            el = time.time() - t0
            rate = done / max(el, 0.01) * 60
            eta = (len(pending) - off - len(batch)) / max(rate / 60, 0.01)
            print(f"  {off + len(batch)}/{len(pending)} "
                  f"({rate:.0f}/min, eta {eta / 60:.1f}m, "
                  f"failed {failed})", file=sys.stderr)
            time.sleep(args.delay)
        lf.close()
        print(f"pass done: {done} labeled, {failed} unverdicted, "
              f"{time.time() - t0:.0f}s", file=sys.stderr)

    stats = derive(ledger, args.threshold, args.review_target, date_str)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
