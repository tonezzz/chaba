#!/usr/bin/env python3
"""retry-storm-watch — surface sustained retry storms / hot containers.

card ops-retry-storm-detection (MEM-1192): the mddb-embed OpenRouter
retry storm burned ~6h before anyone looked — found via a load
investigation, never surfaced. This is the cheap periodic detector.

Checks (each skippable via --checks):

  cpu   — sample `podman stats` (stream, --stats-secs) for a real
          interval CPU%; a container above --cpu-threshold (default 50%)
          for >= --sustain-min (default 30min, tracked across ticks in
          the state file) files an alert. First sighting only arms the
          timer — one hot sample never pages.

  logs  — `podman logs --since <window>` (default 60m) for every running
          container; WARN/ERROR/FATAL lines are normalized into
          signatures (timestamps/hex/ids/numbers stripped). Any signature
          seen >= --log-threshold (default 30) times in the window files
          an alert — the 'embedding attempt failed' retry-storm shape.

  mddb  — for each URL in MDDB_WATCH_URLS / --mddb-urls (comma-sep base
          URLs, e.g. http://127.0.0.1:11023): GET /v1/vector-stats plus
          /metrics, sum numeric counters whose names match
          drop|error|retr|fail|reject|queue, and alert when the sum
          climbs by >= --mddb-delta (default 10) since the previous
          tick. First tick only establishes the baseline.

Alert channel: board-api /inbox — deduped focus-inbox entry, at most
once per --repeat-h (default 6h) per condition. Never Telegram (noise
policy). Recovery is silent + journaled, matching inbox semantics.

Exit 0 healthy, 1 when alerting.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

BOARD_API = "https://idc03.taila0626a.ts.net:10000"
STATE = Path.home() / ".local/state/retry-storm-watch.json"
LABEL = "Retry storm / hot container detected"
TAGS = ["ops", "monitor", "retry-storm", "podman", "mddb"]

SEV_RE = re.compile(r"\b(WARN(?:ING)?|ERROR|ERR|FATAL|CRITICAL)\b", re.I)
HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
NUM_RE = re.compile(r"\d+")
NONALNUM_RE = re.compile(r"[^a-z0-9]+")
MDDB_COUNTER_RE = re.compile(
    r"drop|error|retr|fail|reject|queue|dropped", re.I)
PROM_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)")


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(dt_obj: dt.datetime) -> str:
    return dt_obj.isoformat()


def parse_ts(s: str):
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(STATE.name + ".tmp")
    with tmp.open("w") as f:
        f.write(json.dumps(st))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(STATE)


def podman_names() -> list:
    """Running container names, or [] when podman is absent/broken."""
    try:
        out = subprocess.run(
            ["podman", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=20)
        if out.returncode != 0:
            return []
        return [n for n in out.stdout.split() if n]
    except Exception:
        return []


def cpu_samples(secs: int) -> dict:
    """{name: cpu_percent} — last streamed row per container.

    `podman stats --no-stream` reports a lifetime-ish average; the
    stream's final row is a true short-interval measurement, which is
    what a >50%-for-30min tripwire needs.
    """
    latest = {}
    try:
        proc = subprocess.Popen(
            ["podman", "stats", "--format",
             "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            deadline = now_utc().timestamp() + secs
            for line in proc.stdout:
                if now_utc().timestamp() > deadline:
                    break
                parts = line.strip().split("|")
                if len(parts) >= 2 and parts[0]:
                    latest[parts[0]] = parts[1]
        finally:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:
        pass
    out = {}
    for name, pct_s in latest.items():
        m = re.match(r"([\d.]+)", pct_s.strip().rstrip("%"))
        if m:
            out[name] = float(m.group(1))
    return out


def check_cpu(st: dict, args) -> list:
    """Return [(cond, text)] for containers hot >= sustain-min."""
    problems = []
    samples = cpu_samples(args.stats_secs)
    cpu_state = st.setdefault("cpu", {})
    now = now_utc()
    seen = set()
    for name, pct in samples.items():
        seen.add(name)
        ent = cpu_state.setdefault(name, {})
        ent["last_pct"] = pct
        ent["last_seen"] = iso(now)
        if pct > args.cpu_threshold:
            if not ent.get("hot_since"):
                ent["hot_since"] = iso(now)
                print(f"cpu watch armed: {name} {pct:.0f}% "
                      f"(>{args.cpu_threshold:.0f}%)")
            hot_since = parse_ts(ent["hot_since"])
            if hot_since and (now - hot_since).total_seconds() \
                    >= args.sustain_min * 60:
                mins = int((now - hot_since).total_seconds() // 60)
                problems.append((
                    f"cpu-hot:{name}",
                    f"container {name} CPU {pct:.0f}% sustained "
                    f"{mins}min (>{args.cpu_threshold:.0f}% for "
                    f">={args.sustain_min}min) — possible retry storm"))
        else:
            if ent.pop("hot_since", None):
                print(f"cpu watch cleared: {name} back to {pct:.0f}%")
    for name in list(cpu_state):
        if name not in seen:
            cpu_state.pop(name, None)
    return problems


def sig_of(line: str) -> str:
    """Normalize a log line into a storm signature."""
    s = HEX_RE.sub("<hex>", line.strip().lower())
    s = NUM_RE.sub("N", s)
    s = NONALNUM_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()[:100]


def check_logs(st: dict, args, names: list) -> list:
    problems = []
    skip = {s.strip() for s in args.log_skip.split(",") if s.strip()}
    threshold = args.log_threshold
    for name in names:
        if name in skip:
            continue
        sigs = {}
        try:
            # stderr=STDOUT: container WARN/ERROR usually lands on the
            # container's stderr stream — must not be dropped.
            proc = subprocess.run(
                ["timeout", str(args.log_timeout), "podman", "logs",
                 "--since", args.log_window, "--tail", "50000", name],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=args.log_timeout + 5)
            lines = (proc.stdout or "").splitlines()
        except Exception:
            continue
        for line in lines:
            if not SEV_RE.search(line):
                continue
            sig = sig_of(line)
            if not sig:
                continue
            cnt, example = sigs.get(sig, (0, line.strip()[:160]))
            sigs[sig] = (cnt + 1, example)
        if not sigs:
            continue
        sig, (cnt, example) = max(sigs.items(), key=lambda kv: kv[1][0])
        if cnt >= threshold:
            problems.append((
                f"log-storm:{name}",
                f"container {name}: identical WARN/ERROR signature x{cnt} "
                f"in last {args.log_window} (>= {threshold}) — e.g. "
                f"'{example}'"))
    return problems


def walk_numbers(obj, path=""):
    """Yield (path, float) for every numeric leaf in a JSON tree."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_numbers(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_numbers(v, f"{path}[{i}]")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield path, float(obj)


