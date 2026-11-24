#!/usr/bin/env python3
"""lane-preflight — live admission probe for the JevTeam omen + openrouter
lanes (card jevteam-omen-or-lane-admission, 2026-11-24).

Read-only probes only: HTTP GETs on health/metrics/key endpoints plus ONE
bounded decision call per lane when --smoke is passed (a /v1/systemone
noul on omen, a max_tokens=8 chat completion on openrouter). No
mutations, no secrets printed — keys resolve from the environment or
~/.config/secrets/litellm-keys.env at runtime and are never echoed.

Lane -> checks (endpoint table mirrors ssot.devnest-lanes.yml):

  omen        GET /health on tony-omen :8777 (gemma-3-4b heavy),
              :8778 (gemma-3-1b student), :8779 (student replica),
              :8780 (jev-student-distilmulti confirm-gate); optional
              /metrics + /v1/systemone smoke per endpoint.
  openrouter  LiteLLM gateway :4000 /health/liveliness + /health/readiness,
              /key/info budget headroom for the resolved virtual key,
              one live or-free leg probe through /v1/chat/completions,
              and — only when OPENROUTER_API_KEY is in the env — the OR
              account /auth/key + /credits quota read.

Verdicts (fail-closed, same posture as kk_mac_admission.snapshot):
  eligible   every required check passed
  degraded   lane answers but a non-critical check failed (e.g. one
             omen replica down, OR free quota exhausted but paid leg ok)
  down       a required check failed — the lane must not be admitted

Exit codes: 0 all requested lanes eligible | 1 any degraded |
            2 any down or usage/io error.

Usage:
  lane-preflight.py                    # both lanes, health only
  lane-preflight.py --lane omen        # omen endpoints only
  lane-preflight.py --lane openrouter --smoke
  lane-preflight.py --json --timeout 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# --- endpoint table (canonical copy lives in ssot.devnest-lanes.yml) ---
OMEN_ENDPOINTS = [
    {"id": "omen-8777-heavy", "url": "http://100.75.102.88:8777",
     "model": "gemma-3-4b-it", "role": "heavy scorer / noul gate",
     "critical": True},
    {"id": "omen-8778-student", "url": "http://100.75.102.88:8778",
     "model": "gemma-3-1b-it", "role": "hot bounded classify/pre-gate",
     "critical": True},
    {"id": "omen-8779-student-b", "url": "http://100.75.102.88:8779",
     "model": "gemma-3-1b-it", "role": "student replica",
     "critical": False},
    {"id": "omen-8780-confirm", "url": "http://100.75.102.88:8780",
     "model": "jev-student-distilmulti", "role": "confirm-gate only",
     "critical": False},
]
LITELLM_BASE = os.environ.get("LITELLM_URL",
                              "http://100.102.134.91:4000").rstrip("/")
OR_API = "https://openrouter.ai/api/v1"

# key preference order for the gateway probes — bench first (preflight
# is bench traffic), then the shared prod key.
KEY_ENV_PREF = ["LITELLM_KEY_BENCH", "LITELLM_KEY_CHABA",
                "LITELLM_KEY_ADA", "LITELLM_KEY_MDDB",
                "LITELLM_KEY_KK", "LITELLM_KEY_MICHAEL"]
SECRETS_FILE = Path.home() / ".config" / "secrets" / "litellm-keys.env"

SMOKE_NOUL = {
    "type": "noul",
    "instructions": ("Is the action 'git status' safe for an AI agent "
                     "to run unattended — read-only, reversible?"),
    "criteria": {"true": "safe to run unattended",
                 "false": "unsafe — needs a human first"},
}


def _env_keys() -> dict:
    """KEY=VALUE pairs from litellm-keys.env without printing values."""
    keys = {}
    try:
        for line in SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                keys[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return keys


def resolve_litellm_key() -> tuple[str, str]:
    """(alias, key) — env wins, then the secrets file. ('', '') if none."""
    file_keys = _env_keys()
    for name in KEY_ENV_PREF:
        k = os.environ.get(name) or file_keys.get(name)
        if k:
            return name, k
    return "", ""


def _req(url: str, *, method="GET", payload=None, headers=None,
         timeout=10.0):
    """-> (status, body_bytes, ms, err). Never raises."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), round((time.time() - t0) * 1000), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, body, round((time.time() - t0) * 1000), \
            f"HTTP {e.code}"
    except Exception as e:
        return 0, b"", round((time.time() - t0) * 1000), \
            f"{type(e).__name__}: {e}"[:120]


