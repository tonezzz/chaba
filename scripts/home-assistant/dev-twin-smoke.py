#!/usr/bin/env python3
"""dev-twin-smoke.py — scripted browser pass on a dev twin via playlived.

The alpha -> pre-prod gate from ssot.release-lifecycle.yml (Tony 2026-10-08):
no dev-twin playlive evidence, no promotion. This produces that evidence —
a headless browser loads the dev twin's dashboard, waits for real Lovelace
content, runs DOM assertions, saves a screenshot + JSON verdict under
reports/dev-twin-smoke/ (gitignored, host-local), and appends a [smoke]
tagged comms line to the release card.

Usage:
    dev-twin-smoke.py --lane tony                 # lane's dev instance
    dev-twin-smoke.py --inst michael-dev          # ad-hoc registry instance
    dev-twin-smoke.py --inst michael-dev --dashboard tony-test --views pfg2
    dev-twin-smoke.py --inst michael-dev --selector sunsynk-power-flow-card
    dev-twin-smoke.py --inst michael-dev --card release-lifecycle-standard

Env:
    PLAYLIVED_URL   playlived endpoint (default per playlive-hosts.yml
                    session_selection for this host, else 127.0.0.1:9230)
    BOARD_API       board write path (default http://127.0.0.1:8787;
                    set https://tony-dell.taila0626a.ts.net/apps/board-api
                    off-host)
    LANES_FILE      override lanes registry

Exit 0 pass / 1 smoke fail (still posts [smoke] FAIL comms) / 2 infra error
(instance unprovisioned or unreachable, playlived down, no token).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import socket
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

REPO = Path(os.environ.get(
    "CHABA_REPO", str(Path(__file__).resolve().parents[2])))
LANES_FILE = Path(os.environ.get(
    "LANES_FILE",
    REPO / "docs/ssot/infrastructure/ssot.home-assistant.lanes.yml"))
PLAYLIVE_HOSTS = (REPO / "docs/ssot/infrastructure/playlive-hosts.yml")
OUT_DIR = REPO / "reports" / "dev-twin-smoke"
BOARD_API = os.environ.get("BOARD_API", "http://127.0.0.1:8787").rstrip("/")

NAV_TIMEOUT_S = 60


def eprint(*a):
    print(*a, file=sys.stderr)


# --- registry ---------------------------------------------------------------

def load_lanes() -> dict:
    return yaml.safe_load(LANES_FILE.read_text()) or {}


def resolve_instance(reg: dict, args) -> tuple[str, dict]:
    """-> (instance_id, instance dict). --lane resolves its dev twin."""
    if args.inst:
        inst = args.inst
    elif args.lane:
        lane = (reg.get("lanes") or {}).get(args.lane)
        if not lane:
            sys.exit(f"dev-twin-smoke: unknown lane {args.lane!r} "
                     f"(see {LANES_FILE.name})")
        inst = lane.get("dev")
    else:
        sys.exit("dev-twin-smoke: need --lane, --inst, or --url")
    node = (reg.get("instances") or {}).get(inst)
    if not node:
        sys.exit(f"dev-twin-smoke: unknown instance {inst!r}")
    return inst, dict(node)


# --- auth (mirrors ha-lanes.sh inst_token kinds) ------------------------------

def _ssh_cat(ssh_target: str, ssh_key: str | None, path: str) -> str:
    import shlex
    import subprocess
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
           "-o", "StrictHostKeyChecking=no"]
    if ssh_key:
        cmd += ["-i", ssh_key, "-o", "IdentitiesOnly=yes"]
    cmd += [ssh_target, f"cat {shlex.quote(path)}"]
    return subprocess.run(cmd, capture_output=True, text=True,
                          check=True).stdout


def inst_token(inst: dict) -> str | None:
    auth = inst.get("auth") or {}
    kind = auth.get("kind")
    ssh = inst.get("ssh")

    # env/file kinds are operator-side secrets — always local (ha-lanes.sh
    # inst_token does the same). Only `refresh` reaches into the instance's
    # config dir, which may live on another host.
    def read_config_file(path: str) -> str:
        if ssh and ssh != "local":
            return _ssh_cat(ssh, inst.get("ssh_key"), path)
        return Path(path).expanduser().read_text()

    try:
        if kind == "env":
            for line in Path(auth["file"]).expanduser().read_text(
                    ).splitlines():
                if line.startswith(auth["var"] + "="):
                    return line.split("=", 1)[1].strip()
            return None
        if kind == "file":
            return Path(auth["file"]).expanduser().read_text().strip()
        if kind == "refresh":
            raw = read_config_file(
                inst["config"].rstrip("/") + "/.storage/auth")
            data = json.loads(raw)
            rt = next(t["token"] for t in data["data"]["refresh_tokens"]
                      if t.get("client_name") == auth.get("client_name"))
            req = urllib.request.Request(
                inst["url"].rstrip("/") + "/auth/token", method="POST",
                data=(f"grant_type=refresh_token&refresh_token={rt}"
                      ).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            return json.load(urllib.request.urlopen(req, timeout=15)
                             )["access_token"]
    except Exception as e:
        eprint(f"dev-twin-smoke: token resolution failed ({kind}): {e}")
        return None
    return None


# --- playlived ----------------------------------------------------------------

def playlived_url() -> str:
    if os.environ.get("PLAYLIVED_URL"):
        return os.environ["PLAYLIVED_URL"].rstrip("/")
    # same selection rule as playlive-hosts-loader.py: per_host -> failover
    try:
        data = yaml.safe_load(PLAYLIVE_HOSTS.read_text()) or {}
        host = socket.gethostname().split(".")[0].replace("-", "_")
        url = ((data.get("per_host") or {}).get(host) or {}
               ).get("playlive_url")
        if url:
            return url.rstrip("/")
    except Exception:
        pass
    return "http://127.0.0.1:9230"


def rpc(base: str, method: str, path: str, payload=None,
        timeout: int = 60) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.load(resp)
    if not out.get("ok"):
        raise RuntimeError(f"{method} {path}: {out}")
    return out


def action(base: str, sid: str, name: str, payload=None,
           timeout: int = 60) -> dict:
    return rpc(base, "POST", f"/sessions/{sid}/{name}", payload or {},
               timeout)


# --- browser assertions ------------------------------------------------------

# NOTE: playlived eval needs an expression or IIFE — a bare arrow function
# returns {ok:true} with no result key (the function object isn't
# serializable). Keep the trailing ().
PROBE_JS = """(() => {
  const deepAll = (root, sel, out=[]) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.matches && el.matches(sel)) out.push(el);
      if (el.shadowRoot) deepAll(el.shadowRoot, sel, out);
    }
    return out;
  };
  const lovelace = deepAll(document,
    'ha-main, home-assistant, hui-root, hui-view');
  const cards = deepAll(document,
    'hui-card, hui-entities-card, hui-button-card, '
    + 'sunsynk-power-flow-card, sunsynk-power-flow-card-fork, pfg3d-card');
  const err = deepAll(document,
    'hui-error-card, ha-alert').map(e => (e.textContent||'').trim())
    .filter(Boolean).slice(0, 3);
  const login = deepAll(document,
    'input[type="password"], ha-auth-flow, auth-form, ha-local-auth');
  return { title: document.title, url: location.href,
           lovelace: lovelace.length, cards: cards.length,
           errors: err, loginForm: login.length > 0 };
})()"""


def _probe(base: str, sid: str, wait_s: float) -> tuple[dict | None, str | None]:
    """Poll PROBE_JS until Lovelace content shows or the window ends.
    -> (last probe result, hard-fail reason | None)."""
    deadline = time.time() + wait_s
    last = None
    while time.time() < deadline:
        time.sleep(2.0)
        try:
            last = action(base, sid, "eval",
                          {"script": PROBE_JS}).get("result")
        except Exception:
            continue
        if last and last.get("lovelace") and last.get("cards"):
            break
        if last and last.get("loginForm"):
            return last, "login form shown — token rejected"
    return last, None


def run_smoke(base: str, url: str, token: str | None, wait_s: float,
              selector: str | None, views: list | None) -> dict:
    """One browser pass. -> verdict dict; raises on infra failure."""
    sess = rpc(base, "POST", "/sessions",
               {"type": "playwright-headless", "target": "local"})
    sid = sess["session_id"]
    try:
        origin = url.split("/", 3)[0] + "//" + url.split("/", 3)[2]
        if token:
            action(base, sid, "navigate", {"url": origin + "/"})
            time.sleep(1.5)
            expires = int(time.time() * 1000) + 10 * 365 * 86400 * 1000
            hass_tokens = {
                "access_token": token, "token_type": "Bearer",
                "expires_in": 10 * 365 * 86400, "expires": expires,
                "hassUrl": origin, "clientId": origin + "/",
                "refresh_token": ""}
            action(base, sid, "eval", {"script":
                "(() => { localStorage.setItem('hassTokens', "
                + json.dumps(json.dumps(hass_tokens))
                + "); return true; })()"})
        verdict = {"nav": action(base, sid, "navigate", {"url": url})}
        per_view = max(10.0, wait_s / max(1, len(views or []) + 1))
        last, hard = _probe(base, sid, per_view)
        verdict["probe"] = last
        if hard:
            verdict["fail"] = hard

        for v in views or []:
            action(base, sid, "navigate",
                   {"url": url.rstrip("/") + "/" + v.lstrip("/")})
            vlast, vhard = _probe(base, sid, per_view)
            verdict.setdefault("views", {})[v] = vlast
            if vhard:
                verdict.setdefault("view_fail", []).append(vhard)
            elif not (vlast or {}).get("cards"):
                verdict.setdefault("view_fail", []).append(
                    f"view '{v}' rendered no cards")

        shot = action(base, sid, "screenshot", {})
        verdict["screenshot_b64"] = shot.get("base64")
        if selector:
            sel_js = ("(() => { const deep=(r)=>{for(const e of "
                      "r.querySelectorAll('*')){if(e.matches&&e.matches"
                      f"({json.dumps(selector)}))return e;"
                      "if(e.shadowRoot){const x=deep(e.shadowRoot);"
                      "if(x)return x;}}}return null;}; "
                      "const el=deep(document);"
                      "if(!el)return null;const b=el.getBoundingClientRect"
                      "();return {w:b.width,h:b.height};})()")
            try:
                verdict["selector"] = action(
                    base, sid, "eval", {"script": sel_js}).get("result")
            except Exception as e:
                verdict["selector"] = {"error": str(e)}
        return verdict
    finally:
        try:
            rpc(base, "DELETE", f"/sessions/{sid}")
        except Exception:
            pass


def judge(verdict: dict, selector: str | None) -> tuple[bool, list]:
    last = verdict.get("probe")
    fails = []
    if verdict.get("fail"):
        # hard fail (e.g. token rejected) — the render checks would only be
        # noise on top of it
        fails.append(verdict["fail"])
    elif not last:
        fails.append("no successful DOM probe within the wait window")
    else:
        if not last.get("lovelace"):
            fails.append("no HA shell elements rendered "
                         "(ha-main/home-assistant absent)")
        if not last.get("cards"):
            fails.append("no Lovelace cards rendered")
        if last.get("errors"):
            fails.append(f"error cards: {last['errors']}")
    fails.extend(verdict.get("view_fail") or [])
    if selector and not (verdict.get("selector") or {}).get("w"):
        fails.append(f"--selector {selector!r} not found/visible")
    return not fails, fails


def board_comment(card_id: str, text: str) -> bool:
    payload = {"id": card_id, "from": "devin", "text": text}
    try:
        req = urllib.request.Request(
            BOARD_API + "/comment", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        eprint(f"dev-twin-smoke: board comment failed ({BOARD_API}): {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane")
    ap.add_argument("--inst")
    ap.add_argument("--url", help="ad-hoc URL — alone it browses with no "
                                "auth; combined with --inst it overrides "
                                "the registry url but keeps its auth "
                                "(e.g. tailnet URL for a loopback twin)")
    ap.add_argument("--dashboard", help="dashboard url_path or full path "
                                        "(default: lane dashboard / lovelace)")
    ap.add_argument("--views", help="comma view paths to check exist")
    ap.add_argument("--selector", help="extra deep-DOM selector to require")
    ap.add_argument("--card", help="kanban card id — posts [smoke] comms")
    ap.add_argument("--wait", type=float, default=45)
    args = ap.parse_args()

    base = playlived_url()
    reg = load_lanes() if LANES_FILE.exists() else {}

    if args.url and not (args.inst or args.lane):
        inst_id, inst = "ad-hoc", {"url": args.url}
        dash = args.dashboard or "lovelace"
    else:
        inst_id, inst = resolve_instance(reg, args)
        if inst.get("planned"):
            print(f"dev-twin-smoke: {inst_id} is registered but not "
                  f"provisioned (card ha-dev-instances) — gate cannot be "
                  "met yet")
            return 2
        if args.url:
            inst["url"] = args.url
        dash = args.dashboard or "lovelace"
        if args.lane and not args.dashboard:
            dash = (reg["lanes"][args.lane].get("dashboard")
                    or "lovelace")

    url = inst["url"].rstrip("/")
    code = "000"
    try:
        with urllib.request.urlopen(url + "/api/", timeout=8) as r:
            code = str(r.status)
    except urllib.error.HTTPError as e:
        code = str(e.code)
    except Exception:
        pass
    if code == "000":
        print(f"dev-twin-smoke: {inst_id} unreachable at {url}")
        return 2

    target = url + "/" + dash.lstrip("/")
    token = inst_token(inst) if inst.get("auth") else None
    if inst.get("auth") and not token:
        print(f"dev-twin-smoke: cannot resolve token for {inst_id} "
              f"({(inst.get('auth') or {}).get('kind')}) — page would show "
              "a login form")
        return 2

    try:
        rpc(base, "GET", "/health", timeout=8)
    except Exception as e:
        print(f"dev-twin-smoke: playlived unreachable at {base}: {e}")
        return 2

    print(f"dev-twin-smoke: {inst_id} {target} via {base}")
    views = [v.strip() for v in (args.views or "").split(",") if v.strip()]
    t0 = time.time()
    try:
        verdict = run_smoke(base, target, token, args.wait, args.selector,
                            views)
    except Exception as e:
        print(f"dev-twin-smoke: browser pass failed to run: {e}")
        return 2
    elapsed = round(time.time() - t0, 1)

    ok, fails = judge(verdict, args.selector)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png = None
    if verdict.get("screenshot_b64"):
        import base64
        png = OUT_DIR / f"{ts}-{inst_id}.png"
        png.write_bytes(base64.b64decode(verdict["screenshot_b64"]))
    report = OUT_DIR / f"{ts}-{inst_id}.json"
    slim = {k: v for k, v in verdict.items() if k != "screenshot_b64"}
    report.write_text(json.dumps(
        {"inst": inst_id, "url": target, "ok": ok, "fails": fails,
         "elapsed_s": elapsed, "verdict": slim}, indent=2))

    last = verdict.get("probe") or {}
    summary = (f"lovelace={last.get('lovelace')} cards={last.get('cards')} "
               f"title={last.get('title')!r}")
    line = (f"{'PASS' if ok else 'FAIL'} {inst_id} {target} "
            f"({elapsed}s): {summary}; fails={fails or 'none'}; "
            f"shot={png}")
    print("dev-twin-smoke: " + line)

    if args.card:
        tag = "[smoke] dev-twin pass" if ok else "[smoke] FAIL dev-twin"
        text = (f"{tag}: {inst_id} {target} — {summary}; "
                f"evidence {report} + {png}")
        posted = board_comment(args.card, text)
        print(f"dev-twin-smoke: comms {'posted' if posted else 'FAILED'} "
              f"-> {args.card}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
