#!/usr/bin/env python3
"""eval-budget.py — eval-judge lane client: app-level daily cap + JSONL ledger.

(card gemini-eval-judge-lane, 2026-11-26) Opt-in lane for NEW bulk
eval/judge work. Calls the LiteLLM gateway model `eval-judge` — paid
gemini-3.5-flash-lite primary, then paid-retry -> ollama-llama32-3b-kkmac
-> colab-gemma3; deliberately NO free-tier legs (fail closed). Every call
is checked against an app-level daily request ceiling BEFORE any provider
request and appended to a local JSONL ledger on the caller host.

Ledger: EVAL_JUDGE_STATE_DIR/<YYYY-MM-DD>.jsonl (local date), one JSON
object per call:
  {ts, task, model, provider_call, tokens{prompt,completion,total},
   spend_usd, verdict, status, fallback_hops, latency_ms, text?}

spend_usd is captured when the proxy returns a cost field; otherwise null
— authoritative per-call spend is reconciled from LiteLLM_SpendLogs
(request_tags carry service=eval,job=<task>).

On cap: status "parked", exit 3, and NO provider request is made — no
retry storm, no silent fallback to free models. Pass --card <id> to also
post the parked reason to the board (gate visibility rule).

Env:
  LITELLM_URL              gateway base (default http://100.102.134.91:4000)
  LITELLM_KEY_EVAL_JUDGE   virtual key; falls back to
                           ~/.config/secrets/litellm-keys.env
                           (LITELLM_KEY_EVAL_JUDGE=...). Never falls back
                           to a generic LITELLM_KEY — wrong-budget keys
                           must not silently serve this lane.
  EVAL_JUDGE_MODEL         default "eval-judge"
  EVAL_JUDGE_DAILY_MAX     default 10000 requests/day
                           (~3% of the 350k paid-tier daily quota,
                           GCP project gen-lang-client-0694401188)
  EVAL_JUDGE_STATE_DIR     default ~/.local/state/eval-judge
  EVAL_JUDGE_TAGS          extra x-litellm-tags (service=eval always sent)
  BOARD_API                board-api base for --card comments

CLI:
  eval-budget.py --task slug --prompt "..." [--model m]
                 [--max-tokens n] [--temperature f] [--card id]
  eval-budget.py --status      # {used, max, remaining} for today
  eval-budget.py --selftest
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GW_DEFAULT = "http://100.102.134.91:4000"
KEYS_ENV = Path("~/.config/secrets/litellm-keys.env").expanduser()
MODEL_DEFAULT = "eval-judge"
DAILY_MAX_DEFAULT = 10000
ICT = datetime.timezone(datetime.timedelta(hours=7))

# patch point for tests/selftest — the only network egress in this module
_urlopen = urllib.request.urlopen


def _env_file(path: Path) -> dict:
    env = {}
    try:
        for line in path.read_text().splitlines():
            m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def state_dir() -> Path:
    return Path(os.environ.get(
        "EVAL_JUDGE_STATE_DIR", "~/.local/state/eval-judge")).expanduser()


def daily_max() -> int:
    return int(os.environ.get("EVAL_JUDGE_DAILY_MAX", DAILY_MAX_DEFAULT))


def model_name() -> str:
    return os.environ.get("EVAL_JUDGE_MODEL", MODEL_DEFAULT)


def ledger_file(day: datetime.date | None = None) -> Path:
    day = day or datetime.datetime.now(ICT).date()
    return state_dir() / f"{day.isoformat()}.jsonl"


def resolve() -> tuple[str, str]:
    """(base_url, virtual_key) — env first, litellm-keys.env second."""
    file_env = _env_file(KEYS_ENV)
    url = (os.environ.get("LITELLM_URL")
           or file_env.get("LITELLM_URL") or GW_DEFAULT).rstrip("/")
    key = (os.environ.get("LITELLM_KEY_EVAL_JUDGE")
           or file_env.get("LITELLM_KEY_EVAL_JUDGE") or "")
    return url, key


def _rows_for(path: Path) -> list[dict]:
    rows = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def used_today() -> int:
    """Provider calls already made today (parked refusals don't count)."""
    return sum(1 for r in _rows_for(ledger_file())
               if r.get("provider_call"))


def cap_status() -> dict:
    used = used_today()
    cap = daily_max()
    return {"used": used, "max": cap, "remaining": max(0, cap - used),
            "date": datetime.datetime.now(ICT).date().isoformat()}


def append_row(row: dict) -> None:
    path = ledger_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _extract_cost(d: dict):
    """Best-effort spend from the proxy response; None when absent."""
    for k in ("litellm_response_cost", "response_cost"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    usage = d.get("usage") or {}
    if isinstance(usage.get("cost"), (int, float)):
        return float(usage["cost"])
    return None


def _parse_verdict(text: str | None) -> str | None:
    """First-word verdict for judge-style replies (PASS/FAIL/answer/...);
    None when the reply isn't a bare verdict."""
    if not text:
        return None
    m = re.match(r"^\s*([A-Za-z_-]+)", text)
    if not m:
        return None
    word = m.group(1).lower()
    return word if len(word) <= 24 else None


def _post_board_comment(card: str, text: str) -> str:
    base = os.environ.get(
        "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
    body = json.dumps({"id": card, "from": "devin",
                       "text": text[:900]}).encode()
    req = urllib.request.Request(
        f"{base}/comment", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return "ok" if r.status == 200 else f"http {r.status}"
    except Exception as e:
        return f"failed {type(e).__name__}: {e}"


def chat(messages: list, *, task: str = "adhoc", model: str | None = None,
         temperature: float = 0.0, max_tokens: int = 1024,
         timeout: int = 120, tags: str | None = None,
         park_card: str | None = None,
         post_comment=None) -> dict:
    """One capped, ledgered eval-judge call -> result dict.

    status: ok | provider_error | parked | unconfigured.
    Never retries, never falls back to another lane — the gateway owns
    the (free-leg-free) chain; the app cap owns the daily ceiling.
    """
    post = post_comment or _post_board_comment
    model = model or model_name()
    url, key = resolve()
    base_row = {"ts": datetime.datetime.now(ICT).isoformat(timespec="seconds"),
                "task": task, "model": model}

    if not key:
        row = {**base_row, "provider_call": False, "status": "unconfigured",
               "verdict": None, "tokens": None, "spend_usd": None,
               "detail": "LITELLM_KEY_EVAL_JUDGE unresolved "
                         "(env or litellm-keys.env)"}
        append_row(row)
        return {**row, "ok": False}

    cap = cap_status()
    if cap["used"] >= cap["max"]:
        reason = (f"EVAL_JUDGE_DAILY_MAX={cap['max']} reached "
                  f"({cap['used']} provider calls today {cap['date']}) — "
                  "eval-judge lane parked; no provider request made")
        row = {**base_row, "provider_call": False, "status": "parked",
               "verdict": None, "tokens": None, "spend_usd": None,
               "detail": reason}
        append_row(row)
        note = ""
        if park_card:
            note = post(park_card, f"eval-judge lane PARKED: {reason}")
        return {**row, "ok": False, "parked": True,
                "board_note": note, "cap": cap}

    tag_parts = ["service=eval", f"job={task}", "lane=eval-judge"]
    if tags:
        tag_parts.append(tags)
    data = json.dumps({"model": model, "messages": messages,
                       "temperature": temperature,
                       "max_tokens": max_tokens}).encode()
    headers = {"Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "x-litellm-tags": ",".join(tag_parts)}
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(
            url + "/chat/completions", data=data, headers=headers)
        with _urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
            hdrs = getattr(r, "headers", {}) or {}
            fb = hdrs.get("x-litellm-attempted-fallbacks")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read()[:300].decode("utf-8", "replace")
        except Exception:
            pass
        row = {**base_row, "provider_call": True, "status": "provider_error",
               "http": exc.code, "verdict": None, "tokens": None,
               "spend_usd": None, "fallback_hops": None,
               "latency_ms": int((time.monotonic() - t0) * 1000),
               "detail": detail[:300]}
        append_row(row)
        return {**row, "ok": False}
    except Exception as exc:
        row = {**base_row, "provider_call": True, "status": "provider_error",
               "verdict": None, "tokens": None, "spend_usd": None,
               "fallback_hops": None,
               "latency_ms": int((time.monotonic() - t0) * 1000),
               "detail": f"{type(exc).__name__}: {exc}"[:300]}
        append_row(row)
        return {**row, "ok": False}

    usage = d.get("usage") or {}
    text = ((d.get("choices") or [{}])[0].get("message") or {}
            ).get("content")
    text = text.strip() if isinstance(text, str) else None
    try:
        fb_hops = int(fb) if fb is not None else 0
    except (TypeError, ValueError):
        fb_hops = None
    row = {**base_row, "provider_call": True, "status": "ok",
           "verdict": _parse_verdict(text),
           "tokens": {"prompt": usage.get("prompt_tokens"),
                      "completion": usage.get("completion_tokens"),
                      "total": usage.get("total_tokens")},
           "spend_usd": _extract_cost(d),
           "fallback_hops": fb_hops,
           "served_model": d.get("model"),
           "latency_ms": int((time.monotonic() - t0) * 1000)}
    if text and len(text) <= 1000:
        row["text"] = text
    append_row(row)
    return {**row, "ok": True, "text": text, "cap": cap_status()}


def _selftest() -> int:
    """Offline self-check: cap math + parked path make zero HTTP calls."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        os.environ["EVAL_JUDGE_STATE_DIR"] = td
        os.environ["EVAL_JUDGE_DAILY_MAX"] = "2"
        os.environ["LITELLM_KEY_EVAL_JUDGE"] = "sk-selftest"
        os.environ["LITELLM_URL"] = "http://127.0.0.1:9"

        class _Resp:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": "PASS"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1,
                              "total_tokens": 4},
                    "model": "gemini/gemini-3.5-flash-lite"}).encode()

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            return _Resp()

        global _urlopen
        orig = _urlopen
        _urlopen = fake_urlopen
        try:
            r1 = chat([{"role": "user", "content": "q1"}], task="selftest")
            assert r1["ok"] and r1["status"] == "ok", r1
            assert r1["verdict"] == "pass", r1
            r2 = chat([{"role": "user", "content": "q2"}], task="selftest")
            assert r2["ok"], r2
            # cap=2 -> third call must park with NO provider request
            r3 = chat([{"role": "user", "content": "q3"}], task="selftest")
            assert r3.get("parked") and r3["status"] == "parked", r3
            assert len(calls) == 2, f"provider calls={len(calls)} != 2"
            st = cap_status()
            assert st["used"] == 2 and st["max"] == 2, st
        finally:
            _urlopen = orig
    print("selftest OK (cap+ledger+park, 2 provider calls, 3rd parked)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default="adhoc",
                    help="task slug recorded in the ledger + spend tags")
    ap.add_argument("--prompt", help="single user-message prompt")
    ap.add_argument("--messages-file", type=Path,
                    help="JSON list of chat messages (overrides --prompt)")
    ap.add_argument("--model", help="override EVAL_JUDGE_MODEL")
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--tags", help="extra x-litellm-tags")
    ap.add_argument("--card", help="board card id to notify when parked")
    ap.add_argument("--status", action="store_true",
                    help="print today's cap usage and exit")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if args.status:
        print(json.dumps(cap_status(), indent=2))
        return 0

    if args.messages_file:
        messages = json.loads(args.messages_file.read_text())
    elif args.prompt is not None:
        messages = [{"role": "user", "content": args.prompt}]
    else:
        ap.error("need --prompt or --messages-file")

    res = chat(messages, task=args.task, model=args.model,
               temperature=args.temperature, max_tokens=args.max_tokens,
               timeout=args.timeout, tags=args.tags, park_card=args.card)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    if res.get("parked"):
        return 3
    return 0 if res.get("ok") else 4


if __name__ == "__main__":
    sys.exit(main())