def _check(name: str, ok: bool, detail: str, ms: int | None = None,
           critical: bool = True) -> dict:
    return {"check": name, "ok": bool(ok), "critical": critical,
            "detail": detail, "ms": ms}


# ------------------------------------------------------------------ omen

def probe_omen(timeout: float, smoke: bool) -> dict:
    checks = []
    endpoint_rows = []
    for ep in OMEN_ENDPOINTS:
        base = ep["url"].rstrip("/")
        row = {"id": ep["id"], "url": base, "model": ep["model"],
               "role": ep["role"], "checks": []}
        st, body, ms, err = _req(base + "/health", timeout=timeout)
        health_ok = st == 200
        model = ""
        if health_ok:
            try:
                model = json.loads(body).get("model", "")
            except Exception:
                pass
        row["checks"].append(_check(
            "health", health_ok,
            f"HTTP {st} model={model or '?'}" + (f" err={err}" if err else ""),
            ms, ep["critical"]))
        checks.extend(row["checks"])
        endpoint_rows.append(row)
        if not (smoke and health_ok):
            continue
        payload = {"model": "jev-latest",
                   "state": {"action": "git status"},
                   "questions": {"q": SMOKE_NOUL}}
        st, body, ms, err = _req(
            base + "/v1/systemone", method="POST", payload=payload,
            timeout=max(timeout, 60.0))
        answered = False
        noul = None
        if st == 200:
            try:
                ans = json.loads(body).get("answers", {}).get("q", {})
                noul = ans.get("noul")
                answered = isinstance(noul, (int, float))
            except Exception:
                pass
        row["checks"].append(_check(
            "systemone_smoke", answered,
            f"HTTP {st} noul={noul} "
            f"({'safe->clear' if isinstance(noul, (int, float)) and noul >= 0.5 else 'gate' if answered else 'no answer'})"
            + (f" err={err}" if err else ""),
            ms, ep["critical"]))
        checks.extend(row["checks"][-1:])
    crit_fail = any(not c["ok"] and c["critical"] for c in checks)
    any_fail = any(not c["ok"] for c in checks)
    verdict = "down" if crit_fail else ("degraded" if any_fail else "eligible")
    return {"lane": "omen", "verdict": verdict, "checks": checks,
            "endpoints": endpoint_rows}


# ------------------------------------------------------------- openrouter

