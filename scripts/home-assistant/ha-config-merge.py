#!/usr/bin/env python3
"""ha-config-merge.py — destage-merge a dev twin's automation yaml into prod's.

The staging actuation guard (ssot.home-assistant.staging-overlay.yml)
mutilates the twin's yaml on purpose; promotion reverses the mutilation:

  automations.yaml  (list)  merge key: id -> alias.
      `initial_state: false` injected by the overlay is stripped from every
      promoted item — prod enable/disable lives in the entity registry.
      Dev item replaces prod's; dev-only items append; prod-only items keep.
  scripts.yaml      (map)   merge key: dict key.
      A script whose sequence is the overlay stub ({stop: staging-noop}) is
      treated as absent on dev — prod's real body survives. Only scripts
      authored/changed on the twin AFTER cloning carry over.
  scenes.yaml       (list)  merge key: id -> name.
      A scene with an emptied entities map (overlay artifact) is skipped.

Usage:
    ha-config-merge.py <kind> <dev_yaml> <prod_yaml>
        kind = automations|scripts|scenes
    ha-config-merge.py eq <f1> <f2>
        exit 0 when the two yaml files are semantically equal
        (None/empty/[]/{} all count as empty)

Writes the merged yaml to stdout; a human summary goes to stderr.
Missing prod file => merged = destaged dev file. Missing dev file => empty.
"""
import sys

import yaml

STUB = "staging-noop"


def load(path):
    try:
        doc = yaml.safe_load(open(path))
    except FileNotFoundError:
        return {} if path.endswith("scripts.yaml") else []
    return doc if doc is not None else ({} if path.endswith("scripts.yaml") else [])


def is_stub_script(item):
    seq = (item or {}).get("sequence") or (item or {}).get("action") or []
    return isinstance(seq, list) and len(seq) == 1 and \
        isinstance(seq[0], dict) and seq[0].get("stop") == STUB


def akey(item, n):
    return str(item.get("id") or item.get("alias") or item.get("name") or f"#{n}")


def merge_list(dev, prod, kind):
    """List-form files (automations, scenes): key -> item maps."""
    dmap = {akey(i, n): i for n, i in enumerate(dev) if isinstance(i, dict)}
    pmap = {akey(i, n): i for n, i in enumerate(prod) if isinstance(i, dict)}
    order = [akey(i, n) for n, i in enumerate(prod) if isinstance(i, dict)]
    notes = []
    for k, item in dmap.items():
        if kind == "automations" and item.get("initial_state") is False:
            item = dict(item)
            del item["initial_state"]
        if kind == "scenes" and "entities" in item and not item.get("entities"):
            notes.append(f"skip stubbed scene (empty entities): {k}")
            continue
        if k not in pmap:
            notes.append(f"add: {k}")
            order.append(k)
        elif yaml.dump(item, sort_keys=True) != yaml.dump(pmap[k], sort_keys=True):
            notes.append(f"replace: {k}")
        else:
            notes.append(f"unchanged: {k}")
        pmap[k] = item
    return [pmap[k] for k in order], notes


def merge_scripts(dev, prod):
    notes = []
    out = dict(prod)
    for k, item in dev.items():
        if is_stub_script(item):
            notes.append(f"skip staging stub: {k}")
            continue
        if k not in prod:
            notes.append(f"add: {k}")
        elif yaml.dump(item, sort_keys=True) != yaml.dump(prod[k], sort_keys=True):
            notes.append(f"replace: {k}")
        else:
            notes.append(f"unchanged: {k}")
        out[k] = item
    for k in sorted(set(prod) - set(dev)):
        notes.append(f"keep prod-only: {k}")
    return out, notes


def _semantically_empty(doc):
    return doc is None or doc == [] or doc == {}


def main():
    if sys.argv[1] == "eq":
        d1 = load(sys.argv[2])
        d2 = load(sys.argv[3])
        same = d1 == d2 or (_semantically_empty(d1) and _semantically_empty(d2))
        sys.exit(0 if same else 1)
    kind, dev_path, prod_path = sys.argv[1], sys.argv[2], sys.argv[3]
    dev, prod = load(dev_path), load(prod_path)
    if kind == "scripts":
        merged, notes = merge_scripts(dev or {}, prod or {})
    elif kind in ("automations", "scenes"):
        merged, notes = merge_list(dev or [], prod or [],
                                   "automations" if kind == "automations" else "scenes")
    else:
        sys.exit(f"unknown kind: {kind}")
    for n in notes:
        print(f"  {n}", file=sys.stderr)
    yaml.dump(merged, sys.stdout, sort_keys=False, allow_unicode=True,
              default_flow_style=False, width=1000)


if __name__ == "__main__":
    main()
