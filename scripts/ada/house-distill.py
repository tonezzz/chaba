#!/usr/bin/env python3
"""house-distill.py — distill one lane's raw MDDB telemetry into a house profile.

MDDB topology on idc03 — THREE separate databases, not one:
  mddb.service      primary   HTTP :11023  MCP :9000  ada-ha-* memory/telemetry
  mddb-cms.service  cms store HTTP :11027            ada-cms-*, infra-ssot sync
  mddb-ops.service  ops store                        host-logs, digests
Reads/writes for ada-ha-* MUST go to the primary (:11023); cms-pages writes
go to the cms store (:11027). A bank doc posted to :11027 lands in the wrong
database where no persona backend will ever read it.

Outputs:
  * ada-cms-pages/house-profile-<instance>   browsable at
    https://cms.surf-thailand.com/p/house-profile-<instance>
  * ada-ha-bank-personal-<instance>/house-profile   one compact recall doc so
    the lane persona can answer "what do you know about my house" grounded

Usage:
  house-distill.py --instance michael           # write page + bank doc
  house-distill.py --instance michael --dry-run # print the page, write nothing
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import sys
import urllib.request

MDDB_PRIMARY = os.environ.get(
    "MDDB_PRIMARY_URL", "http://100.102.134.91:11023/v1").rstrip("/")
MDDB_CMS = os.environ.get(
    "MDDB_CMS_URL", "http://100.102.134.91:11027/v1").rstrip("/")
ENTITY_RE = re.compile(r"\(`([a-z_]+\.[a-z0-9_]+)`\):\s*(.+?)\s*$")
EVENT_RE = re.compile(r"— (.+?) \(`([a-z_]+\.[a-z0-9_]+)`\): (.+?) → (.+?)\s*$")
LANE_NAMES = {"michael": "mn-ha", "tony": "tony-ha", "kk": "kk-ha",
              "ada": "ada-ha"}


def _post(base: str, path: str, payload: dict, timeout: int = 60):
    req = urllib.request.Request(
        f"{base}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def iter_docs(collection: str, page: int = 500):
    """All docs in a collection on the PRIMARY store (full contentMd)."""
    off = 0
    while True:
        docs = _post(MDDB_PRIMARY, "search",
                     {"collection": collection, "query": "",
                      "limit": page, "offset": off})
        yield from docs
        off += len(docs)
        if len(docs) < page:
            return


def v1_add(base: str, collection: str, key: str, content_md: str, meta: dict,
           lang: str = "en", timeout: int = 60) -> None:
    _post(base, "add", {"collection": collection, "key": key, "lang": lang,
                        "contentMd": content_md, "meta": meta}, timeout)


def _first(meta: dict, name: str) -> str:
    v = (meta or {}).get(name)
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v else ""


def parse_snapshot(body: str):
    """(entities[(name,eid,state)], meta overview) from a snapshot doc."""
    ents = []
    for ln in (body or "").splitlines():
        m = ENTITY_RE.search(ln)
        if m:
            name = ln.lstrip("- ").split(" (`")[0]
            ents.append((name, m.group(1), m.group(2)))
    return ents


def distill(instance: str) -> tuple[str, dict]:
    snap_col = f"ada-ha-snapshots-{instance}"
    ev_col = f"ada-ha-events-{instance}"

    snaps = list(iter_docs(snap_col))
    snaps.sort(key=lambda d: _first(d["meta"], "refreshed_at"))
    latest = snaps[-1] if snaps else None

    trend = []
    for d in snaps:
        m = d["meta"]
        trend.append((_first(m, "refreshed_at"),
                      int(_first(m, "total_entities") or 0),
                      int(_first(m, "controllable_count") or 0),
                      int(_first(m, "sensor_count") or 0)))

    events = list(iter_docs(ev_col))
    churn = collections.Counter()
    dark = collections.Counter()
    ev_span = [None, None]
    total_ev = 0
    for d in events:
        m = d["meta"]
        total_ev += int(_first(m, "count") or 0)
        ps, pe = _first(m, "period_start"), _first(m, "period_end")
        if ps and (ev_span[0] is None or ps < ev_span[0]):
            ev_span[0] = ps
        if pe and (ev_span[1] is None or pe > ev_span[1]):
            ev_span[1] = pe
        for ln in (d.get("contentMd") or d.get("content_md") or ""
                   ).splitlines():
            em = EVENT_RE.search(ln)
            if not em:
                continue
            name, eid, _old, new = em.groups()
            churn[eid] += 1
            if new.strip() == "unavailable":
                dark[eid] += 1

    ents = parse_snapshot(
        latest.get("contentMd") or latest.get("content_md") or ""
    ) if latest else []
    by_domain = collections.Counter(e[1].split(".")[0] for e in ents)
    unavailable = [(n, e) for n, e, s in ents if s == "unavailable"]

    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date().isoformat()
    lm = (latest["meta"] if latest else {})
    refreshed = _first(lm, "refreshed_at") or "never"
    stale_days = 0
    try:
        stale_days = (now - datetime.datetime.fromisoformat(
            refreshed.replace("Z", "+00:00"))).days
    except Exception:
        pass
    age_days = f" ({stale_days}d old)" if stale_days > 2 else " (live)"

    L = []
    L.append(f"# House profile — {instance} "
             f"({LANE_NAMES.get(instance, instance)})")
    L.append("")
    L.append("Distilled from `ada-ha-snapshots-{i}` + `ada-ha-events-{i}` "
             "by `scripts/ada/house-distill.py` — raw telemetry kept; this is "
             "the readable layer.".format(i=instance))
    L.append("")
    L.append("## Overview")
    L.append(f"- Person entity: `{_first(lm, 'person_entity') or 'unknown'}`")
    L.append(f"- Latest snapshot: {refreshed}{age_days}")
    L.append(f"- Entities: {_first(lm, 'total_entities') or '?'} total · "
             f"{_first(lm, 'controllable_count') or '?'} controllable · "
             f"{_first(lm, 'sensor_count') or '?'} sensors")
    L.append(f"- Snapshots on record: {len(snaps)} "
             f"({trend[0][0][:10] if trend else '?'} → "
             f"{trend[-1][0][:10] if trend else '?'})")
    L.append(f"- Events: {total_ev} transitions in {len(events)} docs "
             f"({(ev_span[0] or '?')[:10]} → {(ev_span[1] or '?')[:10]})")
    L.append("")
    if stale_days > 2:
        L.append(f"> **Staleness warning:** newest telemetry is "
                 f"{stale_days}d old — verify the snapshot/events collectors "
                 "on the lane backend before trusting live facts below.")
        L.append("")
    L.append("## Systems inventory (by entity domain)")
    L.append("")
    for dom, n in by_domain.most_common():
        L.append(f"- `{dom}` — {n}")
    L.append("")
    L.append("## Dark entities (state `unavailable` in latest snapshot)")
    L.append("")
    if unavailable:
        udom = collections.Counter(e.split(".")[0] for _, e in unavailable)
        L.append(f"**{len(unavailable)} entities unavailable** — by domain: "
                 + ", ".join(f"`{d}` {n}" for d, n in udom.most_common()))
        L.append("")
        for name, eid in sorted(unavailable, key=lambda x: x[1])[:60]:
            L.append(f"- {name} (`{eid}`)")
        if len(unavailable) > 60:
            L.append(f"- … +{len(unavailable) - 60} more")
    else:
        L.append("_none — all entities reachable_")
    L.append("")
    L.append("## Activity (events window)")
    L.append("")
    L.append("Top-changed entities:")
    for eid, n in churn.most_common(15):
        L.append(f"- `{eid}` — {n} transitions")
    L.append("")
    if dark:
        L.append("Flap/dropout sources (transitions → unavailable):")
        for eid, n in dark.most_common(10):
            L.append(f"- `{eid}` — {n} drops")
        L.append("")
    L.append("---")
    L.append(f"_generated by house-distill.py — {now.isoformat(timespec='seconds')}_")
    page = "\n".join(L) + "\n"

    meta = {
        "bank": ["cms"], "scope": [instance], "status": ["active"],
        "source": ["api"], "written_by": ["house-distill.py"],
        "subject": [f"house-profile-{instance}"], "attribute": ["page"],
        "kind": ["page"], "format": ["markdown"], "lang": ["en"],
        "valid_from": [today], "last_verified": [today],
        "updated": [now.isoformat(timespec="seconds")],
        "title": [f"House profile — {instance}"],
    }
    return page, meta, ents, events, total_ev, ev_span, stale_days


def bank_doc(instance: str, ents, events, total_ev: int, ev_span,
             stale_days: int) -> tuple[str, dict]:
    """Compact recall doc for the lane persona."""
    now = datetime.datetime.now(datetime.timezone.utc)
    by_domain = collections.Counter(e[1].split(".")[0] for e in ents)
    unavailable = [e for _, e, s in ents if s == "unavailable"]
    span = (f"{(ev_span[0] or '?')[:10]} → {(ev_span[1] or '?')[:10]}"
            if ev_span[0] else "unknown")
    stale = (" Telemetry is fresh." if stale_days <= 2
             else f" Telemetry is {stale_days}d stale.")
    L = [
        f"# {instance} household profile (distilled)",
        "",
        f"Home Assistant `{LANE_NAMES.get(instance, instance)}` has "
        f"~{len(ents)} named entities across "
        f"{len(by_domain)} domains. Top domains: "
        + ", ".join(f"{d}({n})" for d, n in by_domain.most_common(8)) + ".",
        f"{len(unavailable)} entities unavailable at last snapshot; "
        f"telemetry covers {len(events)} event docs / {total_ev} "
        f"transitions, {span}.{stale}",
        "",
        # michael-specific system summary — other lanes get a generic note
        # until per-lane system blurbs are authored.
        ("Systems on record: Solis S6-EH3P10K solar + 3 batteries, RK600 "
         "weather station, gate motor + roller shutters (front door, "
         "kitchen), IEAST oliostream audio x3, LG webOS TV, Broadlink RM4, "
         "Sonoff/fingerbot switches, pool smart meter, ESP32 test display."
         if instance == "michael" else
         "System-level detail is on the CMS page below."),
        "",
        "Full detail: https://cms.surf-thailand.com/p/"
        f"house-profile-{instance}",
    ]
    meta = {"scope": [instance], "kind": ["note"],
            "written_by": ["house-distill.py"], "source": ["api"],
            "subject": ["house-profile"], "status": ["active"],
            "lang": ["en"], "format": ["markdown"],
            "valid_from": [now.date().isoformat()],
            "updated": [now.isoformat(timespec="seconds")]}
    return "\n".join(L) + "\n", meta


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--instance", required=True)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    page, meta, ents, events, total_ev, ev_span, stale_days = \
        distill(a.instance)
    if a.dry_run:
        print(page)
        return 0

    v1_add(MDDB_CMS, "ada-cms-pages", f"house-profile-{a.instance}",
           page, meta)
    body, bmeta = bank_doc(a.instance, ents, events, total_ev, ev_span,
                           stale_days)
    v1_add(MDDB_PRIMARY, f"ada-ha-bank-personal-{a.instance}",
           "house-profile", body, bmeta)
    print(f"wrote ada-cms-pages/house-profile-{a.instance} "
          f"({len(page)} bytes) + personal bank doc")
    return 0


if __name__ == "__main__":
    sys.exit(main())
