#!/usr/bin/env python3
"""disk-trend-watch — df trend per host -> disk-auto-* kanban cards + push.

Born from the 2026-10-05 tony-dell disk-full event (/ hit 100%; the
lab-disk-trend-watch card file itself was written 0-bytes). Instantaneous
disk checks already exist in health-monitor.sh (>85/90%), but nothing
watched the *trend* — 8.6G of yt-live-media cache appeared during dub
work and the disk filled between threshold crossings.

One SSH probe per host (df + du watchlist), samples appended to a JSONL
history, least-squares slope per host+mount over a rolling window:

  pct >= CRIT_PCT (90)            -> card (board) + push
  fills in <= FILL_D days (7)     -> card (board) + push
  recovered                       -> card auto-closed (done)

Push goes through board_notify (scripts/board/board_notify.py): default
channels "ha,yomi" — iPhone push now, LINE when the yomi session is
restored and BOARD_NOTIFY_YOMI_CHAT is set (channel decision:
docs/ssot/jobs/kanban/2026-10-05-board-request-notify.yml). Pushes fire
only when a card newly opens/reopens — quiet-by-design.

Top growers: `du -sk` on the watchlist (~/.cache/* + ~/.cache total +
/var/log by default; yt-live-media cache shows up as a child of .cache)
is trended the same way and the largest 24h deltas are flagged in the
report and inside alert card notes.

History/report/meta are NOT in the cards dir:
  ~/var/chaba/health/disk-trend.jsonl   samples (DISK_TREND_HISTORY)
  reports/disk-trend/disk-trend.yml     consolidated trend report
  reports/disk-trend/meta.*.yml         L1 meta (registry node disk-trend)

Runs inside the kanban-sync tick like cms-auto-health — the caller
passes --reports-root pointing at the served checkout so the detached
worktree stays clean; committing cards is kanban-sync's `git add`.

Usage:
  disk-trend-watch.py                    # probe + trend + cards + report
  disk-trend-watch.py --report           # trend table to stdout, no writes
  disk-trend-watch.py --sample-file F    # inject samples instead of probing
  disk-trend-watch.py --selftest         # synthetic >90% fixture end-to-end

Env: DISK_TREND_HISTORY, DISK_TREND_WINDOW_D (7), DISK_TREND_FILL_D (7),
     DISK_TREND_CRIT_PCT (90), DISK_TREND_MIN_SPAN_H (6),
     DISK_TREND_HOSTS (csv limit), DISK_TREND_DU_ROOTS (space-sep, remote
     shell-expanded), DISK_TREND_SSH_TIMEOUT (90), DISK_TREND_DU_EACH_S
     (45, per-dir du cap), DISK_TREND_NOTIFY_CHANNELS (default "ha,yomi"),
     DISK_TREND_RETAIN_D (45), plus BOARD_NOTIFY_* from board_notify.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

REPO = Path(os.environ.get(
    "CHABA_REPO", str(Path(__file__).resolve().parents[2])))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "board"))

import board_notify as bn  # noqa: E402
from lib.report import append_timeline, now_iso, write_meta  # noqa: E402

HOSTS_SSOT = REPO / "docs" / "ssot" / "infrastructure" / "ssot.audit.hosts.yml"
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"

HISTORY = Path(os.environ.get(
    "DISK_TREND_HISTORY", "~/var/chaba/health/disk-trend.jsonl")).expanduser()
WINDOW_D = float(os.environ.get("DISK_TREND_WINDOW_D", "7"))
FILL_D = float(os.environ.get("DISK_TREND_FILL_D", "7"))
CRIT_PCT = float(os.environ.get("DISK_TREND_CRIT_PCT", "90"))
# a trend alert needs samples spanning this long — blocks single-blip
# false positives from two points minutes apart.
MIN_SPAN_H = float(os.environ.get("DISK_TREND_MIN_SPAN_H", "6"))
RETAIN_D = int(os.environ.get("DISK_TREND_RETAIN_D", "45"))
HISTORY_MAX_LINES = 60000
# directory watchlist: du -sk each; glob expands on the remote side.
# .cache children come BEFORE the .cache parent: the parent total is the
# slowest scan (~77s cold on tony-dell) so if the outer timeout kills it
# we still have the per-child numbers — that is where top-growers live.
DU_ROOTS = os.environ.get(
    "DISK_TREND_DU_ROOTS", "$HOME/.cache/*/ $HOME/.cache /var/log")
TOP_GROWERS_N = 5
# only flag dirs that grew at least this much in 24h (MiB).
TOP_GROW_MIN_MIB = 256
SSH_TIMEOUT = int(os.environ.get("DISK_TREND_SSH_TIMEOUT", "90"))
# per-dir cap so one monster tree can't starve the rest of the watchlist.
DU_EACH_S = int(os.environ.get("DISK_TREND_DU_EACH_S", "45"))
ESCALATE_H = 12

SKIP_FSTYPES = {
    "tmpfs", "devtmpfs", "overlay", "squashfs", "ramfs", "efivarfs",
    "autofs", "binfmt_misc", "debugfs", "tracefs", "securityfs", "pstore",
    "bpf", "hugetlbfs", "mqueue", "devpts", "proc", "sysfs", "cgroup",
    "cgroup2", "nsfs", "fusectl", "configfs", "shm", "none", "selinuxfs",
    "fuse.gvfsd-fuse", "fuse.portal", "fuse.rclone", "fuse.sshfs",
}
SKIP_MOUNTS = ("/snap", "/var/snap", "/run", "/dev")

# One probe, both OSes. df first (the essential data — survives a du
# timeout because TimeoutExpired carries partial stdout), then the dir
# watchlist. Linux gets -T so fstype filtering is exact; macOS df -Pk
# has no type column and only /dev/disk* filesystems are kept.
PROBE = """{
if [ -r /proc/loadavg ]; then df -PTk; else df -Pk; fi
echo "@@DIRS@@"
TO=$(command -v timeout || command -v gtimeout || true)
for d in %s; do
  [ -e "$d" ] || continue
  if [ -n "$TO" ]; then "$TO" %d du -sk "$d" 2>/dev/null; else du -sk "$d" 2>/dev/null; fi
done
} 2>/dev/null""" % (DU_ROOTS, DU_EACH_S)


def load_hosts() -> dict[str, str | None]:
    doc = yaml.safe_load(HOSTS_SSOT.read_text(encoding="utf-8")) or {}
    out = {k: (v or {}).get("tailscale_ip")
           for k, v in (doc.get("hosts") or {}).items()
           if isinstance(v, dict)}
    limit = os.environ.get("DISK_TREND_HOSTS")
    if limit:
        keep = {h.strip() for h in limit.split(",") if h.strip()}
        out = {h: ip for h, ip in out.items() if h in keep}
    return out


def _partial_stdout(e: subprocess.TimeoutExpired) -> str:
    """TimeoutExpired.stdout is bytes even under text=True — decode it or
    the partial df section captured before a slow du is silently dropped."""
    out = e.stdout or e.output or ""
    return out.decode("utf-8", "replace") if isinstance(out, bytes) else out


def _probe_local() -> str:
    try:
        r = subprocess.run(["sh", "-c", PROBE], capture_output=True,
                           text=True, timeout=SSH_TIMEOUT)
        return r.stdout or ""
    except subprocess.TimeoutExpired as e:
        return _partial_stdout(e)


def _probe_ssh(host: str, ip: str | None) -> str:
    for target in (host, ip):
        if not target:
            continue
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
                 target, PROBE],
                capture_output=True, text=True, timeout=SSH_TIMEOUT)
            if r.stdout and r.stdout.strip():
                return r.stdout
        except subprocess.TimeoutExpired as e:
            # df section usually emitted before a slow du killed the ssh;
            # partial output still parses.
            out = _partial_stdout(e)
            if out.strip():
                return out
        except OSError:
            continue
    return ""


def parse_probe(out: str) -> dict:
    """-> {"mounts": [...], "dirs": [...]} from probe stdout."""
    mounts: dict[str, dict] = {}   # dedupe key: filesystem device
    dirs: dict[str, dict] = {}
    in_dirs = False
    for line in out.splitlines():
        line = line.rstrip()
        if line == "@@DIRS@@":
            in_dirs = True
            continue
        if in_dirs:
            p = line.split(None, 1)
            if len(p) == 2 and p[0].isdigit():
                dirs[p[1]] = {"path": p[1], "kb": int(p[0])}
            continue
        p = line.split()
        if len(p) < 6 or p[0] == "Filesystem":
            continue
        # linux: fs type blocks used avail pct mount (7 cols)
        # macos: fs blocks used avail pct mount     (6 cols)
        has_type = len(p) >= 7 and p[2].isdigit()
        fs, fstype = p[0], (p[1] if has_type else None)
        tail = p[2:] if has_type else p[1:]
        if len(tail) < 5 or not tail[0].isdigit():
            continue
        try:
            size_kb, used_kb, avail_kb = (int(tail[0]), int(tail[1]),
                                          int(tail[2]))
            pct = float(tail[3].rstrip("%"))
        except ValueError:
            continue
        mount = tail[4]
        if fstype:
            if fstype in SKIP_FSTYPES or fstype.startswith("fuse."):
                continue
        elif not fs.startswith("/dev/"):
            continue
        if mount.startswith(SKIP_MOUNTS) and mount != "/":
            continue
        row = {"mount": mount, "fs": fs, "size_kb": size_kb,
               "used_kb": used_kb, "avail_kb": avail_kb, "pct": pct}
        prev = mounts.get(fs)
        # dedupe same device mounted twice (btrfs subvols, APFS roles):
        # keep the shorter mount path — "/" over "/System/Volumes/Data".
        if prev is None or len(mount) < len(prev["mount"]):
            mounts[fs] = row
    return {"mounts": list(mounts.values()), "dirs": list(dirs.values())}


def sample_host(host: str, ip: str | None) -> dict:
    local = host == socket.gethostname()
    out = _probe_local() if local else _probe_ssh(host, ip)
    rec = {"ts": now_iso(), "epoch": time.time(), "host": host,
           "unreachable": not bool(out.strip()), "mounts": [], "dirs": []}
    if out.strip():
        rec.update(parse_probe(out))
    return rec


def load_sample_file(path: Path) -> list[dict]:
    """Fixture mode: {host: {unreachable?, mounts: [...], dirs: [...]}}."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    recs = []
    for host, d in doc.items():
        rec = {"ts": now_iso(), "epoch": time.time(), "host": host,
               "unreachable": bool(d.get("unreachable")),
               "mounts": d.get("mounts") or [],
               "dirs": d.get("dirs") or []}
        recs.append(rec)
    return recs


