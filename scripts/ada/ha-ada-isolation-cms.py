#!/usr/bin/env python3
"""L2 domain report: Ada -> HA isolation posture -> CMS pages (ada-cms-pages).

Index page `ha-ada-isolation` is a posture scorecard over the isolation
standard in docs/kb/ha-ada-isolation.md (the canonical prose — this page
is the live-status mirror). Leaf pages detail each vector so Tony, Ada,
and Devin read the same picture.

Sources (declared, not hand-written — ssot.reports.yml L1->L2):
  - docs/kb/ha-ada-isolation.md                        (canonical standard)
  - ssh idc03: env-key hashes, systemd unit caps        (live drift probes)
  - ssh idc03 + ada-pi venv: HA auth/current_user       (token identity)
  - scripts/deploy-ada.sh                               (deploy membership)

Usage:
  ha-ada-isolation-cms.py [--dry-run] [--slug iso-shared-fate]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("CHABA_REPO", "/home/tony/CascadeProjects/chaba"))
RUNBOOK = REPO / "docs/kb/ha-ada-isolation.md"
DEPLOY_SH = REPO.parent / "ada-pi/scripts/deploy-ada.sh"
if not DEPLOY_SH.exists():
    DEPLOY_SH = REPO / "../ada-pi/scripts/deploy-ada.sh"
MDDB = os.environ.get("MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
INDEX_SLUG = "ha-ada-isolation"
RUNBOOK_REF = "docs/kb/ha-ada-isolation.md"
CARD_REF = "kanban: ha-ada-isolation (HOM-0464)"

# Ada backends on idc03 -> their env file + the HA lane they act on.
BACKENDS = {
    "ada-ha-tony":    {"env": "ada-ha-tony.env",    "ha": "tony-ha",    "svc": "svc-ada"},
    "ada-ha-michael": {"env": "ada-ha-michael.env", "ha": "michael-ha", "svc": "svc-ada-michael"},
    "ada-kk":         {"env": "ada-kk.env",         "ha": "kk-ha",      "svc": "svc-kaewta"},
    "ada-dev":        {"env": "ada-dev.env",        "ha": None,         "svc": None},
    "ada-pi-pwa":     {"env": "ada-pi-pwa.env",     "ha": None,         "svc": None},
}

REMOTE_ENV_PROBE = r'''
import hashlib, json, glob, os
out = {}
for f in sorted(glob.glob(os.path.expanduser("~/.config/secrets/ada-*.env"))):
    name = os.path.basename(f)
    d = {}
    for l in open(f):
        if "=" in l and not l.startswith("#"):
            k, v = l.split("=", 1)
            d[k.strip()] = v.strip()
    out[name] = {
        "has_ha": bool(d.get("HOME_ASSISTANT_TOKEN")),
        "ha_url": d.get("HOME_ASSISTANT_URL") or None,
        "gemini": hashlib.sha256((d.get("GEMINI_API_KEY") or "").encode()).hexdigest()[:10] or None,
        "gemini_fb": bool(d.get("GEMINI_API_KEY_")),
        "excluded": bool((d.get("ADA_EXCLUDED_TOOLS") or "").strip()),
        "instance": d.get("ADA_INSTANCE_ID") or None,
    }
print(json.dumps(out))
'''

REMOTE_USER_PROBE = r'''
import json, asyncio, websockets, sys
env = {}
for l in open(sys.argv[1]):
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); env[k.strip()] = v.strip()
url = env["HOME_ASSISTANT_URL"].rstrip("/").replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
async def main():
    try:
        async with websockets.connect(url, open_timeout=8) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "auth", "access_token": env["HOME_ASSISTANT_TOKEN"]}))
            r = json.loads(await ws.recv())
            if r.get("type") != "auth_ok":
                print(json.dumps({"error": "auth_failed"})); return
            await ws.send(json.dumps({"id": 1, "type": "auth/current_user"}))
            u = json.loads(await ws.recv()).get("result", {})
            print(json.dumps({"name": u.get("name"), "is_owner": u.get("is_owner"),
                              "is_admin": u.get("is_admin")}))
    except Exception as e:
        print(json.dumps({"error": str(e)[:120]}))
asyncio.run(main())
'''


def _ssh(host, cmd, input_text=None, timeout=30):
    try:
        p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
                            host, cmd], capture_output=True, text=True,
                           input=input_text, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except Exception as e:
        return f"ssh error: {e}"


def _ssh_json(host, cmd, input_text=None, timeout=30):
    raw = _ssh(host, cmd, input_text=input_text, timeout=timeout)
    try:
        return json.loads(raw.strip().splitlines()[-1])
    except Exception:
        return {"error": raw[:160]}


def probe_envs():
    return _ssh_json("idc03", "python3", input_text=REMOTE_ENV_PROBE)


def probe_user(env_file):
    return _ssh_json("idc03",
                     "~/CascadeProjects/ada-pi/.venv/bin/python - "
                     f"~/.config/secrets/{env_file}",
                     input_text=REMOTE_USER_PROBE, timeout=30)


def probe_units():
    units = " ".join(BACKENDS)
    raw = _ssh("idc03",
               f"systemctl --user show {units} -p Id,ActiveState,"
               "MemoryMax,CPUQuotaPerSecUSec,LogRateLimitIntervalUSec,"
               "LogRateLimitBurst 2>/dev/null")
    out = {}
    for block in raw.split("\n\n"):
        props = dict(l.split("=", 1) for l in block.splitlines() if "=" in l)
        uid = props.get("Id", "").replace(".service", "")
        if uid:
            props["unit"] = uid
            out[uid] = props
    return out


def deploy_services():
    try:
        txt = DEPLOY_SH.read_text()
        m = re.search(r'SERVICES="\$\{ADA_SERVICES:-([^}]+)\}"', txt)
        return m.group(1).split() if m else []
    except Exception:
        return []


def assess(envs, units, users, services):
    """Evaluate the six isolation controls against live probes."""
    controls = []

    # 1. dedicated non-admin HA user
    worst, detail = "n/a", []
    for bid, b in BACKENDS.items():
        if not b["ha"]:
            continue
        u = users.get(bid) or {}
        if u.get("error"):
            detail.append(f"{bid}: probe error ({u['error']})")
            continue
        if not u:
            detail.append(f"{bid}: no HA credentials in env")
            continue
        who = u.get("name", "?")
        priv = "OWNER" if u.get("is_owner") else ("admin" if u.get("is_admin") else "non-admin")
        ok = not u.get("is_owner") and not u.get("is_admin")
        detail.append(f"{bid} -> {b['ha']}: token user **{who}** ({priv})")
        if not ok:
            worst = "fail"
    if worst == "n/a":
        worst = "ok"
    controls.append(("Dedicated non-admin `svc-*` HA user per lane",
                     worst, "; ".join(detail) or "no HA-bound backends"))

    # 2. per-instance gemini key
    hashes = {}
    for env, d in envs.items():
        if d.get("gemini"):
            hashes.setdefault(d["gemini"], []).append(env)
    if len(hashes) <= 1 and hashes:
        st = "fail"
        msg = f"all {sum(map(len, hashes.values()))} envs share one key (hash {next(iter(hashes))})"
    else:
        st = "ok" if all(len(v) == 1 for v in hashes.values()) else "partial"
        msg = "; ".join(f"{k[:6]}: {len(v)} envs" for k, v in hashes.items())
    controls.append(("Per-instance `GEMINI_API_KEY`", st, msg))

    # 3. cgroup caps
    capped = sum(1 for u in units.values()
                 if u.get("MemoryMax") not in (None, "infinity"))
    st = "ok" if capped == len(BACKENDS) else ("partial" if capped else "fail")
    controls.append(("Cgroup caps on ada units (MemoryMax/CPUQuota)",
                     st, f"{capped}/{len(BACKENDS)} units capped"))

    # 4. deploy membership explicit
    missing = [b for b in BACKENDS if b not in services]
    st = "ok" if not missing else "partial"
    controls.append(("Deploy-set membership explicit (deploy-ada.sh SERVICES)",
                     st, f"absent: {', '.join(missing)}" if missing else "all in SERVICES"))

    # 5. actuation allowlist
    bare = [bid for bid, b in BACKENDS.items()
            if envs.get(b["env"], {}).get("has_ha")
            and not envs.get(b["env"], {}).get("excluded")]
    controls.append(("Actuation allowlist (`ADA_EXCLUDED_TOOLS` / no upstream)",
                     "partial" if bare else "ok",
                     f"HA-bound lanes without explicit exclusions: {', '.join(bare)}"
                     if bare else "all HA-bound lanes scoped"))

    # 6. journal caps
    jc = sum(1 for u in units.values()
             if u.get("LogRateLimitIntervalUSec") not in (None, "0", "0s"))
    st = "ok" if jc == len(BACKENDS) else ("partial" if jc else "fail")
    controls.append(("Journal rate caps on ada units",
                     st, f"{jc}/{len(BACKENDS)} units capped"))

    return controls, hashes


COUPLING = [
    ("ada-ha-tony", "idc03:8002", "tony-ha (tailnet :8123)", "Tony OWNER LLAT",
     "REST /api/states+services (light/switch/fan/input_boolean/cover/button/media_player) + ~5s poller"),
    ("ada-ha-michael", "idc03:8003", "michael-ha (tailnet)", "Michael LLAT", "same tool set"),
    ("ada-kk", "idc03:8007", "kk-ha — no creds in env", "—", "voice card browser→/ada-ws/kk only"),
    ("ada-dev", "idc03:8005", "none (upstream removed)", "—", "HA tools excluded"),
    ("ada-pi-pwa", "idc03:8001", "tony-ha (tailnet)", "Tony OWNER LLAT",
     "full tool set — only 2 exclusions (habit tools)"),
]

WHATIF = [
    ("Gemini quota/reconnect storm", "all 5 lanes starve on the shared key",
     "only the offending lane; breaker stops the storm"),
    ("Tool-call / actuation loop", "can toggle real devices on prod tony-ha with owner perms",
     "non-admin svc token + allowlisted domains + logbook attribution"),
    ("Ada HA token leak / rotation", "owner token = full prod admin; revocation breaks co-users",
     "svc token only; revoke kills Ada and nothing else"),
    ("Bad ada-pi deploy", "every backend restarts onto broken code; ada-kk silently stays old",
     "canary order catches it on ada-dev; membership explicit"),
    ("Ada mem/cpu leak on idc03", "starves kk-ha + michael-dev + mddb",
     "cgroup caps contain it"),
    ("Ada log storm", "can fill idc03 disk → whole host",
     "per-unit journal caps"),
    ("idc03 host dies", "kk-ha dies anyway (co-located) — accepted risk",
     "same; tony-ha unaffected (on tony-dell)"),
    ("tony-dell / tailnet down", "ada orphaned; bounded retries (5s timeouts)",
     "same — harmless error churn"),
    ("Ada stopped / killed", "voice card + CMS iframes blank; HA control untouched",
     "same — verify via kill-switch leaf"),
]

KILLSWITCH = [
    ("`ssh idc03 'systemctl --user stop ada-ha-<lane>'`", "seconds, reversible"),
    ("HA UI → svc user → delete its LLAT", "hard sever, survives ada restarts"),
    ("blank `HOME_ASSISTANT_URL`/`TOKEN` in the lane env + restart", "config sever"),
    ("`systemctl --user disable --now`", "survives reboots"),
]

BADGE = {"ok": "PASS", "partial": "PART", "fail": "FAIL", "n/a": "n/a"}


def _md_link(slug, text):
    return f"[{text}]({slug})"


def index_page(controls, units, now):
    score = sum(1 for _, s, _ in controls if s == "ok")
    lines = [
        "# Ada → HA isolation posture", "",
        f"**{score}/6 controls passing** — canonical standard: "
        f"`{RUNBOOK_REF}` · tracked on {CARD_REF}", "",
        "## Isolation standard", "",
        "| # | Control | Status | Live check |", "|---|---|---|---|",
    ]
    for i, (name, st, detail) in enumerate(controls, 1):
        lines.append(f"| {i} | {name} | **{BADGE[st]}** | {detail} |")
    lines += ["", "## Lane state (systemd on idc03)", "",
              "| Backend | Active | MemoryMax | CPUQuota | Journal cap |",
              "|---|---|---|---|---|"]
    for bid in BACKENDS:
        u = units.get(bid, {})
        mm = u.get("MemoryMax", "?")
        cq = u.get("CPUQuotaPerSecUSec", "?")
        jl = u.get("LogRateLimitIntervalUSec", "?")
        lines.append(f"| `{bid}` | `{u.get('ActiveState', '?')}` | `{mm}` | `{cq}` | `{jl}` |")
    lines += ["", "## Leaves", "",
              f"- {_md_link('iso-coupling', 'Coupling map')} — who can reach which HA, with what credential",
              f"- {_md_link('iso-shared-fate', 'Shared-fate vectors')} — one failure, all lanes",
              f"- {_md_link('iso-whatif', 'What-if matrix')} — 9 scenarios, before/after",
              f"- {_md_link('iso-killswitch', 'Kill switch')} — fastest-first severance",
              "",
              "## Open decisions (card requests)", "",
              "1. Gemini key split — shared key vs two pools vs per-instance",
              "2. ada-kk deploy-set membership — add vs pinned",
              "3. Phase B approval — `svc-ada` on prod tony-ha",
              "",
              f"*Generated by ha-ada-isolation-cms.py · {now}*"]
    return "\n".join(lines)


def coupling_page(users, units, now):
    lines = ["# Coupling map — Ada backends → HA", "",
             "| Backend | Listen | Upstream HA | Credential | Surface |",
             "|---|---|---|---|---|"]
    for row in COUPLING:
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## Token identity (live `auth/current_user`)", ""]
    for bid, u in users.items():
        if not u:
            lines.append(f"- `{bid}`: no `HOME_ASSISTANT_*` in env — backend cannot call HA")
        elif u.get("error"):
            lines.append(f"- `{bid}`: probe error — {u['error']}")
        else:
            priv = "OWNER" if u.get("is_owner") else ("admin" if u.get("is_admin") else "non-admin")
            flag = " ⚠️" if u.get("is_owner") or u.get("is_admin") else ""
            lines.append(f"- `{bid}`: user **{u.get('name')}** — {priv}{flag}")
    lines += ["",
              "HA → Ada direction: clean (no rest_command/shell_command in "
              "tony-ha config; voice cards + CMS iframes fail soft).", "",
              f"*Generated by ha-ada-isolation-cms.py · {now} · parent: {INDEX_SLUG}*"]
    return "\n".join(lines)


def shared_fate_page(hashes, services, envs, now):
    lines = ["# Shared-fate vectors", "",
             "## Gemini key sharing (live hash groups)", ""]
    for h, env_list in hashes.items():
        flag = " ⚠️ shared pool" if len(env_list) > 1 else ""
        lines.append(f"- `{h}` → {', '.join(env_list)}{flag}")
    lines += ["", "## Deploy set (deploy-ada.sh SERVICES)", "",
              f"`{' '.join(services) or '?'}`", ""]
    for bid in BACKENDS:
        mark = "in set" if bid in services else "**ABSENT — drifts old code**"
        lines.append(f"- `{bid}`: {mark}")
    lines += ["", "## Co-location on idc03", "",
              "All ada backends + mddb + kk-ha + michael-dev share the host. "
              "Unit caps: see index scorecard row 3.", "",
              f"*Generated by ha-ada-isolation-cms.py · {now} · parent: {INDEX_SLUG}*"]
    return "\n".join(lines)


def whatif_page(now):
    lines = ["# What-if matrix", "",
             "| Scenario | Blast today | After standard |", "|---|---|---|"]
    for s, b, a in WHATIF:
        lines.append(f"| {s} | {b} | {a} |")
    lines += ["", f"Canonical text: `{RUNBOOK_REF}`", "",
              f"*Generated by ha-ada-isolation-cms.py · {now} · parent: {INDEX_SLUG}*"]
    return "\n".join(lines)


def killswitch_page(now):
    lines = ["# Kill switch — fastest first", ""]
    lines += [f"{i}. {cmd} — {note}" for i, (cmd, note)
              in enumerate(KILLSWITCH, 1)]
    lines += ["", "## Verify isolation holds", "", "```bash",
              "ssh idc03 'systemctl --user stop ada-ha-tony'",
              "curl -sf https://tony-dell.taila0626a.ts.net:8123/api/ && echo ok",
              "```", "",
              f"*Generated by ha-ada-isolation-cms.py · {now} · parent: {INDEX_SLUG}*"]
    return "\n".join(lines)


def publish(slug, title, content, extra, now):
    meta = {
        "attribute": ["page"], "bank": ["cms"], "domain": ["infra"],
        "format": ["markdown"], "instance": ["ada"], "kind": ["page"],
        "lang": ["en"], "scope": ["tony"], "slug": [slug], "source": ["api"],
        "status": ["active"], "subject": [slug], "title": [title],
        "updated": [now], "valid_from": [now[:10]], "last_verified": [now[:10]],
        "written_by": ["ha-ada-isolation-cms"],
        "generated_by": ["ha-ada-isolation-cms.py"],
        "sources": ["docs/kb/ha-ada-isolation.md", "systemctl",
                    "ada env key-hashes", "auth/current_user", "deploy-ada.sh"],
    }
    meta.update(extra)
    body = json.dumps({"collection": COLLECTION, "key": slug, "lang": "en",
                       "contentMd": content, "meta": meta}).encode()
    req = urllib.request.Request(f"{MDDB}/add", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slug")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    envs = probe_envs()
    units = probe_units()
    services = deploy_services()
    users = {}
    for bid, b in BACKENDS.items():
        if envs.get(b["env"], {}).get("has_ha"):
            users[bid] = probe_user(b["env"])
        else:
            users[bid] = None
    controls, hashes = assess(envs, units, users, services)

    pages = {
        "iso-coupling":    ("Isolation — coupling map",   coupling_page(users, units, now)),
        "iso-shared-fate": ("Isolation — shared fate",    shared_fate_page(hashes, services, envs, now)),
        "iso-whatif":      ("Isolation — what-if matrix", whatif_page(now)),
        "iso-killswitch":  ("Isolation — kill switch",    killswitch_page(now)),
    }
    if not args.slug:
        leaf_slugs = list(pages)
        pages[INDEX_SLUG] = ("Ada → HA isolation posture",
                             index_page(controls, units, now))
    else:
        pages = {k: v for k, v in pages.items() if k == args.slug}

    failed = 0
    for slug, (title, content) in pages.items():
        extra = {"report_role": ["index" if slug == INDEX_SLUG else "leaf"]}
        if slug == INDEX_SLUG:
            extra["children"] = leaf_slugs
        else:
            extra["parent"] = [INDEX_SLUG]
        if args.dry_run:
            print(f"--- {slug} ({len(content)} chars) ---\n{content}\n")
        else:
            try:
                code = publish(slug, title, content, extra, now)
                print(f"{slug}: HTTP {code} ({len(content)} chars)")
            except Exception as e:
                print(f"{slug}: PUBLISH FAIL {e}", file=sys.stderr)
                failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
