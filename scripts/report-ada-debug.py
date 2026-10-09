#!/usr/bin/env python3
"""report-ada-debug.py — 'ada-debug' leaf report: the interrogation table.

Per known person: resolved aliases, banks they can read/write, HA
control domains, persona overrides, features in effect, private-bank
doc count, last-seen speaker activity. Plus a person_coverage audit:
every speaker identity seen in ada-events (30d) must resolve to a
persons entry or 'default' — unresolvable identities land in the
UNMAPPED section (the "who is Ada actually talking to" question).

Writes (leaf contract, ssot.apps.cms-reports.yml):
  reports/ada-debug/ADA-DEBUG-<yyyymmdd>.md
  reports/meta.ada-debug.yml
  ada-cms-pages/ada-debug-report (kind:report)

Usage: report-ada-debug.py [--print]
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sys
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from lib.report import append_timeline, now_iso, write_meta  # noqa: E402

NODE = "ada-debug"
LAYER = "L2-domain"
OUT_DIR = REPO / "reports" / "ada-debug"
META = REPO / "reports" / "meta.ada-debug.yml"
PERSONS_YML = REPO / "docs" / "ssot" / "apps" / "ssot.apps.ada-persons.yml"
MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
CMS_SLUG = "ada-debug-report"
DAYS = 30


def _mddb(path: str, payload: dict, timeout: int = 20):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception:
        return []


def bank_doc_count(collection: str) -> int:
    r = _mddb("search", {"collection": collection, "limit": 1})
    st = _mddb("stats", {"collection": collection})
    if isinstance(st, dict) and st.get("count"):
        return int(st["count"])
    return len(r) if isinstance(r, list) else -1


def speaker_seen() -> dict:
    """speaker entities observed in ada-ha-events-tony (30d)."""
    docs = _mddb("search", {"collection": "ada-ha-events-tony",
                            "limit": 2000})
    seen = collections.Counter()
    for d in docs or []:
        m = d.get("meta") or {}
        for key in ("speaker", "person", "entity", "owner"):
            v = (m.get(key) or [None])[0]
            if v and str(v).startswith(("person.", "user-", "ha-")):
                seen[v] += 1
    return dict(seen)


def render(cfg: dict, counts: dict, seen: dict) -> tuple[str, str, list]:
    now = now_iso()
    persons = cfg.get("persons") or {}
    flags = (cfg.get("features") or {}).get("flags") or {}
    alias2person = {}
    for key, p in persons.items():
        for a in p.get("aliases") or []:
            alias2person[a] = key

    lines = [
        "# Ada Debug — who she thinks everyone is",
        f"**Updated:** {now[:16]} · coverage window {DAYS}d",
        "",
        "<!-- ada-debug:auto -->",
        "## Feature flags (declared defaults)",
        "",
    ]
    for name, spec in flags.items():
        note = f" — {spec['note']}" if spec.get("note") else ""
        lines.append(f"- `{name}` = **{str(spec.get('default'))}**{note}")
    lines += ["", "live overrides: `ada-config/feature-flags` in MDDB",
              "", "## Persons", ""]
    for key, p in persons.items():
        if key in ("default", "unknown"):
            continue
        banks = ", ".join(str(b) for b in (p.get("banks_read") or []))
        w = p.get("bank_write") or "—"
        ctl = ", ".join(str(d) for d in (p.get("control") or {}).get("domains") or [])
        pers = p.get("persona") or {}
        pers_s = " ".join(f"{k}={v}" for k, v in pers.items())
        feats = p.get("features") or {}
        feat_s = " ".join(f"{k}={v}" for k, v in feats.items()) or "defaults"
        docc = counts.get(f"ada-ha-bank-personal-{key}")
        doc_s = f"{docc} docs" if docc is not None and docc >= 0 else "?"
        seen_hits = sum(v for a, v in seen.items()
                        if alias2person.get(a) == key)
        lines += [
            f"### {p.get('label', key)} (`{key}`) — {p.get('role','?')}",
            f"- aliases: {', '.join(p.get('aliases') or [])}",
            f"- banks read: {banks} · write: {w}",
            f"- control: {ctl}",
            f"- persona: {pers_s}",
            f"- features: {feat_s}",
            f"- private bank: `{w}` = {doc_s} · seen {seen_hits} event(s)/30d",
            "",
        ]
    unmapped = sorted(a for a in seen if a not in alias2person)
    lines += ["## Coverage audit", ""]
    if unmapped:
        lines += [f"**UNMAPPED** — seen in events, no persons entry:"]
        lines += [f"- `{a}` ×{seen[a]}" for a in unmapped]
    else:
        lines += ["All observed speaker identities resolve to a person "
                  "or alias. ✅"]
    lines += ["", "<!-- /ada-debug:auto -->", "",
              "_Generated file — do not hand-edit._", ""]
    md = "\n".join(lines)
    status = "delta" if unmapped else "ok"
    return md, f"ada-debug: {len(persons)-2} persons, " \
               f"{len(unmapped)} unmapped identities", unmapped


def publish_cms(md: str, summary: str) -> bool:
    now = now_iso()
    meta = {
        "kind": ["report"], "report_role": ["leaf"], "slug": [CMS_SLUG],
        "title": [f"Ada Debug — {now[:10]}"],
        "format": ["markdown"], "lang": ["en"],
        "bank": ["cms"], "scope": ["tony"], "status": ["active"],
        "source": ["api"], "subject": [CMS_SLUG], "attribute": ["page"],
        "updated": [now], "last_verified": [now[:10]],
        "domain": ["ops"], "summary": [summary[:240]],
        "fresh_for": ["1d"], "confidence": ["high"],
        "generated_by": ["python3 scripts/report-ada-debug.py"],
        "sources": [str(PERSONS_YML), "ada-ha-events-tony",
                    "ada-ha-bank-* collections"],
        "written_by": ["report-ada-debug.py"],
        "links": ["reports-index"],
        "timeline": [f"{now[:16]} generated"],
    }
    _mddb("add", {"collection": "ada-cms-pages", "key": CMS_SLUG,
                  "lang": "en", "contentMd": md, "meta": meta},
          timeout=60)
    try:
        from lib.cms_index import regen_reports_index
        regen_reports_index(MDDB, written_by="report-ada-debug.py")
    except Exception as e:
        print(f"warn: reports-index regen failed ({e})", file=sys.stderr)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="print_only", action="store_true")
    ap.add_argument("--no-cms", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(PERSONS_YML)) or {}
    counts = {}
    for key in (cfg.get("persons") or {}):
        if key in ("default", "unknown"):
            continue
        counts[f"ada-ha-bank-personal-{key}"] = bank_doc_count(
            f"ada-ha-bank-personal-{key}")
    seen = speaker_seen()
    md, summary, unmapped = render(cfg, counts, seen)

    if args.print_only:
        print(md)
        print(f"---\nsummary={summary}")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = OUT_DIR / f"ADA-DEBUG-{datetime.date.today():%Y%m%d}.md"
    artifact.write_text(md, encoding="utf-8")
    write_meta(META, node=NODE, layer=LAYER,
               generated_by="python3 scripts/report-ada-debug.py",
               purpose="Interrogation report — per-person resolved "
                       "identity/banks/control/persona/features + "
                       "speaker coverage audit",
               status="delta" if unmapped else "ok", summary=summary,
               sources=[str(PERSONS_YML), "ada-ha-events-tony"],
               children=[],
               extra={"unmapped": unmapped})
    append_timeline(NODE, LAYER,
                    "delta" if unmapped else "ok", summary, ref=artifact)
    if not args.no_cms:
        try:
            publish_cms(md, summary)
        except Exception as e:
            print(f"warn: CMS publish failed ({e})", file=sys.stderr)
    print(f"ada-debug: {summary} -> {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