def append_history(recs: list[dict], history: Path) -> None:
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False,
                               separators=(",", ":")) + "\n")


def prune_history(history: Path) -> int:
    """Cap the log — rewrite only when it exceeds HISTORY_MAX_LINES."""
    try:
        lines = [l for l in history.read_text(
            encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return 0
    if len(lines) <= HISTORY_MAX_LINES:
        return 0
    cutoff = time.time() - RETAIN_D * 86400
    kept = []
    for l in lines:
        try:
            if json.loads(l).get("epoch", 0) >= cutoff:
                kept.append(l)
        except json.JSONDecodeError:
            continue
    history.write_text("\n".join(kept[-HISTORY_MAX_LINES:]) + "\n",
                       encoding="utf-8")
    return len(lines) - len(kept)


def load_history(history: Path, window_s: float) -> dict[str, list[dict]]:
    """-> {host: [records in window, oldest-first]}."""
    since = time.time() - window_s
    out: dict[str, list[dict]] = {}
    try:
        lines = history.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for l in lines:
        if not l.strip():
            continue
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        if r.get("epoch", 0) >= since and r.get("host"):
            out.setdefault(r["host"], []).append(r)
    return out


def slope_kb_day(points: list[tuple[float, float]]) -> float | None:
    """Least-squares KiB/day, or None when the span is too thin."""
    if len(points) < 2:
        return None
    if points[-1][0] - points[0][0] < MIN_SPAN_H * 3600:
        return None
    n = len(points)
    mt = sum(t for t, _ in points) / n
    mu = sum(u for _, u in points) / n
    den = sum((t - mt) ** 2 for t, _ in points)
    if den <= 0:
        return None
    return (sum((t - mt) * (u - mu) for t, u in points) / den) * 86400


def mount_trends(hist: list[dict]) -> dict[str, dict]:
    """-> {mount: {slope_kb_day, days_to_full, latest}} for one host."""
    per: dict[str, list[tuple[float, float]]] = {}
    latest: dict[str, dict] = {}
    for rec in hist:
        for m in rec.get("mounts") or []:
            per.setdefault(m["mount"], []).append(
                (rec["epoch"], m["used_kb"]))
            latest[m["mount"]] = m
    out = {}
    for mount, pts in per.items():
        pts.sort()
        slope = slope_kb_day(pts)
        m = latest[mount]
        days = (m["avail_kb"] / slope) if slope and slope > 0 else None
        out[mount] = {"slope_kb_day": slope, "days_to_full": days,
                      "latest": m, "samples": len(pts)}
    return out


def dir_trends(hist: list[dict]) -> dict[str, dict]:
    """-> {path: {kb, delta_24h_kb}} for one host."""
    latest: dict[str, dict] = {}
    ref: dict[str, tuple[float, int]] = {}
    now = time.time()
    for rec in hist:
        for d in rec.get("dirs") or []:
            latest[d["path"]] = d
            # sample closest to now-24h wins the delta baseline
            gap = abs(rec["epoch"] - (now - 86400))
            cur = ref.get(d["path"])
            if cur is None or gap < cur[0]:
                ref[d["path"]] = (gap, d["kb"])
    out = {}
    for path, d in latest.items():
        delta = None
        base = ref.get(path)
        if base is not None and base[0] <= 12 * 3600:
            delta = d["kb"] - base[1]
        out[path] = {"kb": d["kb"], "delta_24h_kb": delta}
    return out


def mount_slug(mount: str) -> str:
    if mount == "/":
        return "root"
    s = "".join(c if c.isalnum() else "-" for c in mount.strip("/"))
    return "-".join(x for x in s.split("-") if x) or "root"


def card_path(host: str, mount: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in host)
    return CARDS / f"disk-auto-{safe}-{mount_slug(mount)}.yml"


def load_card(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def judge(mount: str, t: dict) -> tuple[str, str]:
    """-> (state, reason): ok|fill|critical."""
    m = t["latest"]
    if m["pct"] >= CRIT_PCT:
        return "critical", f"{m['pct']:.0f}% used ({m['avail_kb'] / 2**20:.1f} GiB free)"
    days = t["days_to_full"]
    if days is not None and days <= FILL_D:
        rate = t["slope_kb_day"] / 2**20
        return "fill", (f"{m['pct']:.0f}% used, growing {rate:.1f} GiB/day "
                        f"-> full in ~{days:.1f}d")
    return "ok", ""


def is_fresh_open(path: Path, card: dict) -> bool:
    """True when this write (re)opens the card — push-worthy."""
    return (not path.exists()) or card.get("column") != "review"


def upsert_alert_card(path: Path, host: str, mount: str, state: str,
                      reason: str, note_extra: str, now: float,
                      today: str) -> str:
    """-> 'opened'|'updated'|'unchanged'."""
    card = load_card(path)
    fresh = is_fresh_open(path, card)
    opened = card.get("updated") if card.get("column") == "review" else today
    try:
        age_h = (now - time.mktime(
            time.strptime(str(opened), "%Y-%m-%d"))) / 3600
    except (ValueError, TypeError):
        age_h = 0
    card.update({
        "id": path.stem,
        "title": (f"Disk {host} {mount} {'critical' if state == 'critical' else 'fills in <' + str(int(FILL_D)) + 'd'}"),
        "brief": (f"Disk space on {host} ({mount}) is running "
                  f"{'critically ' if state == 'critical' else ''}low — "
                  "check the note for the rate and top growers, then "
                  "free space or close the card."),
        "column": "review",
        "review_kind": "triage",
        "generated": "disk-trend-watch",
        "area": "monitoring",
        "priority": "high" if (state == "critical" or age_h >= ESCALATE_H)
        else "medium",
        "note": reason + (" " + note_extra if note_extra else ""),
        "help": ("Free space or slow the growth — check the top growers in "
                 "reports/disk-trend/disk-trend.yml. tony-dell playbook "
                 "(2026-10-05): mddb backups, pip/go caches, journalctl "
                 "--vacuum-size, ~/.cache/yt-live-media LRU is 8GiB."),
        "updated": opened,
    })
    if path.exists() and card == load_card(path):
        return "unchanged"
    path.write_text(yaml.safe_dump(card, sort_keys=False,
                                   allow_unicode=True))
    return "opened" if fresh else "updated"


def close_card(path: Path, today: str, why: str) -> bool:
    card = load_card(path)
    if card.get("column") != "review" or \
            card.get("generated") != "disk-trend-watch":
        return False
    card["column"] = "done"
    card["note"] = f"Auto-recovered {today}: {why}"
    card["updated"] = today
    path.write_text(yaml.safe_dump(card, sort_keys=False,
                                   allow_unicode=True))
    return True


def top_growers(dt: dict[str, dict], n: int = TOP_GROWERS_N) -> list[dict]:
    """Dirs with the biggest 24h growth (>= TOP_GROW_MIN_MIB)."""
    rows = []
    for path, d in dt.items():
        delta = d.get("delta_24h_kb")
        if delta is not None and delta >= TOP_GROW_MIN_MIB * 1024:
            rows.append({"path": path, "kb": d["kb"],
                         "delta_24h_kb": delta})
    return sorted(rows, key=lambda r: -r["delta_24h_kb"])[:n]


def notify_opened(new_cards: list[str]) -> bool:
    """One batched push for cards that (re)opened this tick."""
    if not new_cards:
        return True
    if len(new_cards) == 1:
        title, body = "Disk trend alert", new_cards[0]
    else:
        title = f"Disk trend: {len(new_cards)} mounts filling"
        body = "\n".join(f"• {c}" for c in new_cards[:10])
    return bn.send(title, body, channel=os.environ.get(
        "DISK_TREND_NOTIFY_CHANNELS", "ha,yomi"))


def write_report(host_reports: list[dict], reports_root: Path) -> Path:
    out_dir = reports_root / "disk-trend"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "disk-trend.yml"
    path.write_text(yaml.safe_dump(
        {"generated_at": now_iso(), "window_d": WINDOW_D,
         "fill_threshold_d": FILL_D, "crit_pct": CRIT_PCT,
         "hosts": host_reports},
        sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def gib(kb) -> float | None:
    return round(kb / 2**20, 2) if kb is not None else None


def build_host_report(rec: dict, trends: dict, growers: list[dict],
                      states: dict[str, str]) -> dict:
    mounts = []
    for mount in sorted(trends):
        t = trends[mount]
        m = t["latest"]
        mounts.append({
            "mount": mount, "pct": m["pct"], "used_gib": gib(m["used_kb"]),
            "avail_gib": gib(m["avail_kb"]),
            "growth_gib_day": gib(t["slope_kb_day"]),
            "days_to_full": (round(t["days_to_full"], 1)
                             if t["days_to_full"] is not None else None),
            "alert": states.get(mount, "ok"),
            "samples": t["samples"],
        })
    return {
        "host": rec["host"], "unreachable": rec["unreachable"],
        "mounts": mounts,
        "top_growers_24h": [
            {"path": g["path"], "gib": gib(g["kb"]),
             "delta_gib": gib(g["delta_24h_kb"])}
            for g in growers],
    }


def format_report(host_reports: list[dict]) -> str:
    lines = [f"disk-trend report ({now_iso()}) — window {WINDOW_D:g}d, "
             f"alert if full <={FILL_D:g}d or pct >={CRIT_PCT:g}%", ""]
    for h in host_reports:
        lines.append(f"{h['host']}" + (" [unreachable]"
                                      if h["unreachable"] else ""))
        for m in h["mounts"]:
            rate = (f"{m['growth_gib_day']:+.2f} GiB/d"
                    if m["growth_gib_day"] is not None else "  n/a slope")
            fill = (f"full in {m['days_to_full']:.1f}d"
                    if m["days_to_full"] is not None else "          -")
            flag = {"ok": "", "fill": "  <== FILLS",
                    "critical": "  <== CRITICAL"}[m["alert"]]
            lines.append(f"  {m['mount']:<28} {m['pct']:>5.0f}% "
                         f"{m['avail_gib']:>7.1f} GiB free  {rate}  {fill}"
                         f"{flag}")
        for g in h["top_growers_24h"]:
            lines.append(f"    grower {g['path']}: +{g['delta_gib']:.2f} "
                         f"GiB/24h ({g['gib']:.1f} GiB)")
        lines.append("")
    return "\n".join(lines)


def run(sample_file: Path | None, history: Path, cards_dir: Path,
        reports_root: Path, no_notify: bool) -> int:
    global CARDS
    CARDS = cards_dir
    now = time.time()
    today = time.strftime("%Y-%m-%d")

    if sample_file:
        recs = load_sample_file(sample_file)
    else:
        hosts = load_hosts()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            recs = list(ex.map(lambda kv: sample_host(*kv),
                               sorted(hosts.items())))
    append_history(recs, history)
    pruned = prune_history(history)

    hist = load_history(history, WINDOW_D * 86400)
    host_reports = []
    opened: list[str] = []
    n_alert = n_close = 0
    for rec in recs:
        host = rec["host"]
        if rec["unreachable"]:
            host_reports.append({"host": host, "unreachable": True,
                                 "mounts": [], "top_growers_24h": []})
            continue
        trends = mount_trends(hist.get(host, []))
        growers = top_growers(dir_trends(hist.get(host, [])))
        grower_note = ("top grower 24h: "
                       + ", ".join(f"{g['path']} +{g['delta_24h_kb'] / 2**20:.1f} GiB"
                                   for g in growers[:3])) if growers else ""
        states: dict[str, str] = {}
        for mount, t in trends.items():
            state, reason = judge(mount, t)
            states[mount] = state
            path = card_path(host, mount)
            if state != "ok":
                n_alert += 1
                rc = upsert_alert_card(path, host, mount, state, reason,
                                       grower_note, now, today)
                if rc == "opened":
                    opened.append(f"{host} {mount}: {reason}"
                                  + (f" ({grower_note})"
                                     if grower_note else ""))
            else:
                # recovered: pct below crit and trend no longer fills
                if close_card(path, today,
                              f"{host} {mount} back in bounds "
                              f"({t['latest']['pct']:.0f}%, "
                              f"slope {gib(t['slope_kb_day'])} GiB/d)"):
                    n_close += 1
        host_reports.append(
            build_host_report(rec, trends, growers, states))

    # stale cards: mounts that disappeared from samples entirely. Cards
    # for unreachable hosts are kept — no data this tick must not close
    # an open alert (a flaky host would flap the card + re-push later).
    seen = {card_path(r["host"], m["mount"]).stem
            for r in recs if not r["unreachable"]
            for m in r["mounts"]}
    down = {"".join(c if c.isalnum() or c in "-_" else "-"
                    for c in r["host"])
            for r in recs if r["unreachable"]}
    for path in CARDS.glob("disk-auto-*.yml"):
        if any(path.stem.startswith(f"disk-auto-{h}-") for h in down):
            continue
        if path.stem not in seen and close_card(
                path, today, "mount no longer sampled"):
            n_close += 1

    if opened and not no_notify:
        notify_opened(opened)

    report_path = write_report(host_reports, reports_root)
    n_hosts = sum(1 for r in recs if not r["unreachable"])
    n_mounts = sum(len(h["mounts"]) for h in host_reports)
    summary = (f"{n_hosts}/{len(recs)} hosts, {n_mounts} mounts trended, "
               f"{n_alert} alerting, {n_close} auto-recovered")
    status = "delta" if n_alert else "ok"
    write_meta(
        reports_root / "disk-trend" / "meta.disk-trend.yml",
        node="disk-trend", layer="L1-producer",
        generated_by="scripts/ada/disk-trend-watch.py via kanban-sync.timer",
        purpose="df trend per host — days-to-full forecast + top-grower "
                "dirs; disk-auto-* kanban cards + push on open",
        status=status, summary=summary,
        sources=[str(report_path), str(history)],
        children=[], extra={"alerting": n_alert,
                            "history": str(history)})
    append_timeline("disk-trend", "L1", status, summary, ref=report_path)
    print(f"disk-trend-watch: {summary}"
          + (f", pruned {pruned} history rows" if pruned else ""))
    return 0


def selftest() -> int:
    """Synthetic >90% fixture end-to-end: history -> trend -> card+push."""
    with tempfile.TemporaryDirectory(prefix="disk-trend-test-") as td:
        td = Path(td)
        history, cards, reports = td / "hist.jsonl", td / "cards", td / "reports"
        sink = td / "notify.jsonl"
        cards.mkdir()
        now = time.time()
        # synth host: / at 92%, grew 40 GiB over 3 days; another host ok.
        size = 500 * 2**20          # 500 GiB
        used_now = int(0.92 * size)
        hist_lines = []
        for i, age_h in enumerate((72, 48, 24)):
            used = used_now - int(40 * 2**20 * (age_h / 72))
            hist_lines.append(json.dumps({
                "ts": now_iso(), "epoch": now - age_h * 3600,
                "host": "synth-dell", "unreachable": False,
                "mounts": [{"mount": "/", "fs": "/dev/sda2",
                            "size_kb": size, "used_kb": used,
                            "avail_kb": size - used,
                            "pct": used / size * 100}],
                "dirs": [{"path": "/home/tony/.cache/yt-live-media",
                          "kb": (9 - i) * 2**20}]}))
        history.write_text("\n".join(hist_lines) + "\n")
        sample = {
            "synth-dell": {"mounts": [
                {"mount": "/", "fs": "/dev/sda2", "size_kb": size,
                 "used_kb": used_now, "avail_kb": size - used_now,
                 "pct": 92.0}],
                "dirs": [{"path": "/home/tony/.cache/yt-live-media",
                          "kb": 9 * 2**20}]},
            "synth-omen": {"mounts": [
                {"mount": "/", "fs": "/dev/sda1", "size_kb": size,
                 "used_kb": int(0.4 * size), "avail_kb": int(0.6 * size),
                 "pct": 40.0}]},
        }
        sf = td / "sample.json"
        sf.write_text(json.dumps(sample))
        os.environ["DISK_TREND_NOTIFY_CHANNELS"] = "file"
        os.environ["BOARD_NOTIFY_FILE"] = str(sink)
        rc = run(sf, history, cards, reports, no_notify=False)
        assert rc == 0
        card = cards / "disk-auto-synth-dell-root.yml"
        ok = True
        if not card.is_file():
            print("FAIL: alert card not written")
            ok = False
        else:
            doc = yaml.safe_load(card.read_text())
            print(f"card: {doc['id']} col={doc['column']} "
                  f"prio={doc['priority']} note={doc['note'][:80]}")
            ok &= doc["column"] == "review" and doc["priority"] == "high"
        if not sink.is_file() or "Disk" not in sink.read_text():
            print("FAIL: notify sink empty")
            ok = False
        else:
            print(f"notify: {sink.read_text().strip()[:120]}")
        rep = yaml.safe_load(
            (reports / "disk-trend" / "disk-trend.yml").read_text())
        synth = next(h for h in rep["hosts"] if h["host"] == "synth-dell")
        m0 = synth["mounts"][0]
        print(f"trend: pct={m0['pct']} growth={m0['growth_gib_day']} "
              f"GiB/d fill={m0['days_to_full']}d alert={m0['alert']}")
        ok &= m0["alert"] == "critical" and m0["growth_gib_day"] > 0
        grower = synth["top_growers_24h"]
        print(f"growers: {grower}")
        print(format_report(rep["hosts"]))
        print("SELFTEST " + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sample-file", type=Path, default=None,
                   help="JSON fixture replacing live probes")
    p.add_argument("--history", type=Path, default=HISTORY)
    p.add_argument("--cards-dir", type=Path, default=CARDS)
    p.add_argument("--reports-root", type=Path,
                   default=REPO / "reports")
    p.add_argument("--report", action="store_true",
                   help="print the trend table from history; no writes")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--no-notify", action="store_true")
    args = p.parse_args()

    if args.selftest:
        return selftest()
    if args.report:
        recs_by_host: dict[str, dict] = {}
        for rec_list in load_history(
                args.history, WINDOW_D * 86400).values():
            for r in rec_list:
                recs_by_host[r["host"]] = r
        hist = load_history(args.history, WINDOW_D * 86400)
        reports = []
        for host, rec in sorted(recs_by_host.items()):
            trends = mount_trends(hist.get(host, []))
            growers = top_growers(dir_trends(hist.get(host, [])))
            states = {m: judge(m, t)[0] for m, t in trends.items()}
            reports.append(build_host_report(rec, trends, growers, states))
        print(format_report(reports))
        return 0
    return run(args.sample_file, args.history, args.cards_dir,
               args.reports_root, args.no_notify)


if __name__ == "__main__":
    sys.exit(main())
