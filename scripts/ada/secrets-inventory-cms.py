#!/usr/bin/env python3
"""L2 domain report: fleet secrets inventory -> CMS pages (ada-cms-pages).

Index `secrets-inventory` + per-host leaves + a shared-pool/rotation leaf.
Answers: which keys exist where, are they live, which are shared (blast
radius), and when do they expire.

HARD RULE: full secret values never leave their host. Each remote probe
runs locally over ssh and returns only masked values + sha256[:8]
fingerprints. This script (and the pages it publishes) never sees a key.

Sources:
  - ~/.config/secrets/* on each host  (env files + bare-token files)
  - openrouter.ai /auth/key probed FROM the host holding the key
  - generativelanguage models?key= probed the same way
  - consumer map below (from ssot.services.yml env_file references)

Usage:
  secrets-inventory-cms.py [--dry-run] [--slug secrets-idc03]
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
INDEX_SLUG = "secrets-inventory"

HOSTS = ["tony-dell", "tony-omen", "idc03", "tony-macbook"]

# service -> secret file it reads (from ssot.services.yml env_file refs)
CONSUMERS = {
    "openrouter.env":   "openclaw/ghostroute (per-host copy)",
    "mddb-gemini.env":  "mddb embeddings + gemini-ollama-proxy + litellm",
    "ada-ha-tony.env":  "ada-ha-tony.service",
    "ada-ha-michael.env": "ada-ha-michael.service",
    "ada-kk.env":       "ada-kk.service (Kaewta/kk-ha lane)",
    "ada-dev.env":      "ada-dev.service",
    "ada-pi-pwa.env":   "ada-pi-pwa.service",
    "line-bot.env":     "ada-line-relay.service",
    "telegram-ada.env": "ada-tg-relay.service",
    "telegram-kk.env":  "ada-tg-relay-kk.service",
    "ha-michael-dev.env": "devin/agent HA token (michael-dev)",
    "or-next-key":      "rotation input — rotate-or-key.sh",
    "kaewta-paid.env":  "kk-ha lane paid-tier credential (unidentified bare token)",
    "notebooklm-rest-api.env": "ada backends (shared env file)",
}

REMOTE_INVENTORY = r'''
import os, json, glob, hashlib, re
out = []
paths = sorted(glob.glob(os.path.expanduser("~/.config/secrets/*")))
for extra in ("~/or-next-key",):
    p = os.path.expanduser(extra)
    if os.path.exists(p):
        paths.append(p)
for f in paths:
    if not os.path.isfile(f):
        continue
    rec = {"file": os.path.basename(f), "mtime": int(os.path.getmtime(f)), "vars": []}
    try:
        txt = open(f, errors="replace").read()
    except Exception as e:
        rec["error"] = str(e)[:80]; out.append(rec); continue
    is_env = "=" in txt and not f.endswith((".json", ".key", ".sqlite", ".pem"))
    if not is_env:
        # token/JSON/binary file — one row, no line-by-line spill
        toks = re.findall(r"(sk-or-v1-[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]{20,})", txt)
        if toks:
            v = toks[0]
            rec["vars"].append({"name": "<bare-token>", "masked": v[:6]+"…"+v[-4:],
                                "fp": hashlib.sha256(v.encode()).hexdigest()[:8]})
        else:
            rec["vars"].append({"name": "<file>", "masked": "<%d bytes>" % len(txt),
                                "fp": None})
        out.append(rec); continue
    n_config = 0
    for line in txt.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            m = re.search(r"(sk-or-v1-[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9_.-]{10,})", s)
            if m:
                v = m.group(1)
                rec["vars"].append({"name": "<bare-token>", "masked": v[:6]+"…"+v[-4:],
                                    "fp": hashlib.sha256(v.encode()).hexdigest()[:8]})
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if not v:
            continue
        if re.search(r"key|token|secret|pass|auth|api", k, re.I):
            fp = hashlib.sha256(v.encode()).hexdigest()[:8]
            if len(v) <= 20:
                masked = "<short>"
            elif any(c in v for c in " {}[]"):
                masked = "<structured>"
            else:
                masked = v[:6] + "…" + v[-4:]
            rec["vars"].append({"name": k, "masked": masked, "fp": fp})
        else:
            n_config += 1
    if n_config:
        rec["vars"].append({"name": f"<{n_config} config vars>", "masked": "", "fp": None})
    if not rec["vars"]:
        rec["vars"].append({"name": "<empty>", "masked": "", "fp": None})
    out.append(rec)
print(json.dumps(out))
'''

# Live validity probes — run ON the host so keys never leave it.
# Returns {fingerprint: {masked, kind, status, label, expires, usage, limit}}
REMOTE_LIVECHECK = r'''
import os, glob, json, re, hashlib, urllib.request
seen = {}
files = glob.glob(os.path.expanduser("~/.config/secrets/*"))
def probe_or(k, fp):
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": "Bearer " + k})
        d = json.loads(urllib.request.urlopen(req, timeout=12).read())["data"]
        return {"kind": "openrouter", "status": "valid", "label": d.get("label"),
                "expires": d.get("expires_at"), "usage": d.get("usage"),
                "limit": d.get("limit")}
    except urllib.error.HTTPError as e:
        return {"kind": "openrouter", "status": f"HTTP {e.code}"}
    except Exception as e:
        return {"kind": "openrouter", "status": "probe-error " + str(e)[:60]}
def probe_gemini(k, fp):
    try:
        u = "https://generativelanguage.googleapis.com/v1beta/models?key=" + k + "&pageSize=1"
        urllib.request.urlopen(urllib.request.Request(u), timeout=12).read()
        return {"kind": "gemini", "status": "valid"}
    except urllib.error.HTTPError as e:
        return {"kind": "gemini", "status": f"HTTP {e.code}"}
    except Exception as e:
        return {"kind": "gemini", "status": "probe-error " + str(e)[:60]}
for f in files:
    if not os.path.isfile(f):
        continue
    try:
        txt = open(f, errors="replace").read()
    except Exception:
        continue
    for m in re.finditer(r"sk-or-v1-[A-Za-z0-9_-]+", txt):
        k = m.group(0); fp = hashlib.sha256(k.encode()).hexdigest()[:8]
        if fp not in seen:
            r = probe_or(k, fp); r["masked"] = k[:10] + "…" + k[-4:]; seen[fp] = r
    for m in re.finditer(r"(?:GEMINI_API_KEY_?|GOOGLE_API_KEY)=(AIza[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9_.-]{20,})", txt):
        k = m.group(1); fp = hashlib.sha256(k.encode()).hexdigest()[:8]
        if fp not in seen:
            r = probe_gemini(k, fp); r["masked"] = k[:10] + "…" + k[-4:]; seen[fp] = r
print(json.dumps(seen))
'''


def _ssh_json(host, input_text, timeout=90):
    if host == "tony-macbook":
        cmd = ["python3"]
    else:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", host, "python3"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           input=input_text, timeout=timeout)
        raw = (p.stdout or "").strip()
        if not raw:
            return {"error": (p.stderr or "no output")[:160]}
        return json.loads(raw.strip().splitlines()[-1])
    except Exception as e:
        return {"error": str(e)[:160]}


def _md_link(slug, text):
    return f"[{text}]({slug})"


def host_page(host, files, now):
    lines = [f"# Secrets inventory — {host}", "",
             "| File | Var | Masked | fp | mtime | Consumer |",
             "|---|---|---|---|---|---|"]
    for rec in files:
        mtime = datetime.fromtimestamp(rec["mtime"], timezone.utc).strftime("%Y-%m-%d %H:%M")
        consumer = CONSUMERS.get(rec["file"], "")
        if rec.get("error"):
            lines.append(f"| `{rec['file']}` | — | — | — | {mtime} | {consumer} |")
            continue
        for v in rec["vars"]:
            lines.append(f"| `{rec['file']}` | `{v['name']}` | `{v['masked']}` "
                         f"| `{v.get('fp') or ''}` | {mtime} | {consumer} |")
    lines += ["", f"*Generated by secrets-inventory-cms.py · {now} · parent: {INDEX_SLUG}*"]
    return "\n".join(lines)


def rotation_page(live, now):
    lines = ["# Key rotation & validity", "",
             "Live checks run on the host holding each key — values never leave.",
             "",
             "## OpenRouter keys", "",
             "| Key | Label | Status | Expires | Usage / Limit |",
             "|---|---|---|---|---|"]
    for fp, r in sorted(live.items(), key=lambda kv: kv[1].get("masked", "")):
        if r.get("kind") != "openrouter":
            continue
        exp = (r.get("expires") or "—")[:16]
        use = f"{r.get('usage')} / {r.get('limit')}" if r.get("usage") is not None else "—"
        flag = " ⚠️" if str(r.get("status")) != "valid" else ""
        lines.append(f"| `{r.get('masked')}` `{fp}` | {r.get('label') or '—'} "
                     f"| {r.get('status')}{flag} | {exp} | {use} |")
    lines += ["", "## Gemini keys", "", "| Key | Status |", "|---|---|"]
    for fp, r in sorted(live.items(), key=lambda kv: kv[1].get("masked", "")):
        if r.get("kind") != "gemini":
            continue
        flag = " ⚠️" if str(r.get("status")) != "valid" else ""
        lines.append(f"| `{r.get('masked')}` `{fp}` | {r.get('status')}{flag} |")
    lines += ["", f"*Generated by secrets-inventory-cms.py · {now} · parent: {INDEX_SLUG}*"]
    return "\n".join(lines)


def shared_page(all_vars, now):
    """all_vars: {host: [(file, var, masked, fp)]} — dedup by fingerprint."""
    groups = {}
    for host, rows in all_vars.items():
        for f, name, masked, fp in rows:
            if fp:
                groups.setdefault(fp, []).append((host, f, name, masked))
    lines = ["# Shared secrets — same value in multiple places", "",
             "| fp | Masked | Locations |", "|---|---|---|"]
    for fp, locs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(locs) < 2:
            continue
        where = "<br>".join(f"{h}:`{f}`:{n}" for h, f, n, _ in locs)
        flag = " ⚠️" if len(locs) > 2 else ""
        lines.append(f"| `{fp}` | `{locs[0][3]}`{flag} | {where} |")
    singles = sum(1 for v in groups.values() if len(v) == 1)
    lines += ["", f"*{singles} unique keys not shared. "
              "Shared = rotation must hit every store or split brain.*", "",
              f"*Generated by secrets-inventory-cms.py · {now} · parent: {INDEX_SLUG}*"]
    return "\n".join(lines)


def index_page(hosts_data, live, shared_count, now):
    lines = ["# Secrets inventory", "",
             "Masked fingerprints only — values never left their host.", "",
             "| Host | Files | Secret vars | Probe |", "|---|---|---|---|"]
    total_files = total_vars = 0
    for host, files in hosts_data.items():
        if isinstance(files, dict) and files.get("error"):
            lines.append(f"| {host} | — | — | {files['error']} |")
            continue
        nvars = sum(len(r["vars"]) for r in files)
        nsec = sum(1 for r in files for v in r["vars"] if v.get("fp"))
        total_files += len(files); total_vars += nsec
        lines.append(f"| {_md_link('secrets-' + host, host)} | {len(files)} "
                     f"| {nsec}/{nvars} | ok |")
    n_or = sum(1 for r in live.values() if r.get("kind") == "openrouter" and r.get("status") == "valid")
    n_or_bad = sum(1 for r in live.values() if r.get("kind") == "openrouter" and r.get("status") != "valid")
    n_ge = sum(1 for r in live.values() if r.get("kind") == "gemini")
    lines += ["", f"**{total_vars} secret vars across {total_files} files** — "
              f"OR keys live: {n_or} valid / {n_or_bad} broken · "
              f"gemini keys probed: {n_ge} · "
              f"shared fingerprints: {shared_count}", "",
              "## Leaves", "",
              f"- {_md_link('secrets-rotation', 'Rotation & validity')} — live expiry/usage per key",
              f"- {_md_link('secrets-shared', 'Shared pools')} — same key in multiple stores",
              "",
              "## Notes", "",
              "- `or-next-key` on dell is the rotation input file — should be absent between rotations",
              "- cadence changed weekly→daily 2026-10-12: Tony mints a fresh OR key daily",
              "- kaewta-daily OR key (…3c966) now wired into ada-kk.env — per-lane budget tracking",
              "",
              f"*Generated by secrets-inventory-cms.py · {now}*"]
    return "\n".join(lines)


def publish(slug, title, content, extra, now):
    meta = {
        "attribute": ["page"], "bank": ["cms"], "domain": ["infra"],
        "format": ["markdown"], "instance": ["ada"], "kind": ["page"],
        "lang": ["en"], "scope": ["tony"], "slug": [slug], "source": ["api"],
        "status": ["active"], "subject": [slug], "title": [title],
        "updated": [now], "valid_from": [now[:10]], "last_verified": [now[:10]],
        "written_by": ["secrets-inventory-cms"],
        "generated_by": ["secrets-inventory-cms.py"],
        "sources": ["~/.config/secrets/* per host (masked on-host)",
                    "openrouter /auth/key", "gemini models?key="],
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

    hosts_data, live = {}, {}
    all_vars = {}
    for host in HOSTS:
        inv = _ssh_json(host, REMOTE_INVENTORY)
        hosts_data[host] = inv
        if isinstance(inv, list):
            all_vars[host] = [(r["file"], v["name"], v["masked"], v.get("fp"))
                              for r in inv for v in r["vars"]]
        lc = _ssh_json(host, REMOTE_LIVECHECK, timeout=120)
        if isinstance(lc, dict) and not lc.get("error"):
            live.update(lc)

    shared_count = 0
    fp_hosts = {}
    for host, rows in all_vars.items():
        for _, _, _, fp in rows:
            if fp:
                fp_hosts.setdefault(fp, set()).add((host,))
    shared_count = sum(1 for s in fp_hosts.values() if len(s) > 1)

    pages = {f"secrets-{h}": (f"Secrets — {h}", host_page(h, files, now))
             for h, files in hosts_data.items() if isinstance(files, list)}
    pages["secrets-rotation"] = ("Secrets — rotation & validity",
                                 rotation_page(live, now))
    pages["secrets-shared"] = ("Secrets — shared pools",
                               shared_page(all_vars, now))
    if not args.slug:
        leaf_slugs = list(pages)
        pages[INDEX_SLUG] = ("Secrets inventory",
                             index_page(hosts_data, live, shared_count, now))
    else:
        pages = {k: v for k, v in pages.items() if k == args.slug}
        leaf_slugs = []

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
