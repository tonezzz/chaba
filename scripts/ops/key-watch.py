#!/usr/bin/env python3
"""key-watch — credential expiry/quota monitor (card key-watch-monitor,
SEC-0499).

Born 2026-10-12: the OR bridge key hit limit_remaining=$0 with ZERO
warning — inference 403s fleet-wide until a manual sweep noticed. This
is the always-on check for that class of failure.

Sources (metadata only — secret VALUES never leave their host; each
slot is probed by a python3 payload shipped over ssh that returns only
masked fingerprints + verdict metadata):

  openrouter  GET https://openrouter.ai/api/v1/auth/key per declared
              slot -> label, expires_at, usage, limit, limit_remaining
  ha-token    GET <instance>/api/ per stored HOME_ASSISTANT_TOKEN /
              HASS_TOKEN / HA_LONG_LIVED_TOKEN -> 401/403 = dead
  cf-token    GET /client/v4/user/tokens/verify; falls back to
              /zones?per_page=1 — the cfat_ token is rejected by
              /verify but holds Zone DNS r/w (ssot.secrets.yml note)
  gemini-ops  MDDB ada-ha-events-{kk,tony,michael} kind=ops-event scan
              for quota markers in the lookback window (the same feed
              gemini_pool's circuit breaker writes QuotaExhausted into);
              --gemini-probe adds a ~1-token generateContent per key var

Thresholds: expires_at <48h or usage/limit >=80% -> warn (LINE);
dead/expired/limit_remaining=0 -> alert (LINE + incident card via
board-api). Quiet hours 00:00-07:00 ICT defer the LINE push only —
ops-event docs and incident cards are still written (they are the
durable record; the push lands on the next non-quiet tick).

Output: one kind=ops-event doc per run in ada-ha-events-tony
(type: key_watch) — the same feed shape as gemini_pool emit_ops_event /
host-loads _ops_event. Findings also mirror into the state file so a
recovered source auto-closes its incident card.

Cadence: key-watch.timer (6h + OnBootSec) — install on idc03 (canonical
writer host; card said tony-dell but dell is powered off since
2026-10-20 migration ph6). Unit is host-agnostic (%h paths).

Usage:
  key-watch.py                 # full run: probes + LINE + cards + ops-event
  key-watch.py --dry-run       # probe + print, no LINE/card/ops writes
  key-watch.py --selftest      # synthetic fixture through the judge path
  key-watch.py --hosts idc03,tony-omen   # limit probe hosts
  key-watch.py --gemini-probe  # also run the light generate probe

Env: MDDB_BASE_URL, BOARD_API, KEY_WATCH_STATE, KEY_WATCH_RELAY_URL,
     KEY_WATCH_RELAY_SSH, KEY_WATCH_QUIET (e.g. "0-7"), KEY_WATCH_LOOKBACK_H,
     KEY_WATCH_EXPIRY_WARN_H, KEY_WATCH_QUOTA_WARN_PCT, KEY_WATCH_RESEND_MIN,
     KEY_WATCH_SSH_TIMEOUT, GEMINI_KEYS_FILE, GEMINI_KEY_VARS, GEMINI_MODEL.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ICT = datetime.timezone(datetime.timedelta(hours=7))

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")
OPS_COLLECTION = "ada-ha-events-tony"
GEMINI_OPS_COLLECTIONS = [
    "ada-ha-events-kk", "ada-ha-events-tony", "ada-ha-events-michael"]

STATE = Path(os.environ.get(
    "KEY_WATCH_STATE", "~/.local/state/key-watch.json")).expanduser()
RELAY_URL = os.environ.get("KEY_WATCH_RELAY_URL", "http://127.0.0.1:8912/send")
RELAY_SSH = os.environ.get("KEY_WATCH_RELAY_SSH", "idc03")
SSH_TIMEOUT = int(os.environ.get("KEY_WATCH_SSH_TIMEOUT", "120"))
QUIET = tuple(int(x) for x in
              os.environ.get("KEY_WATCH_QUIET", "0-7").split("-", 1))
EXPIRY_WARN_H = float(os.environ.get("KEY_WATCH_EXPIRY_WARN_H", "48"))
QUOTA_WARN_PCT = float(os.environ.get("KEY_WATCH_QUOTA_WARN_PCT", "80"))
RESEND_MIN = int(os.environ.get("KEY_WATCH_RESEND_MIN", "240"))
LOOKBACK_H = float(os.environ.get("KEY_WATCH_LOOKBACK_H", "24"))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# ops-event markers that mean "a Gemini lane hit the wall" — the type
# names gemini_pool/realtime_provider emit plus content signatures seen
# in the 2026-10-12/14 incidents.
QUOTA_TYPES = re.compile(
    r"quota|resource_exhausted|circuit|breaker|degraded", re.I)
QUOTA_TEXT = re.compile(
    r"quota_exhausted|RESOURCE_EXHAUSTED|credits depleted|\b1011\b|"
    r"daily.?quota", re.I)

# --- watchlist ---------------------------------------------------------------
# Declared from docs/ssot/infrastructure/ssot.secrets.yml slots —
# {host, file, var} are metadata pointers only; the probe reads the value
# on that host and reports back fingerprint+verdict, never the secret.
WATCHLIST = [
    # openrouter-ada-safety — the fleet key lives in 3 env slots +
    # openclaw sqlite (sqlite slot not probed — var-less store).
    {"id": "or-tony-dell", "kind": "openrouter", "host": "tony-dell",
     "file": "~/.config/secrets/openrouter.env", "var": "OPENROUTER_API_KEY"},
    {"id": "or-tony-omen", "kind": "openrouter", "host": "tony-omen",
     "file": "~/.config/secrets/openrouter.env", "var": "OPENROUTER_API_KEY"},
    {"id": "or-idc03", "kind": "openrouter", "host": "idc03",
     "file": "~/.config/secrets/mddb-gemini.env", "var": "OPENROUTER_API_KEY"},
    # HA long-lived tokens -> their instance's GET /api/.
    {"id": "ha-tony-ops-omen", "kind": "ha", "host": "tony-omen",
     "file": "~/.config/secrets/home-assistant-token.env",
     "var": "HA_LONG_LIVED_TOKEN",
     "url": "http://127.0.0.1:8123"},          # tony-ha runs on omen
    {"id": "ha-tony-ops-dell", "kind": "ha", "host": "tony-dell",
     "file": "~/.config/secrets/home-assistant-token.env",
     "var": "HA_LONG_LIVED_TOKEN",
     "url": "https://tony-omen.taila0626a.ts.net:8123"},
    {"id": "ha-tony-nodered", "kind": "ha", "host": "tony-dell",
     "file": "~/.config/secrets/nodered-ha.env", "var": "HASS_TOKEN",
     "url": "https://tony-omen.taila0626a.ts.net:8123"},
    {"id": "ha-ada-omen", "kind": "ha", "host": "tony-omen",
     "file": "~/.config/secrets/ada-ha-token.env",
     "var": "HA_LONG_LIVED_TOKEN",
     "url": "http://127.0.0.1:8125"},          # ada-ha instance on omen
    {"id": "ha-tony-ada-mn01", "kind": "ha", "host": "mn01",
     "file": "~/.config/secrets/ada-ha-tony.env",
     "var": "HOME_ASSISTANT_TOKEN",
     "url": "https://tony-omen.taila0626a.ts.net:8123"},
    {"id": "ha-michael-mn01", "kind": "ha", "host": "mn01",
     "file": "~/.config/secrets/ada-ha-michael.env",
     "var": "HOME_ASSISTANT_TOKEN",
     "url": "http://michael-ha.taila0626a.ts.net:8123"},  # michael-ha is its own tailnet host
    {"id": "ha-mdev-dell", "kind": "ha", "host": "tony-dell",
     "file": "~/.config/secrets/ha-michael-dev.env", "var": "HASS_TOKEN",
     "url": "https://idc03.taila0626a.ts.net:8124"},
    {"id": "ha-mdev-omen", "kind": "ha", "host": "tony-omen",
     "file": "~/.config/secrets/ha-michael-dev.env", "var": "HASS_TOKEN",
     "url": "https://idc03.taila0626a.ts.net:8124"},
    {"id": "ha-mlive-dell", "kind": "ha", "host": "tony-dell",
     "file": "~/.config/secrets/ha-michael-live.env", "var": "HASS_TOKEN",
     "url": "http://michael-ha.taila0626a.ts.net:8123"},
    {"id": "ha-mlive-omen", "kind": "ha", "host": "tony-omen",
     "file": "~/.config/secrets/ha-michael-live.env", "var": "HASS_TOKEN",
     "url": "http://michael-ha.taila0626a.ts.net:8123"},
    # cloudflare — cfat_ (idc*, DNS-capable) + cfut_ (dell/omen, workers).
    {"id": "cf-idc01", "kind": "cf", "host": "idc01",
     "file": "~/.config/secrets/cloudflare.env", "var": "CF_API_TOKEN"},
    {"id": "cf-idc02", "kind": "cf", "host": "idc02",
     "file": "~/.config/secrets/cloudflare.env", "var": "CF_API_TOKEN"},
    {"id": "cf-idc03", "kind": "cf", "host": "idc03",
     "file": "~/.config/secrets/cloudflare.env", "var": "CF_API_TOKEN"},
    {"id": "cf-tony-omen", "kind": "cf", "host": "tony-omen",
     "file": "~/.config/secrets/cloudflare.env", "var": "CF_API_TOKEN"},
    {"id": "cf-tony-dell", "kind": "cf", "host": "tony-dell",
     "file": "~/.config/secrets/cloudflare.env", "var": "CF_API_TOKEN"},
]

# Optional light Gemini generate probe — idc03's gemini-keys.env is the
# source of truth for the paid lane keys (gemini-wallet-watch watches
# these hourly; key-watch adds the 6h belt only when asked).
GEMINI_KEYS_FILE = os.environ.get(
    "GEMINI_KEYS_FILE", "~/.config/secrets/gemini-keys.env")
GEMINI_KEY_VARS = os.environ.get(
    "GEMINI_KEY_VARS",
    "GEMINI_API_KEY_PAID GEMINI_API_KEY_TONY GEMINI_API_KEY_KK "
    "GEMINI_API_KEY_MICHAEL").split()
GEMINI_HOST = "idc03"

# --- on-host probe -----------------------------------------------------------
# One python3 payload per host, shipped over ssh stdin. Reads each
# declared env var locally, calls the kind's verify endpoint, prints a
# JSON dict {slot_id: {status, masked, fp, detail}} — secret values are
# NEVER emitted; masked is <first6>…<last4>, fp is sha256[:8].
PROBE_HEAD = r'''
import json, os, re, sys, hashlib, urllib.request, urllib.error
def _env_var(path, var):
    try:
        for line in open(os.path.expanduser(path), errors="replace"):
            s = line.strip()
            if s.startswith(var + "="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
        # bare-token file fallback (e.g. ~/.local/share/.../ha-token)
        if var in (None, "<file>"):
            txt = open(os.path.expanduser(path), errors="replace").read().strip()
            return txt.splitlines()[0].strip() if txt else ""
    except FileNotFoundError:
        return None
    except Exception:
        return None
    return ""
def _get(url, token, extra_h=None, data=None, timeout=15):
    h = {"Authorization": "Bearer " + token}
    if extra_h:
        h.update(extra_h)
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read()[:4000]
    except urllib.error.HTTPError as e:
        try:
            body = e.read()[:2000]
        except Exception:
            body = b""
        return e.code, body
    except Exception as e:
        return -1, ("%s: %s" % (type(e).__name__, e))[:160].encode()
def probe_or(tok):
    st, body = _get("https://openrouter.ai/api/v1/auth/key", tok)
    if st == 200:
        d = json.loads(body).get("data", {})
        return "valid", {"label": d.get("label"),
                         "expires_at": d.get("expires_at"),
                         "usage": d.get("usage"), "limit": d.get("limit"),
                         "limit_remaining": d.get("limit_remaining"),
                         "is_free_tier": d.get("is_free_tier")}
    if st in (401, 403):
        return "dead", {"http": st}
    return "error", {"http": st, "body": body[:120].decode("utf-8", "replace")}
def probe_ha(tok, url):
    st, body = _get(url.rstrip("/") + "/api/", tok)
    if st == 200:
        return "valid", {"message": body[:80].decode("utf-8", "replace")}
    if st in (401, 403):
        return "dead", {"http": st}
    return "error", {"http": st, "body": body[:120].decode("utf-8", "replace")}
def probe_cf(tok):
    # /user/tokens/verify rejects the scoped cfat_ token even though it
    # is live — fall back to a zone list before calling it dead.
    st, body = _get("https://api.cloudflare.com/client/v4/user/tokens/verify",
                    tok)
    if st == 200:
        try:
            d = json.loads(body)
            if d.get("success"):
                return "valid", {"via": "verify",
                                 "status": (d.get("result") or {}).get("status")}
        except Exception:
            pass
        return "valid", {"via": "verify"}
    if st in (401, 403):
        st2, body2 = _get(
            "https://api.cloudflare.com/client/v4/zones?per_page=1", tok)
        if st2 == 200:
            return "valid", {"via": "zones", "note":
                             "verify rejects scoped token (cfat quirk)"}
        if st2 in (401, 403):
            return "dead", {"http": st, "zones_http": st2}
        return "error", {"http": st, "zones_http": st2}
    return "error", {"http": st, "body": body[:120].decode("utf-8", "replace")}
def probe_gemini(tok, model):
    body = json.dumps({"contents": [{"parts": [{"text": "hi"}]}],
                      "generationConfig": {"maxOutputTokens": 1}}).encode()
    st, resp = _get("https://generativelanguage.googleapis.com/v1beta/models/"
                    + model + ":generateContent", "",
                    {"Content-Type": "application/json",
                     "x-goog-api-key": tok}, data=body, timeout=20)
    if st == 200:
        return "valid", {}
    t = resp.decode("utf-8", "replace")
    if st == 402 or "1011" in t or "depleted" in t.lower():
        return "dead", {"why": "credit-depleted", "http": st}
    if st == 429 or "RESOURCE_EXHAUSTED" in t:
        return "quota", {"http": st}
    if st in (401, 403):
        return "dead", {"http": st}
    return "error", {"http": st, "body": t[:120]}
'''

PROBE_BODY = r'''
out = {}
for s in SLOTS:
    tok = _env_var(s["file"], s.get("var"))
    if tok is None:
        out[s["id"]] = {"status": "missing-file"}
        continue
    if not tok:
        out[s["id"]] = {"status": "missing-var"}
        continue
    fp = hashlib.sha256(tok.encode()).hexdigest()[:8]
    masked = tok[:6] + "…" + tok[-4:] if len(tok) > 12 else "<short>"
    try:
        if s["kind"] == "openrouter":
            st, detail = probe_or(tok)
        elif s["kind"] == "ha":
            st, detail = probe_ha(tok, s["url"])
        elif s["kind"] == "cf":
            st, detail = probe_cf(tok)
        elif s["kind"] == "gemini":
            st, detail = probe_gemini(tok, s.get("model") or MODEL)
        else:
            st, detail = "error", {"why": "unknown kind"}
    except Exception as e:
        st, detail = "error", {"why": "%s: %s" % (type(e).__name__, e)}
    out[s["id"]] = {"status": st, "masked": masked, "fp": fp,
                    "detail": detail}
print(json.dumps(out))
'''


def _probe_script(slots: list[dict]) -> str:
    return (PROBE_HEAD
            + "SLOTS = " + json.dumps(slots) + "\n"
            + "MODEL = " + json.dumps(GEMINI_MODEL) + "\n"
            + PROBE_BODY)


def run_host_probe(host: str, slots: list[dict], local: bool) -> dict:
    """-> {slot_id: rec} or {"__host__": "unreachable"}."""
    script = _probe_script(slots)
    cmd = (["python3", "-"] if local else
           ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            host, "python3", "-"])
    try:
        r = subprocess.run(cmd, input=script, capture_output=True,
                           text=True, timeout=SSH_TIMEOUT)
    except Exception as e:
        return {"__host__": f"unreachable: {type(e).__name__} {e}"[:160]}
    raw = (r.stdout or "").strip()
    if not raw:
        err = (r.stderr or "").strip().splitlines()
        return {"__host__": f"unreachable rc={r.returncode} "
                            f"{(err[-1] if err else '')[:100]}"}
    try:
        return json.loads(raw.splitlines()[-1])
    except Exception:
        return {"__host__": f"bad-probe-output: {raw[-120:]}"}


def probe_all(slots: list[dict]) -> dict[str, dict]:
    """Group by host, probe in parallel (host-loads pattern)."""
    by_host: dict[str, list[dict]] = {}
    for s in slots:
        by_host.setdefault(s["host"], []).append(s)
    local = socket.gethostname()
    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(run_host_probe, h, sl, h == local): h
                for h, sl in by_host.items()}
        for f in concurrent.futures.as_completed(futs):
            h = futs[f]
            res = f.result()
            if "__host__" in res:
                for s in by_host[h]:
                    results[s["id"]] = {"status": "host-unreachable",
                                        "detail": {"why": res["__host__"]}}
            else:
                results.update(res)
    return results


# --- gemini ops-event scan ----------------------------------------------------

def mddb_post(path: str, payload: dict, timeout: int = 15):
    req = urllib.request.Request(
        f"{MDDB}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def gemini_quota_scan(lookback_h: float) -> dict:
    """Count quota-ish ops events per lane+type in the window."""
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=lookback_h))
    hits, scanned = [], 0
    for coll in GEMINI_OPS_COLLECTIONS:
        try:
            docs = mddb_post("/search", {"collection": coll,
                                         "filterMeta": {"kind": ["ops-event"]},
                                         "limit": 300})
        except Exception as e:
            print(f"warn: mddb {coll}: {e}", file=sys.stderr)
            continue
        if not isinstance(docs, list):
            continue
        scanned += 1
        for d in docs:
            meta = d.get("meta") or {}
            ts = (meta.get("ts") or [""])[0]
            try:
                dt = datetime.datetime.fromisoformat(
                    ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                if dt < cutoff:
                    continue
            except Exception:
                continue
            etype = (meta.get("type") or [""])[0]
            head = ((d.get("contentMd") or "").splitlines() or [""])[0]
            if QUOTA_TYPES.search(etype) or QUOTA_TEXT.search(head):
                hits.append({"collection": coll, "type": etype,
                             "ts": ts, "head": head[:90]})
    return {"collections_scanned": scanned, "hits": hits}


# --- judging ------------------------------------------------------------------

def _parse_iso(s):
    if not s:
        return None
    try:
        d = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def judge(slot: dict, rec: dict) -> dict:
    """-> {level: ok|warn|alert|unknown, why} for one slot result."""
    st = rec.get("status")
    sid = slot["id"]
    if st == "host-unreachable":
        return {"level": "unknown",
                "why": f"host unreachable: {rec['detail'].get('why', '?')}"}
    if st == "missing-file":
        return {"level": "warn", "why": f"{slot['file']} absent on {slot['host']}"}
    if st == "missing-var":
        return {"level": "warn",
                "why": f"{slot['var']} not set in {slot['file']} on {slot['host']}"}
    d = rec.get("detail") or {}
    if slot["kind"] == "openrouter":
        if st == "dead":
            return {"level": "alert",
                    "why": f"OR key {rec.get('masked')} rejected "
                           f"(HTTP {d.get('http')}) — fleet inference dies"}
        if st == "valid":
            exp = _parse_iso(d.get("expires_at"))
            now = datetime.datetime.now(datetime.timezone.utc)
            if exp and exp < now:
                return {"level": "alert",
                        "why": f"OR key {rec.get('masked')} EXPIRED "
                               f"{d.get('expires_at')}"}
            if exp and (exp - now) < datetime.timedelta(hours=EXPIRY_WARN_H):
                hrs = (exp - now).total_seconds() / 3600
                return {"level": "warn",
                        "why": f"OR key {rec.get('masked')} expires in "
                               f"{hrs:.0f}h ({d.get('expires_at')})"}
            lim, use, rem = d.get("limit"), d.get("usage"), \
                d.get("limit_remaining")
            if rem is not None and rem <= 0:
                return {"level": "alert",
                        "why": f"OR key {rec.get('masked')} "
                               f"limit_remaining={rem} — bridge dead "
                               f"(the 2026-10-12 failure mode)"}
            if lim and use is not None and lim > 0 and \
                    use / lim * 100 >= QUOTA_WARN_PCT:
                return {"level": "warn",
                        "why": f"OR key {rec.get('masked')} at "
                               f"{use / lim * 100:.0f}% of limit "
                               f"(${use:.2f}/${lim:.2f})"}
            return {"level": "ok",
                    "why": f"{rec.get('masked')} label={d.get('label')} "
                           f"exp={d.get('expires_at') or 'never'} "
                           f"use={use}/{lim}"}
        return {"level": "unknown",
                "why": f"OR probe error: {d.get('body') or d}"}
    if slot["kind"] == "ha":
        if st == "dead":
            return {"level": "alert",
                    "why": f"HA token {rec.get('masked')} for {slot['url']} "
                           f"-> HTTP {d.get('http')} (dead LLAT)"}
        if st == "valid":
            return {"level": "ok", "why": f"{rec.get('masked')} -> "
                                          f"{slot['url']} live"}
        return {"level": "unknown",
                "why": f"HA probe error vs {slot['url']}: "
                       f"{d.get('body') or d}"}
    if slot["kind"] == "cf":
        if st == "dead":
            return {"level": "alert",
                    "why": f"CF_API_TOKEN {rec.get('masked')} on "
                           f"{slot['host']} rejected (verify + zones)"}
        if st == "valid":
            return {"level": "ok",
                    "why": f"{rec.get('masked')} live via {d.get('via')}"
                           + (f" ({d.get('note')})" if d.get('note') else "")}
        return {"level": "unknown",
                "why": f"CF probe error: {d}"}
    if slot["kind"] == "gemini":
        if st == "dead":
            return {"level": "alert",
                    "why": f"Gemini key {rec.get('masked')} "
                           f"({d.get('why') or 'auth'}) dead"}
        if st == "quota":
            return {"level": "warn",
                    "why": f"Gemini key {rec.get('masked')} 429 "
                           f"RESOURCE_EXHAUSTED"}
        if st == "valid":
            return {"level": "ok", "why": f"{rec.get('masked')} live"}
        return {"level": "unknown", "why": f"Gemini probe error: {d}"}
    return {"level": "unknown", "why": f"unhandled kind {slot['kind']}"}


def or_drift_finding(recs: dict) -> dict | None:
    """All OR slots should hold the SAME fleet key — differing fps mean a
    stale slot (the 2026-10-12 ada-*.env sweep miss)."""
    fps = {sid: r.get("fp") for sid, r in recs.items()
           if sid.startswith("or-") and r.get("fp")}
    if len(set(fps.values())) > 1:
        detail = ", ".join(f"{k}:{v}" for k, v in sorted(fps.items()))
        return {"id": "or-fp-drift", "level": "warn",
                "why": f"OR key fingerprints differ across slots — a store "
                       f"is stale ({detail})"}
    return None


# --- sinks --------------------------------------------------------------------

def send_line(text: str) -> tuple[bool, str]:
    """LINE push via ada-line-relay :8912/send — direct loopback first
    (relay lives on idc03), then chaba-nag's `ssh idc03 curl` fallback."""
    payload = json.dumps({"text": text})
    try:
        req = urllib.request.Request(
            RELAY_URL, data=payload.encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
        if '"ok":true' in body.replace(" ", ""):
            return True, "relay-url"
    except Exception:
        pass
    try:
        p = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             RELAY_SSH, "curl", "-s", "-m", "8", "-X", "POST",
             "http://127.0.0.1:8912/send",
             "-H", "Content-Type: application/json", "-d", "@-"],
            input=payload, capture_output=True, text=True, timeout=30)
        if '"ok":true' in (p.stdout or "").replace(" ", ""):
            return True, f"ssh:{RELAY_SSH}"
        return False, (p.stdout or p.stderr or "")[:160]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def board_api(path: str, body: dict, timeout: int = 20) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{BOARD_API}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"error": f"{type(e).__name__}: {e}"}


