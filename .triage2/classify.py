#!/usr/bin/env python3
"""Classify inbox/general extracts by MDDB bank doc status."""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "docs/ada-memory/inbox/general"
BANKDIR = ROOT / "docs/ada-memory/general"

def load_bank(f):
    d = json.load(open(f))
    out = {}
    for doc in d["documents"]:
        m = doc["meta"]
        out[doc["key"]] = {
            "status": (m.get("status") or ["?"])[0],
            "superseded_by": (m.get("superseded_by") or [None])[0],
            "retracted_reason": (m.get("retracted_reason") or [None])[0],
            "subject": (m.get("subject") or [None])[0],
        }
    return out

gen = load_bank(ROOT / ".triage2/bank-general.json")
ho  = load_bank(ROOT / ".triage2/bank-devin-handoff.json")

fm_re = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

def parse_key(path):
    txt = path.read_text()
    m = fm_re.match(txt)
    if not m:
        return None, txt.strip()
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip("'\"")
    return fm.get("key"), m.group(2).strip()

TERMINAL = {"superseded", "retracted", "answered", "done"}
report = []
counts = {}
for f in sorted(INBOX.glob("*.md")):
    key, body = parse_key(f)
    slug = f.stem
    g = gen.get(key) if key else None
    h = ho.get(key) if key else None
    bankfile = (BANKDIR / f.name).exists()
    # Also check key-derived bank path (key may include subdir prefix)
    keyfile = (BANKDIR / (key.split("/")[-1] + ".md")).exists() if key else False
    if g:
        st = g["status"]
    elif h:
        st = "handoff:" + h["status"]
    else:
        st = "missing"
    if g and st in TERMINAL:
        cls = "processed"
        why = f"bank doc {st}" + (f" -> {g['superseded_by']}" if g["superseded_by"] else "")
    elif g and st == "active":
        if bankfile or keyfile:
            cls = "processed"; why = "bank doc active, vault bank file exists (dup inbox copy)"
        else:
            cls = "processed?"; why = "bank doc active but NO vault bank file"
    elif h and h["status"] in TERMINAL:
        cls = "processed"; why = f"devin-handoff doc {h['status']}"
    elif h:
        cls = "keep"; why = f"live: devin-handoff doc {h['status']}"
    elif g and st == "draft":
        cls = "keep"; why = "bank doc still draft (untriaged)"
    else:
        cls = "review"; why = "no MDDB doc in either bank"
    report.append({"file": f.name, "key": key, "status": st, "cls": cls,
                   "why": why, "bankfile": bankfile or keyfile,
                   "body": body[:200]})
    counts[cls] = counts.get(cls, 0) + 1

json.dump(report, open(ROOT / ".triage2/report.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(counts, indent=1))
for r in report:
    if r["cls"] in ("keep", "review", "processed?"):
        print(f"{r['cls']:11} {r['file']:55} [{r['status']}] {r['why']}")