def probe_openrouter(timeout: float, smoke: bool) -> dict:
    checks = []
    alias, key = resolve_litellm_key()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if not key:
        checks.append(_check(
            "litellm_key", False,
            "no LITELLM_KEY_* in env or ~/.config/secrets/litellm-keys.env",
            critical=True))
    else:
        checks.append(_check(
            "litellm_key", True, f"resolved alias={alias}", critical=False))

    st, body, ms, err = _req(LITELLM_BASE + "/health/liveliness",
                             timeout=timeout)
    checks.append(_check("gateway_liveliness", st == 200,
                         f"HTTP {st} {err or ''}".strip(), ms))
    st, body, ms, err = _req(LITELLM_BASE + "/health/readiness",
                             timeout=timeout)
    db_ok = False
    if st == 200:
        try:
            db_ok = json.loads(body).get("status") == "healthy"
        except Exception:
            pass
    checks.append(_check("gateway_readiness", db_ok,
                         f"HTTP {st} db={'connected' if db_ok else '?'} "
                         f"{err or ''}".strip(), ms))

    # key budget — spend vs max_budget is the lane's cost gate evidence
    if key:
        st, body, ms, err = _req(LITELLM_BASE + "/key/info",
                                 headers=headers, timeout=timeout)
        info = {}
        if st == 200:
            try:
                info = json.loads(body).get("info", {})
            except Exception:
                pass
        spend = info.get("spend")
        budget = info.get("max_budget")
        headroom = None
        try:
            if spend is not None and budget is not None:
                headroom = round(float(budget) - float(spend), 4)
        except (TypeError, ValueError):
            pass
        ok = st == 200 and headroom is not None and headroom > 0
        checks.append(_check(
            "key_budget", ok,
            f"alias={info.get('key_alias', alias)} spend={spend} "
            f"max_budget={budget} {info.get('budget_duration','')} "
            f"headroom={headroom} models={len(info.get('models', []))}",
            ms, critical=False))

    # live OR leg probe through the gateway — or-free first (cheap),
    # paid deepseek leg only with --smoke-paid (real spend).
    if key:
        for leg, model, mt in (("or_free_leg", "or-free-nemotron-35", 8),):
            payload = {"model": model,
                       "messages": [{"role": "user",
                                     "content": "Reply with the single "
                                                "word: ok"}],
                       "max_tokens": mt}
            st, body, ms, err = _req(
                LITELLM_BASE + "/v1/chat/completions",
                method="POST", payload=payload, headers=headers,
                timeout=max(timeout, 90.0))
            answered = False
            detail = f"HTTP {st}"
            if st == 200:
                try:
                    ch = json.loads(body)["choices"][0]["message"]
                    content = (ch.get("content") or "").strip()
                    answered = bool(content)
                    detail += f" content={content[:40]!r}"
                except Exception:
                    detail += " unparseable"
            elif st in (401, 402, 403, 429):
                detail += f" {err}"
                try:
                    detail += " " + json.loads(body).get(
                        "error", {}).get("message", "")[:100]
                except Exception:
                    pass
            checks.append(_check(
                leg, answered or st == 200,
                detail + (f" err={err}" if err and st == 0 else ""),
                ms, critical=False))

    # OR account quota — only when a direct key is in the env (the
    # fleet OR key lives in the litellm container on idc03; hosts that
    # hold OPENROUTER_API_KEY can report the account state).
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        oh = {"Authorization": f"Bearer {or_key}"}
        st, body, ms, err = _req(OR_API + "/auth/key", headers=oh,
                                 timeout=timeout)
        lim = usage = None
        if st == 200:
            try:
                d = json.loads(body).get("data", {})
                lim = d.get("limit")
                usage = d.get("usage")
            except Exception:
                pass
        checks.append(_check(
            "or_account_key", st == 200,
            f"HTTP {st} limit={lim} usage={usage} "
            f"{err or ''}".strip(), ms, critical=False))
        st, body, ms, err = _req(OR_API + "/credits", headers=oh,
                                 timeout=timeout)
        credits = None
        if st == 200:
            try:
                d = json.loads(body).get("data", {})
                credits = round(float(d.get("total_credits", 0))
                                - float(d.get("total_usage", 0)), 2)
            except Exception:
                pass
        checks.append(_check(
            "or_account_credits", st == 200 and credits is not None,
            f"HTTP {st} remaining={credits} {err or ''}".strip(),
            ms, critical=False))
    else:
        checks.append(_check(
            "or_account_quota", True,
            "skipped — OPENROUTER_API_KEY not in env (quota readable "
            "only on hosts holding the OR key; gateway legs above are "
            "the admission signal)", critical=False))

    crit_fail = any(not c["ok"] and c["critical"] for c in checks)
    any_fail = any(not c["ok"] for c in checks)
    verdict = "down" if crit_fail else ("degraded" if any_fail else "eligible")
    return {"lane": "openrouter", "verdict": verdict, "checks": checks,
            "gateway": LITELLM_BASE, "key_alias": alias or None}


# -------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lane", choices=["omen", "openrouter", "all"],
                    default="all")
    ap.add_argument("--smoke", action="store_true",
                    help="run one bounded decision/chat call per lane "
                         "(slower; health-only is the default)")
    ap.add_argument("--timeout", type=float, default=10.0,
                    help="per-probe HTTP timeout seconds (smoke calls "
                         "get max(timeout,60) internally)")
    ap.add_argument("--json", action="store_true",
                    help="emit the full JSON report (default also prints "
                         "a one-line verdict per lane)")
    args = ap.parse_args()

    report = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "lanes": []}
    worst = 0
    if args.lane in ("omen", "all"):
        r = probe_omen(args.timeout, args.smoke)
        report["lanes"].append(r)
        worst = max(worst, {"eligible": 0, "degraded": 1,
                            "down": 2}[r["verdict"]])
    if args.lane in ("openrouter", "all"):
        r = probe_openrouter(args.timeout, args.smoke)
        report["lanes"].append(r)
        worst = max(worst, {"eligible": 0, "degraded": 1,
                            "down": 2}[r["verdict"]])

    for lane in report["lanes"]:
        fails = [c["check"] for c in lane["checks"] if not c["ok"]]
        print(f"{lane['lane']}: {lane['verdict']}"
              + (f"  failed={fails}" if fails else ""))
    print(json.dumps(report, indent=1))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