def card_id(finding_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", finding_id.lower()).strip("-")
    return f"keywatch-{slug}"[:60]


def file_incident(f: dict) -> str:
    """Alert-level finding -> board-api card (dedup by deterministic id)."""
    cid = card_id(f["id"])
    body = {"id": cid, "title": f"key-watch: {f['id']} — {f['why'][:60]}",
            "column": "review", "review_kind": "triage",
            "brief": f"Credential monitor flagged {f['id']}: {f['why']}",
            "note": (f"Auto-filed by key-watch at "
                     f"{datetime.datetime.now(ICT):%Y-%m-%d %H:%M} ICT. "
                     f"Rotate/replace the credential, then close the card "
                     f"(key-watch auto-closes on next clean run)."),
            "priority": "high", "tags": ["secrets", "monitoring"],
            "from": "chaba"}
    st, r = board_api("/card", body)
    if st in (200, 201):
        return f"filed {cid}"
    # duplicate or other error -> leave a comms line on the card instead
    st2, _ = board_api("/comment", {"id": cid, "from": "chaba",
                                    "text": f"still alerting: {f['why']}"[:400]})
    return f"exists {cid} (comment {'ok' if st2 == 200 else st2})"


def close_incident(finding_id: str) -> str:
    cid = card_id(finding_id)
    board_api("/comment", {"id": cid, "from": "chaba",
                           "text": "recovered — latest key-watch probe "
                                   "is clean; auto-closing."})
    st, _ = board_api("/action", {"id": cid, "do": "close",
                                  "column": "done", "from": "chaba"})
    return f"closed {cid}" if st == 200 else f"close {cid} http {st}"


def emit_ops_event(verdict: str, findings: list[dict], notes: list[str]) -> str:
    """One ops-event doc per run — same shape host-loads/gemini_pool emit."""
    now = datetime.datetime.now(datetime.timezone.utc)
    bad = [f for f in findings if f["level"] in ("warn", "alert")]
    md = [f"key-watch run — verdict {verdict} "
          f"({len(findings)} sources, {len(bad)} finding(s))",
          ""]
    for f in findings:
        if f["level"] != "ok":
            md.append(f"- [{f['level'].upper()}] {f['id']}: {f['why']}")
    if not bad:
        md.append("- all sources clean")
    if notes:
        md += [""] + [f"- {n}" for n in notes]
    try:
        mddb_post("/add", {
            "collection": OPS_COLLECTION,
            "key": f"ops-key-watch-{now:%Y%m%d%H%M%S}",
            "lang": "en",
            "contentMd": "\n".join(md),
            "meta": {"kind": ["ops-event"], "type": ["key_watch"],
                     "instance": ["tony"], "verdict": [verdict],
                     "findings": [str(len(bad))],
                     "ts": [now.isoformat(timespec="seconds")],
                     "written_by": ["key-watch"]}})
        return "emitted"
    except Exception as e:
        return f"emit-failed {type(e).__name__}: {e}"


# --- selftest ------------------------------------------------------------------

SELFTEST_RESULTS = {
    "or-idc03": {"status": "valid", "masked": "sk-or-…aa11", "fp": "aa11",
                 "detail": {"label": "ada-safety",
                            "expires_at": "2026-10-24T00:00:00Z",
                            "usage": 9.9, "limit": 10.0,
                            "limit_remaining": 0.1}},
    "or-tony-dell": {"status": "host-unreachable",
                     "detail": {"why": "timeout"}},
    "ha-tony-ada-mn01": {"status": "dead", "masked": "eyJh…zz99",
                         "fp": "zz99", "detail": {"http": 401}},
    "cf-idc03": {"status": "valid", "masked": "cfat_…cc33", "fp": "cc33",
                 "detail": {"via": "zones", "note": "cfat quirk"}},
}


def selftest() -> int:
    findings = []
    for s in WATCHLIST:
        rec = SELFTEST_RESULTS.get(s["id"], {"status": "valid",
                                             "masked": "x…1", "fp": "f1",
                                             "detail": {}})
        j = judge(s, rec)
        findings.append({"id": s["id"], **j})
        if s["id"] in SELFTEST_RESULTS:
            print(f"  {s['id']:20} -> {j['level']:7} {j['why'][:80]}")
    drift = or_drift_finding(SELFTEST_RESULTS)
    if drift:
        findings.append(drift)
        print(f"  {drift['id']:20} -> {drift['level']:7} {drift['why'][:80]}")
    alerts = [f for f in findings if f["level"] == "alert"]
    warns = [f for f in findings if f["level"] == "warn"]
    print(f"selftest: {len(alerts)} alert, {len(warns)} warn, "
          f"{sum(1 for f in findings if f['level'] == 'unknown')} unknown")
    text = format_line(alerts, warns, [f for f in findings
                                       if f["level"] == "unknown"])
    print("--- LINE preview ---\n" + text)
    print("--- card bodies ---")
    for f in alerts:
        print(f"  would file {card_id(f['id'])}: {f['why'][:80]}")
    # sanity assertions on the fixture
    by_id = {f["id"]: f for f in findings}
    assert by_id["or-idc03"]["level"] == "warn", "expected >80% warn"
    assert by_id["ha-tony-ada-mn01"]["level"] == "alert"
    assert by_id["cf-idc03"]["level"] == "ok"
    assert by_id["or-tony-dell"]["level"] == "unknown"
    print("selftest OK")
    return 0


def format_line(alerts, warns, unknowns) -> str:
    n = len(alerts) + len(warns)
    lines = [f"🔑 KEY-WATCH — {n} finding(s) need you:"]
    if alerts:
        lines += ["", f"▸ ALERT ({len(alerts)}) — dead/expired:"] + \
                 [f"  · {f['id']}: {f['why'][:80]}" for f in alerts] + \
                 ["  → incident card(s) filed on the board"]
    if warns:
        lines += ["", f"▸ WARN ({len(warns)}) — expiry<48h / quota>80%:"] + \
                 [f"  · {f['id']}: {f['why'][:80]}" for f in warns]
    if unknowns:
        lines += ["", f"▸ probe gaps ({len(unknowns)}):"] + \
                 [f"  · {f['id']}: {f['why'][:70]}" for f in unknowns[:5]]
    return "\n".join(lines)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--now", action="store_true",
                    help="ignore the LINE resend gap")
    ap.add_argument("--hosts", help="comma list — probe only these hosts")
    ap.add_argument("--gemini-probe", action="store_true",
                    help="also run the ~1-token generateContent probe per "
                         "key var in GEMINI_KEYS_FILE on " + GEMINI_HOST)
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    slots = list(WATCHLIST)
    if args.hosts:
        keep = {h.strip() for h in args.hosts.split(",") if h.strip()}
        slots = [s for s in slots if s["host"] in keep]
    if args.gemini_probe:
        for var in GEMINI_KEY_VARS:
            slots.append({"id": f"gemini-{var.lower().replace('_', '-')}",
                          "kind": "gemini", "host": GEMINI_HOST,
                          "file": GEMINI_KEYS_FILE, "var": var})

    results = probe_all(slots)
    findings = []
    for s in slots:
        rec = results.get(s["id"], {"status": "error",
                                    "detail": {"why": "no probe row"}})
        findings.append({"id": s["id"], **judge(s, rec)})
        if rec.get("status") not in ("valid",):
            print(f"  {s['id']:22} {rec.get('status')!s:18} "
                  f"{findings[-1]['level']:7} {findings[-1]['why'][:80]}")

    drift = or_drift_finding(results)
    if drift:
        findings.append(drift)

    gscan = gemini_quota_scan(LOOKBACK_H)
    notes = [f"gemini ops-scan: {len(gscan['hits'])} quota markers "
             f"in {LOOKBACK_H:g}h across {gscan['collections_scanned']}/"
             f"{len(GEMINI_OPS_COLLECTIONS)} collections"]
    if gscan["hits"]:
        findings.append({
            "id": "gemini-ops-events", "level": "warn",
            "why": f"{len(gscan['hits'])} quota-exhaustion marker(s) in "
                   f"ada ops-events last {LOOKBACK_H:g}h: "
                   + ", ".join(sorted({h['type'] for h in gscan['hits']}))})
        for h in gscan["hits"][-3:]:
            notes.append(f"  {h['ts'][:16]} {h['collection']} "
                         f"{h['type']} — {h['head'][:70]}")

    alerts = [f for f in findings if f["level"] == "alert"]
    warns = [f for f in findings if f["level"] == "warn"]
    unknowns = [f for f in findings if f["level"] == "unknown"]
    verdict = ("alert" if alerts else
               "warn" if warns else
               "degraded" if unknowns else "ok")
    print(f"key-watch verdict={verdict}: "
          f"{len(alerts)} alert / {len(warns)} warn / "
          f"{len(unknowns)} unknown of {len(findings)}")

    st = load_state()
    now_epoch = datetime.datetime.now().timestamp()

    # incident cards: file for alerts, auto-close recovered ones we filed
    open_cards = st.get("open_cards") or {}
    notes_cards = []
    if not args.dry_run:
        for f in alerts:
            if open_cards.get(f["id"]):
                notes_cards.append(f"{f['id']} already carded")
                continue
            notes_cards.append(file_incident(f))
            open_cards[f["id"]] = card_id(f["id"])
        cur_ids = {f["id"] for f in alerts}
        for fid, cid in list(open_cards.items()):
            if fid not in cur_ids:
                notes_cards.append(close_incident(fid))
                del open_cards[fid]

    # LINE — quiet hours defer the push only (cards/ops-event already ran)
    line_note = "quiet"
    if alerts or warns:
        quiet = QUIET[0] <= datetime.datetime.now(ICT).hour < QUIET[1]
        h = hashlib.sha1(json.dumps(
            [(f["id"], f["level"]) for f in alerts + warns],
            sort_keys=True).encode()).hexdigest()
        gap_min = (now_epoch - (st.get("line_sent") or 0)) / 60
        resend = st.get("line_hash") != h or gap_min >= RESEND_MIN
        if args.dry_run:
            line_note = "dry-run"
        elif quiet:
            line_note = "quiet-hours deferred"
        elif not (args.now or resend):
            line_note = f"unchanged set, sent {gap_min:.0f}m ago — skip"
        else:
            ok, via = send_line(format_line(alerts, warns, unknowns))
            line_note = f"sent via {via}" if ok else f"FAILED {via}"
            st["line_hash"], st["line_sent"] = h, now_epoch
    print(f"LINE: {line_note}")

    ops = "dry-run" if args.dry_run else \
        emit_ops_event(verdict, findings, notes + notes_cards)
    print(f"ops-event: {ops}")
    for n in notes + notes_cards:
        print(f"  {n}")

    if not args.dry_run:
        st.update({"last_run": datetime.datetime.now(ICT).isoformat(
            timespec="seconds"), "verdict": verdict,
            "findings": {f["id"]: f["level"] for f in findings},
            "open_cards": open_cards})
        save_state(st)
    # exit 0 on a completed run — findings travel via LINE/card/ops-event,
    # nonzero is for crashes only (timer-expectations procedure).
    return 0


if __name__ == "__main__":
    sys.exit(main())
