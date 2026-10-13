#!/usr/bin/env python3
"""gemini-wallet-watch — early warning for the Gemini prepaid wallet.

Probes the PAID key once per run with a ~1-token generateContent call
(negligible cost) and watches the state transition:

    ok -> credit  : notify every household lane via the LINE relay /send
                    (tony DM + kk group) so an empty wallet is known
                    BEFORE a voice session dies on it.
    credit -> ok  : one recovery note so the lanes know they're whole.

429/demand verdicts are logged but do NOT alert — they are per-key
throttling/congestion, not an empty wallet (2026-10-12 incident: the
402 '1011 prepayment credits depleted' is the only true empty-wallet
signal).

    state:   ~/.local/share/ada/gemini-wallet-watch.json
    journal: one INFO line per run (journald)

Usage:
  gemini-wallet-watch.py --env-file ~/.config/secrets/gemini-keys.env
                         [--relay-url http://127.0.0.1:8912/send]
                         [--model gemini-3.5-flash-lite]
"""
from __future__ import annotations

import argparse
import datetime
import json
import urllib.request
from pathlib import Path

MODEL = "gemini-3.5-flash-lite"
STATE = Path.home() / ".local/share/ada/gemini-wallet-watch.json"
RELAY = "http://127.0.0.1:8912/send"

DEPLETED_EN = ("⚠️ Gemini prepaid depleted — paid wallet empty. Voice "
               "lanes are running on the free tier until you top up "
               "(ai.studio → project billing). Scenario suite stays "
               "parked either way.")
DEPLETED_TH = ("แจ้งเตือนค่ะ — เครดิต Gemini เติมเงินหมดแล้ว "
               "ระบบเสียงใช้เฟรีเทียร์ชั่วคราว รอคุณโทนี่เติมเงินนะคะ")
RECOVERED = ("✅ Gemini prepaid credit is back — paid lane healthy "
             "again.")


def _env_key(path: str, var: str) -> str:
    for line in Path(path).expanduser().read_text().splitlines():
        if line.startswith(var + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _verdict(status: int, body: str) -> str:
    if status == 200:
        return "ok"
    if status == 402 or "1011" in body or "depleted" in body.lower():
        return "credit"
    if status == 429 or "RESOURCE_EXHAUSTED" in body:
        return "quota"
    if status == 503 or "high demand" in body.lower():
        return "demand"
    if status in (401, 403):
        return "auth"
    return "other"


def probe(key: str, model: str) -> dict:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    body = json.dumps({
        "contents": [{"parts": [{"text": "hi"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json",
                                 "x-goog-api-key": key})
    try:
        r = urllib.request.urlopen(req, timeout=20)
        return {"verdict": "ok"}
    except urllib.error.HTTPError as e:
        payload = e.read()[:400].decode(errors="replace")
        return {"verdict": _verdict(e.code, payload),
                "detail": payload[:160]}
    except Exception as e:
        return {"verdict": "other", "detail": f"{type(e).__name__}: {e}"[:160]}


def notify(relay: str, targets: list[dict]) -> list[str]:
    out = []
    for t in targets:
        req = urllib.request.Request(
            relay, data=json.dumps(t).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.load(r)
            out.append(f"{t.get('to') or t.get('instance')}: "
                       f"{'ok' if res.get('ok') else res}")
        except Exception as e:
            out.append(f"{t.get('to') or t.get('instance')}: "
                       f"FAILED {type(e).__name__}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--key-var", default="GEMINI_API_KEY_PAID")
    ap.add_argument("--relay-url", default=RELAY)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--state", type=Path, default=STATE)
    ap.add_argument("--dry-run", action="store_true",
                    help="probe + report but do not notify or write state")
    args = ap.parse_args()

    key = _env_key(args.env_file, args.key_var)
    rec = probe(key, args.model) if key else {"verdict": "no-key"}
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    prev = {}
    if args.state.exists():
        try:
            prev = json.loads(args.state.read_text())
        except Exception:
            prev = {}
    prev_status = prev.get("status", "ok")
    cur = rec["verdict"]
    notes = []

    depleted_now = cur == "credit"
    was_depleted = prev_status == "credit"
    if not args.dry_run:
        if depleted_now and not was_depleted:
            notes = notify(args.relay_url, [
                {"to": "tony", "instance": "tony", "text": DEPLETED_EN},
                {"instance": "kk", "text": DEPLETED_TH},
            ])
        elif was_depleted and cur == "ok":
            notes = notify(args.relay_url, [
                {"to": "tony", "instance": "tony", "text": RECOVERED},
                {"instance": "kk", "text": RECOVERED},
            ])
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps({
            "status": cur, "at": ts,
            "key_suffix": key[-4:] if key else "",
            "detail": rec.get("detail", "")[:160],
        }) + "\n")
    print(f"gemini-wallet-watch: {cur} (was {prev_status}) "
          f"key=...{key[-4:] if key else 'none'} "
          f"{rec.get('detail','')} {' '.join(notes)}")
    # exit 1 while depleted so the unit's Result reflects the wallet —
    # one timer-alert card, resolved by the auto-close on recovery.
    return 1 if depleted_now else 0


if __name__ == "__main__":
    raise SystemExit(main())
