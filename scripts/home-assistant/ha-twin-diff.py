#!/usr/bin/env python3
"""ha-twin-diff.py — diff two collected HA instance snapshots per release scope.

Snapshots are produced by inst_collect() in ha-lanes.sh:
    <dir>/storage/<file>   .storage JSON files
    <dir>/yaml/<file>      automations/scripts/scenes + packages/*.yaml
    <dir>/bundles.md5      "md5  ./path" lines for www/**/*.js

Usage:
    ha-twin-diff.py A_DIR B_DIR [--names A:B]
        [--scope dashboards,resources,bundle,automations,helpers,users|all]
        [--json]

Exit 0 = parity on every selected scope, 1 = drift, 2 = collection/usage error.
Never prints secret material — user scope reports users/groups/persons only.
"""
import hashlib
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    yaml = None

ALL_SCOPES = ["dashboards", "resources", "bundle", "automations", "helpers", "users"]
HELPER_DOMAINS = ["input_boolean", "input_button", "input_datetime",
                  "input_number", "input_select", "input_text",
                  "counter", "timer", "schedule", "group", "tag", "person"]
STUB_MARK = "staging-noop"


def jload(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def yload(path):
    if yaml is None or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def storage_items(node):
    if not node:
        return []
    d = node.get("data", node)
    return d.get("items", []) if isinstance(d, dict) else []


def canon(obj):
    return json.dumps(obj, sort_keys=True, default=str)


def digest(obj):
    return hashlib.md5(canon(obj).encode()).hexdigest()[:10]


class Report:
    def __init__(self):
        self.sections = {}   # scope -> [drift lines]
        self.notes = {}      # scope -> [informational lines, not drift]

    def add(self, scope, line):
        self.sections.setdefault(scope, []).append(line)

    def note(self, scope, line):
        self.notes.setdefault(scope, []).append(line)

    def render(self, a_name, b_name, scopes):
        out = []
        for s in scopes:
            lines = self.sections.get(s, [])
            notes = self.notes.get(s, [])
            hdr = f"== {s} =="
            if not lines:
                out.append(f"{hdr} parity")
            else:
                out.append(f"{hdr} {len(lines)} diff(s) — {a_name} vs {b_name}")
                out.extend("  " + l for l in lines)
            out.extend("  (note) " + n for n in notes)
        return "\n".join(out)


def diff_maps(scope, rep, a_map, b_map, label=lambda k: k, kind=""):
    p = f"{kind} " if kind else ""
    for k in sorted(set(a_map) | set(b_map)):
        if k not in a_map:
            rep.add(scope, f"{p}only in B: {label(k)}")
        elif k not in b_map:
            rep.add(scope, f"{p}only in A: {label(k)}")
        elif a_map[k] != b_map[k]:
            rep.add(scope, f"{p}changed: {label(k)}")


# ---------------------------------------------------------------- resources
def scope_resources(a, b, rep):
    def urls(d):
        n = jload(os.path.join(d, "storage/lovelace_resources"))
        return {i.get("url", "") for i in storage_items(n) if i.get("url")}
    ua, ub = urls(a), urls(b)
    norm = lambda u: re.sub(r"-v\d+(\.js)$", r"\1", u.split("?")[0])
    na, nb = {norm(u) for u in ua}, {norm(u) for u in ub}
    for u in sorted(na - nb):
        rep.add("resources", f"missing in B: {u}")
    for u in sorted(nb - na):
        rep.add("resources", f"missing in A: {u}")
    for x in sorted(ua):
        for y in ub:
            if norm(x) == norm(y) and x != y:
                rep.add("resources", f"version skew: {x}  vs  {y}")


# ---------------------------------------------------------------- dashboards
def scope_dashboards(a, b, rep):
    def registry(d):
        n = jload(os.path.join(d, "storage/lovelace_dashboards"))
        reg = {}
        for i in storage_items(n):
            reg[i.get("id")] = {k: i.get(k) for k in
                                ("url_path", "title", "icon", "mode",
                                 "require_admin", "show_in_sidebar")}
        return reg

    def dash_cfg(d, dash_id):
        n = jload(os.path.join(d, f"storage/lovelace.{dash_id}"))
        return (n or {}).get("data", {}).get("config", {})

    ra, rb = registry(a), registry(b)
    meta_diff = False
    for did in sorted(set(ra) | set(rb)):
        pa = (ra.get(did) or {}).get("url_path", did)
        if did not in ra:
            rep.add("dashboards", f"dashboard only in B: {pa}")
            continue
        if did not in rb:
            rep.add("dashboards", f"dashboard only in A: {pa}")
            continue
        if ra[did] != rb[did]:
            rep.add("dashboards", f"dashboard meta differs: {pa}")
            meta_diff = True
    # per-view diff for shared dashboards
    for did in sorted(set(ra) & set(rb)):
        ca, cb = dash_cfg(a, did), dash_cfg(b, did)
        if canon(ca) == canon(cb):
            continue
        path = (ra.get(did) or {}).get("url_path", did)
        va = {v.get("path") or v.get("title") or f"#{n}": v
              for n, v in enumerate(ca.get("views", []))}
        vb = {v.get("path") or v.get("title") or f"#{n}": v
              for n, v in enumerate(cb.get("views", []))}
        top_a = {k: v for k, v in ca.items() if k != "views"}
        top_b = {k: v for k, v in cb.items() if k != "views"}
        if canon(top_a) != canon(top_b):
            rep.add("dashboards", f"{path}: dashboard-level keys differ")
        for vk in sorted(set(va) | set(vb)):
            if vk not in va:
                rep.add("dashboards", f"{path}: view only in B: {vk}")
            elif vk not in vb:
                rep.add("dashboards", f"{path}: view only in A: {vk}")
            elif canon(va[vk]) != canon(vb[vk]):
                rep.add("dashboards", f"{path}: view differs: {vk} "
                        f"(a:{digest(va[vk])} b:{digest(vb[vk])})")


# ---------------------------------------------------------------- bundle
def scope_bundle(a, b, rep):
    def md5s(d):
        m = {}
        p = os.path.join(d, "bundles.md5")
        if os.path.exists(p):
            for line in open(p):
                parts = line.split()
                if len(parts) == 2:
                    m[parts[1].lstrip("./")] = parts[0]
        return m
    diff_maps("bundle", rep, md5s(a), md5s(b))


# ---------------------------------------------------------------- automations
def _auto_key(item, n):
    return str(item.get("id") or item.get("alias") or f"#{n}")


def _auto_items(d, fname):
    doc = yload(os.path.join(d, "yaml", fname))
    if isinstance(doc, list):
        return {_auto_key(i, n): i for n, i in enumerate(doc) if isinstance(i, dict)}
    if isinstance(doc, dict):                      # keyed mapping form
        return {str(k): v for k, v in doc.items()}
    return {}


def _is_stub_script(item):
    seq = item.get("sequence") or item.get("action") or []
    return isinstance(seq, list) and len(seq) == 1 and \
        isinstance(seq[0], dict) and seq[0].get("stop") == STUB_MARK


def _is_stub_scene(item):
    return "entities" in item and not item.get("entities")


def _destage(items, kind):
    """Strip actuation-guard artifacts before comparing: injected
    `initial_state: false` on automations; stubbed scripts/emptied scenes are
    removed from comparison entirely (contents intentionally destroyed on the
    twin). Returns (clean_items, stub_count, stripped_count)."""
    clean, stubs, stripped = {}, 0, 0
    for k, v in items.items():
        if kind in ("script", "scene") and (
                (kind == "script" and _is_stub_script(v)) or
                (kind == "scene" and _is_stub_scene(v))):
            stubs += 1
            continue
        if kind == "automation" and isinstance(v, dict) and \
                v.get("initial_state") is False:
            v = dict(v)
            del v["initial_state"]
            stripped += 1
        clean[k] = v
    return clean, stubs, stripped


def scope_automations(a, b, rep):
    for fname, kind in (("automations.yaml", "automation"),
                        ("scripts.yaml", "script"),
                        ("scenes.yaml", "scene")):
        ia, ib = _auto_items(a, fname), _auto_items(b, fname)
        ca, sa, ta = _destage(ia, kind)
        cb, sb, tb = _destage(ib, kind)
        if sa or sb:
            rep.note("automations",
                     f"{fname}: {sa} A-side / {sb} B-side {kind}s stubbed by "
                     f"the actuation guard — excluded from comparison")
        if ta or tb:
            rep.note("automations",
                     f"{fname}: injected initial_state:false stripped for "
                     f"comparison (A={ta} B={tb})")
        for k in sorted(set(ca) | set(cb)):
            if k not in ca:
                rep.add("automations", f"{kind} only in B: {k}")
            elif k not in cb:
                rep.add("automations", f"{kind} only in A: {k}")
            elif canon(ca[k]) != canon(cb[k]):
                rep.add("automations", f"{kind} changed: {k}")
    pa = set(os.listdir(os.path.join(a, "yaml/packages")) if os.path.isdir(
        os.path.join(a, "yaml/packages")) else [])
    pb = set(os.listdir(os.path.join(b, "yaml/packages")) if os.path.isdir(
        os.path.join(b, "yaml/packages")) else [])
    for f in sorted(pa | pb):
        ha = digest(open(os.path.join(a, "yaml/packages", f), "rb").read()) \
            if f in pa else None
        hb = digest(open(os.path.join(b, "yaml/packages", f), "rb").read()) \
            if f in pb else None
        if ha != hb:
            where = "only in A" if hb is None else \
                    "only in B" if ha is None else "differs"
            rep.add("automations", f"package {f}: {where}")


# ---------------------------------------------------------------- helpers
def scope_helpers(a, b, rep):
    for dom in HELPER_DOMAINS:
        ia = {i.get("id") or i.get("name"): i
              for i in storage_items(jload(os.path.join(a, "storage", dom)))}
        ib = {i.get("id") or i.get("name"): i
              for i in storage_items(jload(os.path.join(b, "storage", dom)))}
        if not ia and not ib:
            continue
        for k in sorted(set(ia) | set(ib)):
            name = (ia.get(k) or ib.get(k) or {}).get("name", k)
            if k not in ia:
                rep.add("helpers", f"{dom} only in B: {name}")
            elif k not in ib:
                rep.add("helpers", f"{dom} only in A: {name}")
            elif canon(ia[k]) != canon(ib[k]):
                changed = sorted(
                    kk for kk in set(ia[k]) | set(ib[k])
                    if canon(ia[k].get(kk)) != canon(ib[k].get(kk)))
                rep.add("helpers", f"{dom} changed: {name} fields={changed}")


# ---------------------------------------------------------------- users
def scope_users(a, b, rep):
    def users(d):
        n = jload(os.path.join(d, "storage/auth"))
        out = {}
        for u in (n or {}).get("data", {}).get("users", []):
            out[u.get("id")] = {k: u.get(k) for k in
                                ("name", "is_owner", "is_active",
                                 "system_generated", "local_only", "group_ids")}
        return out
    ua, ub = users(a), users(b)
    diff_maps("users", rep, ua, ub,
              label=lambda k: (ua.get(k) or ub.get(k) or {}).get("name", k),
              kind="user")

    def creds(d):
        n = jload(os.path.join(d, "storage/auth_provider.homeassistant"))
        return sorted(i.get("username") for i in storage_items(n) if i.get("username"))
    ca, cb = creds(a), creds(b)
    for u in sorted(set(ca) - set(cb)):
        rep.add("users", f"login only in A: {u}")
    for u in sorted(set(cb) - set(ca)):
        rep.add("users", f"login only in B: {u}")

    def persons(d):
        return {i.get("id"): {"name": i.get("name"), "user_id": i.get("user_id")}
                for i in storage_items(jload(os.path.join(d, "storage/person")))}
    pa, pb = persons(a), persons(b)
    diff_maps("users", rep, pa, pb,
              label=lambda k: (pa.get(k) or pb.get(k) or {}).get("name", k),
              kind="person")


SCOPES = {
    "dashboards": scope_dashboards,
    "resources": scope_resources,
    "bundle": scope_bundle,
    "automations": scope_automations,
    "helpers": scope_helpers,
    "users": scope_users,
}


def main():
    args = sys.argv[1:]
    if len(args) < 2 or "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(2)
    a_dir, b_dir = args[0], args[1]
    names = ("A", "B")
    scopes = list(ALL_SCOPES)
    want_json = "--json" in args
    for i, x in enumerate(args):
        if x == "--names":
            names = tuple(args[i + 1].split(":"))
        if x == "--scope":
            scopes = args[i + 1].split(",")
    if scopes == ["all"]:
        scopes = list(ALL_SCOPES)
    for d in (a_dir, b_dir):
        if not os.path.isdir(d):
            print(f"snapshot dir missing: {d}", file=sys.stderr)
            sys.exit(2)
    rep = Report()
    for s in scopes:
        if s not in SCOPES:
            print(f"unknown scope: {s}", file=sys.stderr)
            sys.exit(2)
        SCOPES[s](a_dir, b_dir, rep)
    if want_json:
        print(json.dumps({
            s: {"diffs": rep.sections.get(s, []),
                "notes": rep.notes.get(s, [])} for s in scopes}, indent=1))
    else:
        print(rep.render(names[0], names[1], scopes))
    sys.exit(1 if any(rep.sections.get(s) for s in scopes) else 0)


if __name__ == "__main__":
    main()