def mddb_score(base: str):
    """Sum of drop/error/retry-ish counters across vector-stats + metrics.

    Returns None when BOTH endpoints fail — a dead MDDB must not write a
    0 baseline, or the next good fetch would fake a massive delta.
    """
    total = 0.0
    ok = 0
    try:
        req = urllib.request.Request(
            base.rstrip("/") + "/v1/vector-stats",
            headers={"User-Agent": "retry-storm-watch/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        for path, val in walk_numbers(data):
            if MDDB_COUNTER_RE.search(path):
                total += val
        ok += 1
    except Exception as e:
        print(f"mddb vector-stats {base}: {e}", file=sys.stderr)
    try:
        req = urllib.request.Request(
            base.rstrip("/") + "/metrics",
            headers={"User-Agent": "retry-storm-watch/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read().decode("utf-8", "replace")
        for line in text.splitlines():
            if line.startswith("#"):
                continue
            m = PROM_RE.match(line.strip())
            if not m:
                continue
            name = m.group(1)
            if not MDDB_COUNTER_RE.search(name):
                continue
            try:
                total += float(m.group(3))
            except ValueError:
                pass
        ok += 1
    except Exception as e:
        print(f"mddb metrics {base}: {e}", file=sys.stderr)
    return total if ok else None


def check_mddb(st: dict, args) -> list:
    urls = [u.strip() for u in args.mddb_urls.split(",") if u.strip()]
    if not urls:
        return []
    problems = []
    prev = st.setdefault("mddb", {})
    now = iso(now_utc())
    for base in urls:
        score = mddb_score(base)
        host = re.sub(r"^https?://", "", base).rstrip("/")
        if score is None:
            print(f"mddb unreachable {host} — baseline kept", file=sys.stderr)
            continue
        ent = prev.get(host, {})
        old = ent.get("score")
        ent["score"] = score
        ent["ts"] = now
        prev[host] = ent
        if old is None:
            print(f"mddb baseline {host}: score={score:.0f}")
            continue
        delta = score - float(old)
        if delta >= args.mddb_delta:
            problems.append((
                f"mddb-queue:{host}",
                f"MDDB queue/embed error counters climbing at {host}: "
                f"+{delta:.0f} drop/error/retry-ish since last check "
                f"(now {score:.0f}, was {float(old):.0f}) — possible "
                f"embedding retry storm"))
    return problems


def file_inbox(text: str) -> bool:
    body = {"text": text, "label": LABEL, "priority": "high",
            "tags": TAGS, "owner": "tony"}
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/inbox", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception as e:
        sys.stderr.write(f"retry-storm-watch: inbox post failed: {e}\n")
        return False


def recently_alerted(st: dict, cond: str, repeat_h: float) -> bool:
    try:
        at = st.get("alerts", {}).get(cond)
        return bool(at) and (
            now_utc() - parse_ts(at)).total_seconds() < repeat_h * 3600
    except Exception:
        return False


def main() -> int:
    global STATE, BOARD_API
    ap = argparse.ArgumentParser()
    ap.add_argument("--checks", default="cpu,logs,mddb",
                    help="comma list: cpu,logs,mddb (default all)")
    ap.add_argument("--no-alert", action="store_true",
                    help="check only, print verdict")
    ap.add_argument("--cpu-threshold", type=float, default=50.0)
    ap.add_argument("--sustain-min", type=float, default=30.0)
    ap.add_argument("--stats-secs", type=int, default=6,
                    help="seconds to stream podman stats per tick")
    ap.add_argument("--log-window", default="60m",
                    help="podman logs --since window (e.g. 60m, 2h)")
    ap.add_argument("--log-threshold", type=int, default=30,
                    help="identical WARN/ERROR sig count that alerts")
    ap.add_argument("--log-timeout", type=int, default=30,
                    help="per-container podman logs timeout (s)")
    ap.add_argument("--log-skip", default="",
                    help="comma-separated container names to skip")
    ap.add_argument("--mddb-urls", default=os.environ.get(
        "MDDB_WATCH_URLS", ""),
        help="comma-separated MDDB base URLs (env MDDB_WATCH_URLS)")
    ap.add_argument("--mddb-delta", type=float, default=10.0,
                    help="counter climb since last tick that alerts")
    ap.add_argument("--repeat-h", type=float, default=6.0,
                    help="inbox dedup window per condition")
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--board-api", default=os.environ.get(
        "BOARD_API", BOARD_API))
    args = ap.parse_args()
    STATE = Path(args.state)
    BOARD_API = args.board_api.rstrip("/")

    checks = {c.strip() for c in args.checks.split(",") if c.strip()}
    st = load_state()
    names = podman_names() if checks & {"cpu", "logs"} else []
    problems = []
    if "cpu" in checks:
        problems += check_cpu(st, args)
    if "logs" in checks:
        problems += check_logs(st, args, names)
    if "mddb" in checks:
        problems += check_mddb(st, args)

    rc = 0
    alerts = st.setdefault("alerts", {})
    for cond, text in problems:
        rc = 1
        if args.no_alert:
            print(f"ALERT {cond}: {text}")
            continue
        if recently_alerted(st, cond, args.repeat_h):
            print(f"alert muted (deduped): {cond}")
            continue
        if file_inbox(text):
            alerts[cond] = iso(now_utc())
            print(f"alert filed: {cond}")
        else:
            print(f"alert FAILED to file: {cond}", file=sys.stderr)
    active = {c for c, _ in problems}
    for cond in list(alerts):
        if cond not in active:
            print(f"recovered (silent): {cond}")
            del alerts[cond]

    if not problems:
        print(f"ok — checks={','.join(sorted(checks))} "
              f"containers={len(names)}")
    save_state(st)
    return rc


if __name__ == "__main__":
    sys.exit(main())
