#!/usr/bin/env python3
"""Execute round-2 inbox triage: MDDB writes + remote file plan.

Usage: execute.py [--apply]   (default: dry-run, prints plan)
"""
import json, sys, urllib.request, importlib.util, re
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from decisions import D, ORPHANS, NEW_DOCS

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ada_sync", ROOT / "scripts/ada/sync-ada-memory-to-mddb.py")
ada_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ada_sync)

MDDB = "http://100.74.146.0:11023/v1"
TODAY = date.today().isoformat()
APPLY = "--apply" in sys.argv

# bank -> (collection, vault dir, scope)
BANKMAP = {
 "general": ("ada-ha-bank-general", "general", "shared"),
 "people": ("ada-ha-bank-people", "people", "shared"),
 "purchase": ("ada-ha-bank-purchase", "purchase", "shared"),
 "note": ("ada-ha-bank-note-tony", "note", "tony"),
 "personal": ("ada-ha-bank-personal-tony", "personal/tony", "tony"),
 "personal-kk": ("ada-ha-bank-personal-kk", "personal-kk", "shared"),
 "personal-testo": ("ada-ha-bank-personal-testo", "personal-testo", "shared"),
 "tony-projects": ("ada-ha-bank-projects-tony", "tony-projects", "tony"),
 "developer": ("ada-ha-bank-developer-tony", None, "tony"),
}

def post(path, payload):
    req = urllib.request.Request(MDDB + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def mddb_add(coll, key, content, meta):
    if APPLY:
        post("/add", {"collection": coll, "key": key, "lang": "en",
                      "contentMd": content, "meta": meta})

drafts = json.load(open(ROOT / ".triage/drafts.json"))
by_bank_key = {}
for ck, v in drafts.items():
    coll, key = ck.split("||")
    by_bank_key[(v["bank"], key)] = v

fm_re = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

def promote_meta(bank, scope, fm, today=TODAY):
    return ada_sync.build_meta(fm, bank, scope, today)

file_ops = []   # (action, src, dst)
stats = {"K": 0, "P": 0, "S": 0, "R": 0, "skip": 0}

for bank, dm in D.items():
    if bank in ("devin-handoff", "ideas") or not dm:
        continue
    coll, vdir, scope = BANKMAP[bank]
    for key, dec in dm.items():
        doc = by_bank_key.get((bank, key))
        if doc is None:
            print(f"!! no doc for {bank}/{key}"); stats["skip"] += 1; continue
        meta = dict(doc["meta"])
        slug = key.split("/", 1)[-1]
        # inbox file path (bank-level dir; personal uses inbox/personal)
        inbox_dir = {"personal": "personal"}.get(bank, bank)
        src = f"inbox/{inbox_dir}/{slug}.md"
        dst = f"{vdir}/{slug}.md" if vdir else None
        if dec == "K" or dec == "P":
            fm = {"kind": meta.get("kind", ["note"])[0], "status": "active",
                  "valid_from": meta.get("valid_from", [TODAY])[0],
                  "last_verified": TODAY}
            for f in ("subject", "attribute", "valid_until", "applies_to",
                      "supersedes", "superseded_by", "retracted_reason",
                      "source", "written_by"):
                if meta.get(f):
                    fm[f] = meta[f][0] if len(meta[f]) == 1 else meta[f]
            fm["source"] = meta.get("source", ["voice"])[0]
            fm["written_by"] = meta.get("written_by", ["ada_remember"])[0]
            new_meta = promote_meta(bank, scope, fm)
            mddb_add(coll, key, doc["content"], new_meta)
            stats[dec] += 1
            if dst:
                file_ops.append(("promote", src, dst,
                                 (new_meta, doc["content"], key)))
        elif dec.startswith("S:"):
            meta["status"] = ["superseded"]
            meta["superseded_by"] = [dec[2:]]
            mddb_add(coll, key, doc["content"], meta)
            stats["S"] += 1
            file_ops.append(("rm", src, None, None))
        elif dec.startswith("R:"):
            meta["status"] = ["retracted"]
            meta["retracted_reason"] = [f"inbox triage 2026-10-04: {dec[2:]}"]
            mddb_add(coll, key, doc["content"], meta)
            stats["R"] += 1
            file_ops.append(("rm", src, None, None))

import yaml
# Fetch orphan file contents over SSH
import subprocess
def cat(path):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "idc01",
                        f"cat ~/CascadeProjects/chaba-vault/docs/ada-memory/{path}"],
                       capture_output=True, text=True, timeout=30)
    return r.stdout

for f, dec in ORPHANS.items():
    if dec == "L":
        continue
    p = Path(f)
    bank = p.parent.name
    coll, vdir, scope = BANKMAP[bank]
    txt = cat(f)
    m = fm_re.match(txt)
    fm = yaml.safe_load(m.group(1)) if m else {}
    body = m.group(2).strip() if m else txt.strip()
    key = (fm or {}).get("key") or f"{bank}/{p.stem}"
    if dec == "K":
        fm2 = dict(fm or {})
        fm2["status"] = "active"
        fm2.setdefault("kind", "note")
        fm2.setdefault("valid_from", TODAY)
        fm2["last_verified"] = TODAY
        new_meta = promote_meta(bank, scope, fm2)
        mddb_add(coll, key, body, new_meta)
        file_ops.append(("promote", f, f"{vdir}/{p.name}", (new_meta, body, key)))
        stats["K"] += 1
    elif dec.startswith("S:"):
        meta = ada_sync.build_meta({**(fm or {}), "status": "superseded",
                                    "superseded_by": dec[2:]}, bank, scope, TODAY)
        mddb_add(coll, key, body, meta)
        file_ops.append(("rm", f, None, None))
        stats["S"] += 1
    elif dec.startswith("R:"):
        meta = ada_sync.build_meta({**(fm or {}), "status": "retracted",
                                    "retracted_reason": f"inbox triage 2026-10-04: {dec[2:]}"},
                                   bank, scope, TODAY)
        mddb_add(coll, key, body, meta)
        file_ops.append(("rm", f, None, None))
        stats["R"] += 1

# NEW_DOCS: create doc + vault file
for nd in NEW_DOCS:
    coll, vdir, scope = BANKMAP[nd["bank"]]
    meta = ada_sync.build_meta({"kind": nd["kind"], "status": "active",
                                "subject": nd["subject"], "valid_from": TODAY,
                                "last_verified": TODAY}, nd["bank"], scope, TODAY)
    mddb_add(coll, nd["key"], nd["content"], meta)
    file_ops.append(("promote", None, f"{vdir}/{nd['key'].split('/')[-1]}.md",
                     (meta, nd["content"], nd["key"])))
    stats["K"] += 1

def render(meta, body, key=None):
    fm = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
          for k, v in meta.items() if k in ada_sync.MANAGED_FIELDS}
    if key: fm["key"] = key
    return "---\n" + yaml.safe_dump(fm, sort_keys=True, allow_unicode=True) + "---\n" + body + "\n"

json.dump([{"a": a, "s": s, "d": d,
            "text": render(*payload) if payload else None}
           for a, s, d, payload in file_ops],
          open(ROOT / ".triage/file-ops.json", "w"), ensure_ascii=False, indent=1)
print("STATS", stats, "file-ops:", len(file_ops))
