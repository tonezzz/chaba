#!/usr/bin/env python3
"""gemini-wallet-watch — early warning for depleted/capped Gemini keys.

Probes each configured key once per run with a ~1-token generateContent
call (negligible cost) and watches the per-key state transition:

    ok -> credit  : notify — tony DM (EN) for every key; kk group (TH)
                    only when the kk lane's own key is down — so an
                    empty wallet / capped project is known BEFORE a
                    voice session dies on it.
    credit -> ok  : one recovery note so the lanes know they're whole.

429/demand verdicts are logged but do NOT alert — they are per-key
throttling/congestion, not an empty wallet (2026-10-12 incident: the
402 '1011 prepayment credits depleted' is the only true empty-wallet
signal; the 2026-10-14 ada-ha-tony incident was the same 1011 surfacing
as a project spend cap on GEMINI_API_KEY_TONY — which is why the probe
list now covers every paid lane key, not just the shared PAID wallet).

    state:   ~/.local/share/ada/gemini-wallet-watch.json
    journal: one INFO line per key per run (journald)

Usage:
  gemini-wallet-watch.py --env-file ~/.config/secrets/gemini-keys.env
                         [--key-var GEMINI_API_KEY_PAID]...   (repeatable)
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

# Which voice lanes die when a given key stops working. Used in alert
# text so "key down" reads as "this lane is down" — the 1011 incident
# showed a bare var name means nothing at 2am.
LANE_LABELS = {
    "GEMINI_API_KEY_PAID": "mddb/infra shared paid wallet",
    "GEMINI_API_KEY_TONY": "ada-ha-tony + ada-pi-pwa",
    "GEMINI_API_KEY_KK": "ada-kk",
    "GEMINI_API_KEY_MICHAEL": "ada-ha-michael",
    "GEMINI_API_KEY_FREE": "dev lanes (free tier)",
}

# Lanes whose group should hear about their own key dying (Thai).
KK_LANE_VARS = {"GEMINI_API_KEY_KK"}


def _depleted_en(var: str) -> str:
    lane = LANE_LABELS.get(var, "unknown lane")
    return (f"⚠️ Gemini key refusing calls — {var} ({lane}) is "
            "depleted/capped. That lane is down until topped up "
            "(ai.studio → project billing). Scenario suite stays "
            "parked either way.")


def _depleted_th(var: str) -> str:
    lane = LANE_LABELS.get(var, var)
    return (f"แจ้งเตือนค่ะ — คีย์ Gemini ของ {lane} หมดเครดิตแล้ว "
            "เลนเสียงใช้ไม่ได้จนกว่าจะเติมเงินนะคะ")


def _recovered_en(var: str) -> str:
    lane = LANE_LABELS.get(var, "unknown lane")
    return f"✅ Gemini credit is back — {var} ({lane}) healthy again."


_RECOVERED_TH = ("✅ เครดิต Gemini กลับมาแล้วค่ะ "
                 "เลนเสียงใช้งานได้ตามปกติ")


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


def _load_state(path: Path) -> dict:
    """Return per-key state; migrate the legacy single-key format
    ({status: ...}) — it always tracked GEMINI_API_KEY_PAID."""
    try:
        raw = json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        raw = {}
    if "keys" in raw and isinstance(raw["keys"], dict):
        return raw
    keys = {}
    if raw.get("status"):
        keys["GEMINI_API_KEY_PAID"] = raw
    return {"keys": keys}


def _alert_targets(var: str, depleted: bool) -> list[dict]:
    text_en = _depleted_en(var) if depleted else _recovered_en(var)
    targets = [{"to": "tony", "instance": "tony", "text": text_en}]
    if var in KK_LANE_VARS:
        targets.append({"instance": "kk", "text":
                        _depleted_th(var) if depleted else _RECOVERED_TH})
    return targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--key-var", action="append", default=None,
                    help="env var to probe; repeatable. "
                         "Default: GEMINI_API_KEY_PAID")
    ap.add_argument("--relay-url", default=RELAY)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--state", type=Path, default=STATE)
    ap.add_argument("--dry-run", action="store_true",
                    help="probe + report but do not notify or write state")
    args = ap.parse_args()

    key_vars = args.key_var or ["GEMINI_API_KEY_PAID"]
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    state = _load_state(args.state)
    prev_keys = state.get("keys", {})
    new_keys = {}
    any_depleted = False

    for var in key_vars:
        key = _env_key(args.env_file, var)
        rec = probe(key, args.model) if key else {"verdict": "no-key"}
        prev_status = prev_keys.get(var, {}).get("status", "ok")
        cur = rec["verdict"]
        notes = []

        depleted_now = cur == "credit"
        any_depleted = any_depleted or depleted_now
        was_depleted = prev_status == "credit"
        if not args.dry_run:
            if depleted_now and not was_depleted:
                notes = notify(args.relay_url, _alert_targets(var, True))
            elif was_depleted and cur == "ok":
                notes = notify(args.relay_url, _alert_targets(var, False))
        new_keys[var] = {
            "status": cur, "at": ts,
            "key_suffix": key[-4:] if key else "",
            "detail": rec.get("detail", "")[:160],
        }
        print(f"gemini-wallet-watch: {var}={cur} (was {prev_status}) "
              f"key=...{key[-4:] if key else 'none'} "
              f"{rec.get('detail','')} {' '.join(notes)}")

    if not args.dry_run:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps({"keys": new_keys}) + "\n")
    # exit 1 while ANY key is depleted so the unit's Result reflects the
    # worst lane — one timer-alert card, resolved on full recovery.
    return 1 if any_depleted else 0


if __name__ == "__main__":
    raise SystemExit(main())
