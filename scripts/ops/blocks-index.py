#!/usr/bin/env python3
"""blocks-index — generate blocks.json (the composer's block catalog).

Scans scripts/ops, scripts/ada, scripts/colab/packs + the pack ymls.
Each block: {name, kind: script|pack|door-op, desc, produces, consumes,
needs}. The composer (jev-code-decision v2) decides over a shortlist
from this catalog; the agent pre-filters to a shortlist.
"""
import json, glob, os, re, sys, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
blocks = []

def doc_of(path):
    try:
        txt = open(path).read()
    except Exception:
        return ""
    m = re.search(r'"""(.*?)"""', txt, re.S)
    if m:
        return m.group(1).split("\n\n")[0].strip().replace("\n", " ")[:160]
    m = re.search(r'^\s*#\s*(.*)', txt, re.M)
    return m.group(1).strip()[:120] if m else ""

for pat, kind in ((f"{ROOT}/ops/*.py", "script"),
                  (f"{ROOT}/ada/*.py", "script")):
    for f in sorted(glob.glob(pat)):
        name = os.path.basename(f)[:-3]
        if name.startswith("__"):
            continue
        blocks.append({"name": name, "kind": kind, "desc": doc_of(f),
                       "produces": [], "consumes": []})

for p in sorted(glob.glob(f"{ROOT}/colab/packs/*/pack.yml")):
    name = os.path.basename(os.path.dirname(p))
    try:
        y = yaml.safe_load(open(p))
    except Exception:
        continue
    blocks.append({
        "name": name, "kind": "pack",
        "desc": (y.get("name") or name),
        "needs": y.get("needs", {}),
        "produces": list((y.get("artifacts") or [])[:3]),
        "consumes": list((y.get("fetch") or [])[:3]),
        "publish": list((y.get("publish") or {}).keys()),
    })

out = f"{ROOT}/blocks.json"
json.dump({"blocks": blocks, "count": len(blocks),
           "generated": __import__("datetime").date.today().isoformat()},
          open(out, "w"), indent=1)
print(f"blocks.json: {len(blocks)} blocks -> {out}")
for b in blocks[:6]:
    print(" -", b["kind"], b["name"], "|", b["desc"][:50])
