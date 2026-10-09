#!/usr/bin/env python3
"""logs-kanban — host-log pipeline health -> kanban cards.

Judges the log-shipping fleet and writes/removes `logs-auto-*` kanban
cards so a broken shipper becomes tracked work instead of a silently
empty digest. Mirrors cms-auto-health.py's lifecycle:

  condition open     -> column=review, note = reason (updates = log)
  condition cleared  -> column=done, note records the recovery
  open >= 12h        -> priority bumped to high

Inputs (all MDDB — no local files, so it can run inside kanban-sync's
detached worktree on any host):
  host-logs-state `ship/<host>`  — one doc per shipper run, written by
    log-shipper.py; distinguishes quiet-host from broken-pipe because
    reachable=False/never-shipped shows up
  host-logs-state `report/24h`   — logs-report's per-host rollup, for
    the severe-count check; ignored when older than 30h

Checks:
  silent       — no state write in >26h (host dropped out of the fleet)
  unreachable  — state.reachable=false (ssh probe failed / ship crashed)
  backlog      — matched - shipped >= 200 (500/day cap can't drain it)
  severe spike — >=40 severe lines in the last 24h for a host
  coverage     — one `logs-coverage` card: expected-host matrix vs what
                 actually ships (missing host, one-sided journals, never)

Bloat rules: cards are rewritten only when the generated dict actually
changes; cleared conditions flip to done rather than staying open; the
coverage matrix is a single card, not one per gap.

Runs anywhere with MDDB access; writes into a chaba checkout. Committing
is the caller's job.

Runs inside kanban-sync.sh on tony-dell — its `git add cards/` block
commits and pushes whatever this writes. --expected to override hosts.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import yaml

MDDB = os.environ.get(
    "MDDB_OPS_URL",
    os.environ.get("MDDB_BASE_URL",
                   "http://100.102.134.91:11026/v1")).rstrip("/")
REPO = Path(os.environ.get("CHABA_REPO",
                           str(Path(__file__).resolve().parents[2])))
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"
STATE_COLLECTION = os.environ.get("LOG_STATE_COLLECTION",
                                  "host-logs-state")

# thresholds live in docs/ssot/infrastructure/ssot.log-digest-standard.yml
# — these are fallbacks only; the SSOT is authoritative
STANDARD = REPO / "docs" / "ssot" / "infrastructure" / \
    "ssot.log-digest-standard.yml"


def _bars() -> dict:
    try:
        return (yaml.safe_load(STANDARD.read_text()) or {}).get(
            "bars") or {}
    except Exception:
        return {}


_B = _bars()
_fleet = _B.get("fleet") or {}
_pipe = _B.get("pipeline") or {}
_sig = _B.get("signal") or {}
_brd = _B.get("board") or {}

EXPECTED_JOURNALS = _fleet.get("journals_per_host") or ["user", "sys"]
JOURNAL_OVERRIDES = _fleet.get("journal_overrides") or {}
SILENT_H = float(_fleet.get("cadence_min", 40)) / 60 * \
    float(_pipe.get("silent_factor", 39.0))  # 60min * 1.5 = 90min
BACKLOG_MIN = int(_pipe.get("backlog_min", 200))
SEVERE_24H = int(_sig.get("severe_24h_max", 40))
ESCALATE_H = int(_brd.get("escalate_h", 12))


def _expected_hosts() -> list[str]:
    """SSOT fleet list wins; log-shipper.py DEFAULT_HOSTS is fallback."""
    if _fleet.get("hosts"):
        return list(_fleet["hosts"])
    spec = importlib.util.spec_from_file_location(
        "logshipper", Path(__file__).with_name("log-shipper.py"))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return list(mod.DEFAULT_HOSTS)
    except Exception:
        return ["idc01", "idc02", "idc03", "mn01", "tony-dell",
                "tony-omen", "michael-ha"]


def _post(path: str, payload: dict, timeout: int = 15):
    try:
        req = urllib.request.Request(
            f"{MDDB}{path}", data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def ship_states() -> tuple[dict[str, dict], dict[str, dict]]:
    """-> (host->ship state, host->{total,severe} from report/24h)."""
    docs = _post("/search", {"collection": STATE_COLLECTION,
                             "query": "", "limit": 100})
    ships: dict[str, dict] = {}
    severe: dict[str, dict] = {}
    report_age_h: float | None = None
    for d in docs or []:
        try:
            st = json.loads(d.get("contentMd") or "{}")
        except json.JSONDecodeError:
            continue
        if d.get("key") == "report/24h":
            for h, v in (st.get("hosts") or {}).items():
                severe[h] = v
            try:
                rep_ts = st.get("ts", "")
                report_age_h = (time.time() - __import__("datetime")
                                .datetime.fromisoformat(rep_ts)
                                .timestamp()) / 3600
            except Exception:
                pass
            continue
        if not d.get("key", "").startswith("ship/"):
            continue  # ship-severe/<host> etc. — side lanes' heartbeats,
            #           judged separately, must not clobber ship/<host>
        st["_ts"] = (d.get("updatedAt") or 0)
        host = st.get("host") or d.get("key", "").split("/")[-1]
        ships[host] = st
    if report_age_h is not None and report_age_h > 30:
        severe = {}  # stale report — don't spike-card on old counts
    return ships, severe


def card_path(slug: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
    return CARDS / f"logs-auto-{safe}.yml"


def load_card(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def judge(states: dict[str, dict], severe: dict[str, dict],
          expected: list[str], now: float) -> list[dict]:
    """-> open conditions [{slug, title, reason, help}]."""
    bad: list[dict] = []
    for host in expected:
        st = states.get(host)
        if st is None:
            bad.append({
                "slug": f"{host}-silent", "host": host,
                "title": f"logs `{host}` never shipped state",
                "reason": f"{host} is in the shipper's host list but has "
                          f"no {STATE_COLLECTION} doc — the shipper never "
                          f"reported (added to fleet but not wired? ssh?)",
                "help": "Run `log-shipper.py --hosts " + host +
                        " --dry-run` from tony-omen; if the ssh probe "
                        "fails, check tailscale auth (browser link)."})
            continue
        age_h = (now - float(st.get("_ts") or 0)) / 3600
        reachable = st.get("reachable", True)
        if not reachable:
            bad.append({
                "slug": f"{host}-unreachable", "host": host,
                "title": f"logs `{host}` ssh probe failed",
                "reason": f"shipper's ssh probe failed — {host} logs are "
                          f"not being collected. error={st.get('error')}",
                "help": "Likely a tailscale ssh auth check on the "
                        "tony-omen -> host hop: run a manual ssh and open "
                        "the login.tailscale.com link it prints, or "
                        "install a local log-shipper timer on " + host +
                        "."})
        elif age_h > SILENT_H:
            bad.append({
                "slug": f"{host}-silent", "host": host,
                "title": f"logs `{host}` silent {int(age_h)}h",
                "reason": f"last ship-state write {age_h:.0f}h ago "
                          f"(limit {SILENT_H}h) — shipper stopped running",
                "help": "Check ada-review-refresh.service on tony-omen "
                        "and whether the host was removed from --hosts."})
        gap = (st.get("scanned") or 0) - (st.get("shipped") or 0)
        if reachable and gap >= BACKLOG_MIN:
            bad.append({
                "slug": f"{host}-backlog", "host": host,
                "title": f"logs `{host}` backlog {gap}",
                "reason": f"last run matched {st.get('scanned')} but the "
                          f"500/run cap shipped only {st.get('shipped')} — "
                          f"drains {int(gap / 500) + 1} days behind",
                "help": "Tighten the GREP/KINDS filter (noise share too "
                        "high) or raise --max-docs until it drains."})
        sev = (severe.get(host) or {}).get("severe", 0)
        if reachable and sev >= SEVERE_24H:
            bad.append({
                "slug": f"{host}-severe-spike", "host": host,
                "title": f"logs `{host}` {sev} severe/24h",
                "reason": f"{sev} severe lines (oom/panic/failed) in the "
                          f"last 24h (limit {SEVERE_24H})",
                "help": "Read the digest's repeat-offender lines for "
                        f"{host}; this is a real incident signal, not "
                        "pipeline breakage."})
    return bad


def coverage_note(states: dict[str, dict], expected: list[str],
                  now: float) -> tuple[list[str], bool]:
    """-> (matrix lines, any_gap)."""
    lines, gap = [], False
    for host in expected:
        st = states.get(host)
        if st is None:
            lines.append(f"- `{host}` — no state (never shipped)")
            gap = True
            continue
        age_h = (now - float(st.get("_ts") or 0)) / 3600
        jr = st.get("journals") or {}
        legs = st.get("journal_legs") or {}
        want = JOURNAL_OVERRIDES.get(host, EXPECTED_JOURNALS)
        if st.get("lane") == "ha-cli-ssh":
            missing = []
        elif legs:
            # authoritative: "denied" = journal unreadable (real gap);
            # "empty"/"ok" = readable, just quiet — not a gap
            missing = [j for j in want if legs.get(j) == "denied"]
        else:
            # legacy states (pre journal_legs): zero rows on a declared
            # journal while a sibling scanned rows — heuristic only
            missing = [j for j in want if jr.get(j, 0) == 0
                       and sum(jr.get(x, 0) for x in want) > 0]
        one_sided = missing[0] if missing else ""
        status = "ok"
        if not st.get("reachable", True):
            status, gap = f"UNREACHABLE ({st.get('error')})", True
        elif age_h > SILENT_H:
            status, gap = f"silent {age_h:.0f}h", True
        if one_sided:
            gap = True
        lines.append(
            f"- `{host}` — {status} [{st.get('lane') or '?'}]; "
            f"shipped {st.get('shipped', 0)}"
            f"/{st.get('scanned', 0)} matched"
            + (f"; `{one_sided}` journal denied (unreadable)"
               if one_sided else ""))
    return lines, gap


RESPECT_CLOSE_D = int((_brd.get("respect_close_days") or 3))


def _human_closed(card: dict, now: float) -> bool:
    """A card a human moved out of review stays closed for
    RESPECT_CLOSE_D days — auto-cards must not fight the operator. A
    persisting condition resurfaces after the cool-down."""
    if card.get("column") != "done":
        return False
    last_human = None
    for c in card.get("comms") or []:
        if c.get("from") not in (None, "logs-kanban", "cms-auto-health"):
            last_human = str(c.get("at") or "")
    if not last_human:
        return False
    try:
        closed_ts = time.mktime(time.strptime(last_human[:10],
                                              "%Y-%m-%d"))
        return (now - closed_ts) < RESPECT_CLOSE_D * 86400
    except (ValueError, TypeError):
        return True  # unparseable stamp -> err on the side of the human


def upsert_card(path: Path, card_id: str, title: str, note: str,
                help_text: str, now: float, today: str) -> str:
    """Write a review card. -> 'created'|'updated'|'unchanged'|'held'."""
    card = load_card(path)
    if _human_closed(card, now):
        return "held"
    opened = card.get("updated") if card.get("column") == "review" \
        else today
    try:
        age_h = (now - time.mktime(
            time.strptime(str(opened), "%Y-%m-%d"))) / 3600
    except (ValueError, TypeError):
        age_h = 0
    card.update({
        "id": card_id,
        "title": title,
        "brief": (f"The log digest flagged something worth a look: "
                  f"{title}. Read the note, then fix it or close the "
                  "card."),
        "column": "review",
        "review_kind": "triage",
        "generated": "logs-kanban",
        "program": "logs-digest",
        "priority": "high" if age_h >= ESCALATE_H else "medium",
        "note": note,
        "help": help_text,
        "updated": opened,
    })
    if path.exists() and card == load_card(path):
        return "unchanged"
    path.write_text(yaml.safe_dump(card, sort_keys=False,
                                   allow_unicode=True))
    return "updated" if path.exists() else "created"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expected", default="",
                    help="comma host list (default: DEFAULT_HOSTS from "
                         "log-shipper.py)")
    args = ap.parse_args()

    expected = [x.strip() for x in args.expected.split(",") if x.strip()] \
        or _expected_hosts()
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    states, severe = ship_states()
    bad = judge(states, severe, expected, now)

    n_open = n_close = 0
    seen_slugs = set()
    for c in bad:
        seen_slugs.add(c["slug"])
        rc = upsert_card(card_path(c["slug"]), f"logs-auto-{c['slug']}",
                         c["title"], c["reason"], c["help"], now, today)
        if rc != "unchanged":
            n_open += 1

    # coverage card — the "what logs are we missing" audit, one card
    matrix, has_gap = coverage_note(states, expected, now)
    cov_path = CARDS / "logs-auto-coverage.yml"
    cov_card = load_card(cov_path)
    if has_gap:
        upsert_card(
            cov_path, "logs-auto-coverage",
            "Log coverage gaps",
            "Expected log sources vs what actually ships:\n\n"
            + "\n".join(matrix),
            "Fix each gap or remove the host from log-shipper "
            "DEFAULT_HOSTS. Journal gaps usually mean `journalctl "
            "--user` isn't permitted for the ssh login.",
            now, today)
        n_open += 1
    elif cov_path.exists() and cov_card.get("column") == "review" and \
            cov_card.get("generated") == "logs-kanban":
        cov_card["column"] = "done"
        cov_card["note"] = (f"Coverage clean {today}: all {len(expected)} "
                            "expected hosts ship both journals.")
        cov_card["updated"] = today
        cov_path.write_text(yaml.safe_dump(cov_card, sort_keys=False,
                                           allow_unicode=True))
        n_close += 1

    # auto-close cleared condition cards
    for path in CARDS.glob("logs-auto-*.yml"):
        slug = path.stem.removeprefix("logs-auto-")
        if slug == "coverage" or slug in seen_slugs:
            continue
        card = load_card(path)
        if card.get("column") == "review" and \
                card.get("generated") == "logs-kanban":
            card["column"] = "done"
            card["note"] = (f"Auto-recovered {today}: `{slug}` condition "
                            "cleared — shipper healthy again.")
            card["updated"] = today
            path.write_text(yaml.safe_dump(card, sort_keys=False,
                                           allow_unicode=True))
            n_close += 1

    print(f"logs-kanban: {len(bad)} open conditions "
          f"({n_open} cards written), {n_close} auto-recovered, "
          f"{len(states)} hosts reporting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
