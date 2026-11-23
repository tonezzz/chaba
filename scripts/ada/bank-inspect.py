#!/usr/bin/env python3
"""Snapshot per-lane Ada memory-bank contents into CMS memory-inspect pages.

Card memory-inspect-pages (MEM-0745). For each persona lane declared in
docs/ssot/apps/ssot.apps.ada-persona-lanes.yml (instances -> cms_collection),
dump every ada-ha-bank-* collection visible to that lane's instance from the
memory plane (:11023) as a subject -> attribute -> kind/value + modified
digest, then write the snapshot into THAT lane's CMS collection (:11027):

  <cms_collection>/memory-inspect            index — the lane's bank roster
  <cms_collection>/memory-inspect-<bank>     leaf — one bank's entries

Scope-respecting by construction: tony -> ada-cms-pages,
kk -> ada-cms-pages-kk, michael -> ada-cms-pages-mn,
kk-dev -> ada-cms-pages-kk-dev (read-only mounts via instances_readonly
resolve to the mapped prod collection and are flagged ro).

Only ada-ha-bank-* collections are dumped — kb-*/ada-cms-* registry
entries live on the CMS plane and are out of scope. Snapshots are
read-only: the memory->CMS direction stays one-way.

Secret-keyed entries (subject/attribute matching credential words, or
values that look like live secrets) are redacted at write time — the page
shows the entry exists, never the payload.

Usage:
  bank-inspect.py                     # all lanes, live write
  bank-inspect.py --dry-run           # print pages, write nothing
  bank-inspect.py --lane tony         # one lane only
  bank-inspect.py --bank personal-tony  # one bank only (per resolved name)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
BANKS_SSOT = REPO / "docs/ssot/apps/ssot.apps.ada-memory-banks.yml"
LANES_SSOT = REPO / "docs/ssot/apps/ssot.apps.ada-persona-lanes.yml"

MEMORY_MDDB = os.environ.get(
    "ADA_MEMORY_MDDB_URL", "http://100.102.134.91:11023/v1").rstrip("/")
CMS_MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11027/v1").rstrip("/")

INDEX_SLUG = "memory-inspect"
MAX_VALUE_CHARS = 240
DOC_LIMIT = 5000

# Entries whose join key suggests a credential — redact the value but keep
# the row so drift/growth is still visible.
SECRET_KEY_RE = re.compile(
    r"key|token|secret|passw|credential|api[_-]?key|auth", re.I)

# Live-secret-shaped payloads (same family as backup-mddb-banks.py) — a
# value that matches is redacted regardless of its key.
SECRET_VALUE_RE = re.compile(
    r"AIza[0-9A-Za-z_\-]{20,}|"            # Google/GCP API keys
    r"ya29\.[0-9A-Za-z_\-]{20,}|"          # Google OAuth access tokens
    r"ghp_[0-9A-Za-z]{20,}|"               # GitHub PATs
    r"xox[baprs]-[0-9A-Za-z-]{10,}|"       # Slack tokens
    r"sk-[0-9A-Za-z]{20,}|"                # OpenAI-style keys
    r"sk-or-v1-[0-9A-Za-z_\-]{10,}|"       # OpenRouter
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

REDACTED = "*(redacted)*"


def _post(base: str, path: str, payload: dict, timeout: int = 60):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{base}{path}", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def meta1(meta: dict, name: str, default: str = "") -> str:
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return str(v[0]) if v else default
    return str(v) if v is not None else default


def load_lanes() -> dict[str, str]:
    """{bank-instance-id: cms_collection} from the persona-lanes registry."""
    data = yaml.safe_load(LANES_SSOT.read_text()) or {}
    lanes = {}
    for svc, spec in (data.get("instances") or {}).items():
        coll = (spec or {}).get("cms_collection")
        if not coll:
            continue
        inst = spec.get("instance_id")
        if not inst:
            # ada-ha-tony -> tony, ada-kk -> kk, ada-kk-dev -> kk-dev
            inst = re.sub(r"^ada-(ha|ai)-", "", svc)
            inst = re.sub(r"^ada-", "", inst)
        lanes[inst] = coll
    return lanes


def load_banks() -> dict[str, dict]:
    data = yaml.safe_load(BANKS_SSOT.read_text()) or {}
    return data.get("banks") or {}


def lane_banks(lane: str, banks: dict[str, dict]) -> list[dict]:
    """Banks visible to a lane: assigned (instances) rw/ro per writable,
    plus read-only mounts (instances_readonly) resolved to the mapped
    prod instance. ada-ha-bank-* collections only."""
    out = []
    for name, spec in banks.items():
        coll_tpl = spec.get("mddb_collection") or ""
        if not coll_tpl:
            continue
        ro_map = spec.get("instances_readonly") or {}
        instances = spec.get("instances") or []
        if lane in instances:
            coll = coll_tpl.replace("{instance}", lane)
            access = "rw" if spec.get("writable") else "ro"
        elif lane in ro_map:
            coll = coll_tpl.replace("{instance}", ro_map[lane])
            access = "ro"
        else:
            continue
        if not coll.startswith("ada-ha-bank-"):
            continue  # kb-*/ada-cms-* registry entries aren't memory banks
        out.append({"bank": name, "collection": coll, "access": access})
    return out


def list_docs(collection: str, mddb: str = MEMORY_MDDB) -> list[dict]:
    return _post(mddb, "/search", {"collection": collection,
                                   "limit": DOC_LIMIT}) or []


def _modified(doc: dict) -> str:
    meta = doc.get("meta") or {}
    for f in ("updated", "last_verified", "valid_from"):
        v = meta1(meta, f)
        if v:
            return v[:10]
    ts = doc.get("updatedAt") or doc.get("addedAt")
    if ts:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    return ""


def _is_secret_entry(subject: str, attr: str, value: str) -> bool:
    if SECRET_KEY_RE.search(attr):
        return True
    if SECRET_KEY_RE.search(subject) and SECRET_VALUE_RE.search(value):
        return True
    return bool(SECRET_VALUE_RE.search(value))


def entry_rows(docs: list[dict]) -> tuple[list[dict], int]:
    """subject -> attr -> {kind, value, modified} rows; returns (rows, n_redacted)."""
    rows, n_red = [], 0
    for d in docs:
        meta = d.get("meta") or {}
        if meta1(meta, "status") in ("superseded", "retracted", "expired"):
            continue
        subject = meta1(meta, "subject") or d.get("key", "")
        attr = meta1(meta, "attribute") or "-"
        value = re.sub(r"\s+", " ", (d.get("contentMd") or "").strip())
        value = value.split("\n---", 1)[0].strip()
        if _is_secret_entry(subject, attr, value):
            value = REDACTED
            n_red += 1
        elif len(value) > MAX_VALUE_CHARS:
            value = value[:MAX_VALUE_CHARS].rstrip() + "…"
        rows.append({"subject": subject, "attr": attr,
                     "kind": meta1(meta, "kind") or "-",
                     "value": value, "modified": _modified(d)})
    rows.sort(key=lambda r: (r["subject"], r["attr"]))
    return rows, n_red


def _cell(s: str) -> str:
    return s.replace("|", "\\|") if s else s


def bank_page(lane: str, bank: dict, rows: list[dict], n_red: int,
              now: str) -> str:
    lines = [
        f"# Memory inspect — {bank['collection']}", "",
        f"Lane `{lane}` · access `{bank['access']}` · "
        f"{len(rows)} entries"
        + (f" · {n_red} redacted" if n_red else ""), "",
        "| Subject | Attribute | Kind | Value | Modified |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| `{_cell(r['subject'])}` | `{_cell(r['attr'])}` "
                     f"| {r['kind']} | {_cell(r['value'])} "
                     f"| {r['modified']} |")
    lines += ["", f"*Generated by bank-inspect.py · {now} · "
              f"parent: {INDEX_SLUG}*"]
    return "\n".join(lines)


def index_page(lane: str, summaries: list[dict], now: str) -> str:
    lines = [
        f"# Memory inspect — {lane} lane", "",
        "Read-only snapshot of the memory banks this lane sees "
        "(memory plane :11023). Secret-keyed entries are redacted "
        "at write time.", "",
        "| Bank | Collection | Entries | Access | Redacted | Latest |",
        "|---|---|---|---|---|---|",
    ]
    total = 0
    for s in summaries:
        total += s["n"]
        lines.append(
            f"| [{s['bank']}]({INDEX_SLUG}-{_page_suffix(s['bank'])}) "
            f"| `{s['collection']}` | {s['n']} | {s['access']} "
            f"| {s['n_red']} | {s['latest']} |")
    lines += ["", f"**{total} entries across {len(summaries)} banks**", "",
              f"*Generated by bank-inspect.py · {now}*"]
    return "\n".join(lines)


def _page_suffix(bank: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", bank.lower()).strip("-")


def publish(collection: str, slug: str, title: str, content: str,
            lane: str, extra: dict, now: str,
            cms: str = CMS_MDDB) -> int:
    scope = lane if lane in ("tony", "michael", "kk") else "shared"
    meta = {
        "attribute": ["page"], "bank": ["cms"], "domain": ["memory"],
        "format": ["markdown"], "instance": ["ada"],
        "kind": ["memory-inspect"],
        "lang": ["en"], "scope": [scope], "slug": [slug], "source": ["api"],
        "status": ["active"], "subject": [slug], "title": [title],
        "updated": [now], "valid_from": [now[:10]], "last_verified": [now[:10]],
        "written_by": ["bank-inspect"], "generated_by": ["bank-inspect.py"],
        "lane": [lane],
        "sources": ["memory plane :11023 ada-ha-bank-* dump (read-only)"],
    }
    meta.update(extra)
    _post(cms, "/add", {"collection": collection, "key": slug, "lang": "en",
                        "contentMd": content, "meta": meta})
    return 200


def run_lane(lane: str, cms_collection: str, banks: dict[str, dict],
             args, now: str) -> int:
    summaries, pages = [], {}
    for bank in lane_banks(lane, banks):
        if args.bank and bank["bank"] != args.bank \
                and bank["collection"] != f"ada-ha-bank-{args.bank}":
            continue
        try:
            docs = list_docs(bank["collection"], args.memory_mddb)
        except Exception as e:
            print(f"  ! {bank['collection']}: {e}", file=sys.stderr)
            summaries.append({**bank, "n": 0, "n_red": 0,
                              "latest": f"ERR {type(e).__name__}"})
            continue
        rows, n_red = entry_rows(docs)
        latest = max((r["modified"] for r in rows), default="")
        slug = f"{INDEX_SLUG}-{_page_suffix(bank['bank'])}"
        pages[slug] = (f"Memory inspect — {bank['collection']}",
                       bank_page(lane, bank, rows, n_red, now))
        summaries.append({**bank, "n": len(rows), "n_red": n_red,
                          "latest": latest})
    if not args.bank:
        pages = {INDEX_SLUG: (f"Memory inspect — {lane} lane",
                              index_page(lane, summaries, now)),
                 **pages}
    failed = 0
    for slug, (title, content) in pages.items():
        extra = {"report_role": ["index" if slug == INDEX_SLUG else "leaf"]}
        if slug != INDEX_SLUG:
            extra["parent"] = [INDEX_SLUG]
        else:
            extra["children"] = [s for s in pages if s != INDEX_SLUG]
        if args.dry_run:
            print(f"--- [{cms_collection}] {slug} "
                  f"({len(content)} chars) ---\n{content}\n")
            continue
        try:
            publish(cms_collection, slug, title, content, lane, extra,
                    now, args.cms_mddb)
            print(f"  {cms_collection}/{slug}: ok ({len(content)} chars)")
        except Exception as e:
            print(f"  {cms_collection}/{slug}: PUBLISH FAIL {e}",
                  file=sys.stderr)
            failed += 1
    return failed


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--lane", help="one lane instance id only")
    ap.add_argument("--bank", help="one bank name only")
    ap.add_argument("--memory-mddb", default=MEMORY_MDDB)
    ap.add_argument("--cms-mddb", default=CMS_MDDB)
    args = ap.parse_args()

    lanes = load_lanes()
    banks = load_banks()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    failed = 0
    for lane in ([args.lane] if args.lane else sorted(lanes)):
        cms_collection = lanes.get(lane)
        if not cms_collection:
            print(f"! lane {lane}: no cms_collection — skipped",
                  file=sys.stderr)
            failed += 1
            continue
        print(f"lane {lane} -> {cms_collection}")
        failed += run_lane(lane, cms_collection, banks, args, now)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
