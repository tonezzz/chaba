#!/usr/bin/env python3
"""queue-mgr — mirror the ada-nest Drive queue into WP nest_job via board-api.

OPS-0759 (nest-pack v3 leg 2): watchers watch, one door writes. This
one-shot poller reads gdrive:ada-nest queue/packs state over rclone
(tony-dell holds the remote) and upserts one nest_job post per unit of
work through board-api ``POST /job`` — agents and Colab workers never
hold WP creds; this daemon is the only writer of the member surface.

Entities mirrored (all children of the root job ``ada-nest-queue``):

  ada-nest-queue   kind=queue — the whole offload queue; status DERIVED
                   from children (running > stalled > queued > done/failed)
  job-<name>       kind=sub   — JOBS.py manifest entries (env + work scope)
  <pack-name>      kind=pack  — packs/<name>/ dirs on the store

Status mapping (store truth -> JOB_STATUSES):

  pack   done marker      -> done     (result_ref = done marker path)
         failed marker    -> failed   (error = marker text)
         heartbeat names  -> running  (fresh heartbeat, phase run/prep)
         claim/ non-empty -> claimed  (runner = first claim file)
         otherwise        -> queued
  job    done marker      -> done     (work: queue/done/<n>.done;
                                      env:  newest env-done/<boot>/<n>.done)
         heartbeat names  -> running
         otherwise        -> queued

Delta-only writes: a per-slug fingerprint of the mirrored fields decides
what to POST — unchanged entities cost zero WP writes. ``comms`` lines
are appended only on transitions (staged / claimed / running / done /
failed / released). A failed POST leaves the fingerprint un-advanced so
the next tick retries; the root post goes first because children resolve
``parent`` by slug at write time.

Env jobs are per-boot bootstrap (cache restore, warmup): their "done" is
scoped to the freshest env-done/<boot_id>/ — the boot named by a fresh
queue/runner.id when present, else the env-done dir with the newest
modtime. A new Colab boot legitimately flips them queued->running->done.

Kill switch: ``touch ~/.config/queue-mgr.off`` or ``QUEUE_MGR=off`` —
every tick exits silently. ``--dry-run`` prints the derived plan without
writing state or calling board-api.

Env:
  QUEUE_MGR             off disables
  QUEUE_MGR_OFF_FILE    kill-switch path (default ~/.config/queue-mgr.off)
  QUEUE_MGR_STATE       state file (default ~/.local/state/queue-mgr.json)
  QUEUE_MGR_REMOTE      rclone root (default gdrive:ada-nest)
  QUEUE_MGR_API         board-api base (default tailnet :10000)
  QUEUE_MGR_HB_FRESH_S  heartbeat freshness for 'running' (default 120)
  QUEUE_MGR_RUNNER_FRESH_S  runner.id/lease freshness (default 900)
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
OFF_FILE = Path(os.environ.get(
    "QUEUE_MGR_OFF_FILE", HOME / ".config/queue-mgr.off"))
STATE = Path(os.environ.get(
    "QUEUE_MGR_STATE", HOME / ".local/state/queue-mgr.json"))
REMOTE = os.environ.get("QUEUE_MGR_REMOTE", "gdrive:ada-nest").rstrip("/")
Q = f"{REMOTE}/queue"
PACKS = f"{REMOTE}/packs"
API = os.environ.get(
    "QUEUE_MGR_API",
    os.environ.get("BOARD_API")
    or "https://idc03.taila0626a.ts.net:10000").rstrip("/")
HB_FRESH_S = int(os.environ.get("QUEUE_MGR_HB_FRESH_S", "120"))
RUNNER_FRESH_S = int(os.environ.get("QUEUE_MGR_RUNNER_FRESH_S", "900"))

ROOT_SLUG = "ada-nest-queue"
ROOT_TITLE = "ada-nest offload queue"
FROM = "queue-mgr"

RCLONE = shutil.which("rclone") or os.path.expanduser("~/.local/bin/rclone")

JOB_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,60}")


def say(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} queue-mgr: {msg}", flush=True)


# ---------------------------------------------------------------- rclone --

def rclone(*args: str, timeout: int = 120) -> str:
    """rclone passthrough; raises on failure, returns stdout."""
    r = subprocess.run([RCLONE] + list(args), capture_output=True,
                       text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(
            f"rclone {args[0]}: {r.stderr.strip()[:300]}")
    return r.stdout


def rclone_ok(*args: str, timeout: int = 60) -> str:
    """rclone passthrough tolerant of absent paths — '' on failure."""
    r = subprocess.run([RCLONE] + list(args), capture_output=True,
                       text=True, timeout=timeout)
    return r.stdout if r.returncode == 0 else ""


def lsf(path: str, recursive: bool = False,
        fmt: str | None = None) -> list[str]:
    args = ["lsf", path]
    if recursive:
        args.append("--recursive")
    if fmt:
        args += ["--format", fmt]
    out = rclone_ok(*args)
    return [l.rstrip("\n") for l in out.splitlines() if l.strip()]


def cat(path: str) -> str:
    return rclone_ok("cat", path).strip()


# ----------------------------------------------------------------- scan --

def pack_inventory() -> dict:
    """{pack: {relpath: mtime|None}} — one recursive listing, same shape
    nest-worker.plan_pass uses (dirs end with '/', ';ts' suffix optional)."""
    inv = {}
    for line in lsf(PACKS, recursive=True, fmt="pt"):
        path, _, ts = line.rpartition(";")
        parts = path.rstrip("\n").split("/", 1)
        if len(parts) == 1:
            if parts[0]:
                inv.setdefault(parts[0].rstrip("/"), {})
            continue
        mtime = None
        try:
            mtime = datetime.datetime.strptime(
                ts.strip().split(".")[0], "%Y-%m-%d %H:%M:%S").timestamp()
        except (ValueError, IndexError):
            pass
        inv.setdefault(parts[0], {})[parts[1]] = mtime
    return inv


def fetch_pack_meta(inventory: dict) -> dict:
    """Batched pack.yml fetch -> {pack: parsed dict}. One rclone copy
    with --files-from; per-pack cat fallback for stragglers."""
    want = sorted(f"{d}/pack.yml" for d, e in inventory.items()
                  if "pack.yml" in e)
    texts = {}
    if want:
        tmp = tempfile.mkdtemp(prefix="queue-mgr-")
        try:
            lst = os.path.join(tmp, "files.txt")
            with open(lst, "w") as f:
                f.write("\n".join(want) + "\n")
            r = subprocess.run(
                [RCLONE, "copy", PACKS, tmp, "--files-from", lst],
                capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                for rel in want:
                    fp = os.path.join(tmp, rel)
                    if os.path.isfile(fp):
                        texts[rel.split("/", 1)[0]] = open(fp).read()
            else:
                say(f"pack.yml batch fetch failed: "
                    f"{r.stderr.strip()[:200]} — per-pack fallback")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    out = {}
    for d, e in inventory.items():
        if "pack.yml" not in e:
            continue
        text = texts.get(d)
        if text is None:
            text = cat(f"{PACKS}/{d}/pack.yml")
        spec = _load_yml(text) or {}
        if isinstance(spec, dict):
            out[d] = spec
    return out


def _load_yml(text: str):
    if not text:
        return None
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        pass
    except Exception:
        return None
    # pyyaml-less fallback: name/title scalars only — enough for titles
    out = {}
    for line in text.splitlines():
        m = re.match(r"^(name|title):\s*['\"]?([^'\"#]+)", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out or None


def parse_manifest(text: str) -> list[dict]:
    """queue/JOBS.py -> [{name, scope}]. exec our own manifest file;
    regex fallback keeps a syntax drift from blinding the mirror."""
    jobs = []
    if text:
        try:
            ns = {}
            exec(compile(text, "<JOBS.py>", "exec"), ns)
            for j in ns.get("JOBS") or []:
                if isinstance(j, dict) and isinstance(j.get("name"), str):
                    jobs.append({"name": j["name"],
                                 "scope": j.get("scope") or "work"})
            if jobs:
                return jobs
        except Exception as e:
            say(f"JOBS.py exec failed ({e}) — regex fallback")
    for m in re.finditer(
            r"""['"]name['"]\s*:\s*['"]([a-z0-9-]+)['"]"""
            r"""[^}]*?['"]scope['"]\s*:\s*['"](\w+)['"]""", text):
        jobs.append({"name": m.group(1), "scope": m.group(2)})
    if not jobs:  # scope may precede name in the dict literal
        for m in re.finditer(
                r"""['"]scope['"]\s*:\s*['"](\w+)['"]"""
                r"""[^}]*?['"]name['"]\s*:\s*['"]([a-z0-9-]+)['"]""", text):
            jobs.append({"name": m.group(2), "scope": m.group(1)})
    # dedupe preserving order
    seen, out = set(), []
    for j in jobs:
        if j["name"] not in seen:
            seen.add(j["name"])
            out.append(j)
    return out


def parse_heartbeat(text: str) -> dict:
    parts = text.split()
    hb = {"epoch": 0.0, "job": "", "phase": "", "age_s": None}
    if len(parts) >= 3:
        try:
            hb["epoch"] = float(parts[0])
        except ValueError:
            pass
        hb["job"], hb["phase"] = parts[1], parts[2]
    if hb["epoch"]:
        hb["age_s"] = time.time() - hb["epoch"]
    return hb


def scan() -> dict:
    """One pass over the store -> plain dict the deriver consumes."""
    inv = pack_inventory()
    meta = fetch_pack_meta(inv)
    jobs = parse_manifest(cat(f"{Q}/JOBS.py"))

    done_work = set()
    for line in lsf(f"{Q}/done"):
        if line.endswith(".done"):
            done_work.add(line[:-5])

    # env-done boots with modtimes -> freshest session's marker set
    env_boots = {}   # boot_id -> mtime
    for line in lsf(f"{Q}/env-done", fmt="pt"):
        name, _, ts = line.rpartition(";")
        name = name.strip().rstrip("/")
        if not name:
            continue
        try:
            env_boots[name] = datetime.datetime.strptime(
                ts.strip().split(".")[0], "%Y-%m-%d %H:%M:%S").timestamp()
        except (ValueError, IndexError):
            env_boots.setdefault(name, 0.0)
    runner = {}
    raw = cat(f"{Q}/runner.id")
    if raw:
        try:
            runner = json.loads(raw)
        except Exception:
            runner = {}
    runner_fresh = bool(runner) and (
        time.time() - float(runner.get("ts") or 0)) < RUNNER_FRESH_S
    env_boot = ""
    if runner_fresh and runner.get("boot_id") in env_boots:
        env_boot = runner["boot_id"]          # the live session's boot
    elif env_boots:
        env_boot = max(env_boots, key=env_boots.get)   # last session
    env_done = set()
    if env_boot:
        for line in lsf(f"{Q}/env-done/{env_boot}"):
            if line.endswith(".done"):
                env_done.add(line[:-5])

    lease = {}
    raw = cat(f"{Q}/lease")
    if raw:
        try:
            lease = json.loads(raw)
        except Exception:
            lease = {}

    packs = {}
    for d, entries in sorted(inv.items()):
        is_pack = ("pack.yml" in entries or "done" in entries
                   or "failed" in entries
                   or any(k.startswith("claim/") for k in entries))
        if not is_pack or not JOB_NAME_RE.fullmatch(d):
            continue
        claims = sorted({k[len("claim/"):] for k in entries
                         if k.startswith("claim/")
                         and k[len("claim/"):].strip()})
        packs[d] = {
            # done-marker CONTENT is never read downstream — existence in
            # the inventory is the signal; cat-ing ~60 markers per tick
            # was the scan's whole runtime. failed markers stay cat'ed
            # (rare) because their text becomes the post's error field.
            "done": "1" if "done" in entries else "",
            "failed": (cat(f"{PACKS}/{d}/failed")
                       if "failed" in entries else ""),
            "claims": claims,
            "spec": meta.get(d) or {},
        }

    return {
        "packs": packs,
        "jobs": jobs,
        "done_work": done_work,
        "env_done": env_done,
        "env_boot": env_boot,
        "heartbeat": parse_heartbeat(cat(f"{Q}/heartbeat")),
        "runner": runner if runner_fresh else {},
        "lease": lease,
    }


# --------------------------------------------------------------- derive --

def _slug_for_job(name: str) -> str:
    return f"job-{name}"


def _host_from_worker(worker: str) -> str:
    """claim/<worker> names are '<host>-<pid>' (nest-worker) or
    'colab-<boot8>-<pid>' (queue-runner) — strip the pid for the Host
    column; the full id stays in runner."""
    m = re.match(r"^(.*)-\d+$", worker or "")
    return m.group(1) if m else (worker or "")


def derive(sc: dict) -> dict:
    """Store snapshot -> {slug: post}. Root first in dict order."""
    hb = sc["heartbeat"]
    hb_live = (hb["age_s"] is not None and hb["age_s"] <= HB_FRESH_S
               and hb["job"] not in ("", "boot", "exit"))
    hb_name = hb["job"] if hb_live else ""

    lease_worker = ""
    lease = sc.get("lease") or {}
    try:
        if lease and time.time() - int(lease.get("ts") or 0) \
                < RUNNER_FRESH_S:
            lease_worker = str(lease.get("worker") or "")
    except (TypeError, ValueError):
        pass
    if not lease_worker and sc.get("runner"):
        lease_worker = str(sc["runner"].get("worker") or "")

    posts = {}
    children = {}

    for d, p in sc["packs"].items():
        slug = d
        spec = p["spec"] or {}
        title = str(spec.get("title") or spec.get("name") or d)
        claims = p["claims"]
        runner = claims[0] if claims else ""
        host = _host_from_worker(runner)
        status, result_ref, error = "queued", "", ""
        if p["done"]:
            status = "done"
            result_ref = f"gdrive:ada-nest/packs/{d}/done"
        elif p["failed"]:
            status = "failed"
            error = p["failed"][:300]
        elif d == hb_name:
            status = "running"
        elif claims:
            status = "claimed"
        post = {
            "slug": slug, "title": title, "status": status,
            "kind": "pack", "host": host, "pack": d,
            "parent": ROOT_SLUG,
            "runner": runner, "result_ref": result_ref, "error": error,
        }
        if status == "done" and result_ref:
            # OPS-0923 terminal-done gate: the done marker IS the
            # verified artifact evidence — point at it explicitly
            post["evidence"] = [result_ref]
        posts[slug] = post
        children[slug] = status

    for j in sc["jobs"]:
        name, scope = j["name"], j.get("scope") or "work"
        slug = _slug_for_job(name)
        status, result_ref = "queued", ""
        if scope == "env":
            if name in sc["env_done"]:
                status = "done"
                result_ref = (f"gdrive:ada-nest/queue/env-done/"
                              f"{sc['env_boot']}/{name}.done")
        elif name in sc["done_work"]:
            status = "done"
            result_ref = f"gdrive:ada-nest/queue/done/{name}.done"
        if name == hb_name and status != "done":
            status = "running"
        post = {
            "slug": slug, "title": name, "status": status,
            "kind": "sub", "host": "",
            "pack": "", "parent": ROOT_SLUG,
            "runner": lease_worker if status == "running" else "",
            "result_ref": result_ref, "error": "",
        }
        if status == "done" and result_ref:
            post["evidence"] = [result_ref]
        posts[slug] = post
        children[slug] = status

    # --- root: derived status -----------------------------------------
    # 'stalled' is deliberately unused: Colab runtimes recycle mid-job as
    # a matter of course, so a stale-mid-run heartbeat is the NORMAL
    # between-sessions state, not an incident — real stall detection
    # lives in nest-queue-status.py / nest-queue-health.py. Live-ness
    # comes from the heartbeat alone: runner.id's ts is boot-time (never
    # refreshed) so it can't prove a long session is still alive.
    sts = list(children.values())
    live = hb_live
    pending = any(s == "queued" for s in sts)
    active = any(s in ("claimed", "running") for s in sts)
    if active or (live and (pending or any(s == "done" for s in sts))):
        root_status = "running"
    elif pending:
        root_status = "queued"
    elif sts and all(s == "done" for s in sts):
        root_status = "done"
    elif any(s == "failed" for s in sts) and not any(
            s == "done" for s in sts):
        root_status = "failed"
    else:
        root_status = "done" if sts else "queued"

    root_post = {
        "slug": ROOT_SLUG, "title": ROOT_TITLE, "status": root_status,
        "kind": "queue", "pack": "", "parent": "",
        "runner": lease_worker,
        "result_ref": "gdrive:ada-nest/queue/",
        "error": "",
        # queue depth rides in comms on transitions — the door only
        # persists JOB_META_KEYS, arbitrary meta keys are dropped
        "_counts": {"children": len(children),
                    "active": sum(1 for s in sts
                                  if s in ("claimed", "running")),
                    "pending": sum(1 for s in sts if s == "queued")},
    }
    if root_status == "done":
        # OPS-0923 gate: root done is derived — its evidence is the
        # children's done markers (capped; the queue dir is the
        # fallback pointer)
        done_refs = [p["result_ref"] for p in posts.values()
                     if p.get("status") == "done" and p.get("result_ref")]
        root_post["evidence"] = done_refs[:10] or [
            "gdrive:ada-nest/queue/"]
    posts = {ROOT_SLUG: root_post, **posts}
    return posts


# ---------------------------------------------------------------- posts --

def fingerprint(post: dict) -> str:
    keys = ("title", "status", "kind", "host", "pack", "runner",
            "result_ref", "error", "parent")
    body = {k: post.get(k) or "" for k in keys}
    meta = post.get("meta") or {}
    if meta:
        body["meta"] = meta
    return hashlib.sha1(
        json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def transition_comms(old: dict | None, post: dict) -> str:
    """One comms line per mirrored transition — the CPT's append log is
    the job's story (queue-mgr transitions + agent decisions later)."""
    new = post["status"]
    detail = ""
    if new == "claimed":
        detail = f"claimed by {post.get('runner') or '?'}"
    elif new == "running":
        detail = "running"
    elif new == "done":
        detail = f"done — {post.get('result_ref') or 'marker written'}"
    elif new == "failed":
        detail = f"failed — {post.get('error') or 'see store'}"
    elif new == "queued" and old and old.get("status") in (
            "claimed", "running", "failed"):
        detail = f"released back to queue (was {old['status']})"
    elif post["slug"] == ROOT_SLUG:
        m = post.get("_counts") or {}
        detail = (f"children={m.get('children','?')} "
                  f"active={m.get('active','?')} "
                  f"pending={m.get('pending','?')}")
    old_status = (old or {}).get("status") or "new"
    head = f"{old_status} -> {new}"
    return f"{head}: {detail or post.get('title') or post['slug']}"[:480]


def api_post(path: str, payload: dict, timeout: int = 30):
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"posts": {}}


def save_state(st: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_name(STATE.name + ".tmp")
        with tmp.open("w") as f:
            f.write(json.dumps(st))
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(STATE)
    except OSError as e:
        say(f"state write failed: {e}")


def post_job(post: dict, comms: str) -> bool:
    body = {k: v for k, v in post.items() if not k.startswith("_")}
    body["title"] = body.get("title") or body["slug"]
    body.update({"comms": comms, "from": FROM})
    try:
        r = api_post("/job", body)
    except Exception as e:
        say(f"{post['slug']}: POST /job failed: {e}")
        return False
    if isinstance(r, dict) and r.get("post_id"):
        say(f"{post['slug']}: {r.get('action')} ({post['status']})")
        return True
    say(f"{post['slug']}: unexpected /job reply: {str(r)[:200]}")
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print derived posts; no writes, no state")
    args = ap.parse_args(argv)

    if os.environ.get("QUEUE_MGR") == "off" or OFF_FILE.exists():
        return 0

    try:
        sc = scan()
    except Exception as e:
        say(f"scan failed: {e}")
        return 1
    posts = derive(sc)

    if args.dry_run:
        for slug, p in posts.items():
            print(json.dumps({k: v for k, v in p.items() if v},
                             ensure_ascii=False))
        return 0

    state = load_state()
    known = state.setdefault("posts", {})

    # order: root first (children resolve parent by slug at write time),
    # then children by slug for a stable comms order
    ordered = sorted(posts.items(),
                     key=lambda kv: (kv[0] != ROOT_SLUG, kv[0]))
    changed = []
    for slug, post in ordered:
        fp = fingerprint(post)
        old = known.get(slug)
        if old and old.get("fp") == fp:
            continue
        comms = transition_comms(old, post)
        if not post_job(post, comms):
            if slug == ROOT_SLUG:
                say("root post failed — skipping children this tick")
                break
            continue                       # fp stays old -> retry next tick
        known[slug] = {"fp": fp, "status": post["status"],
                       "ts": int(time.time())}
        changed.append(f"{slug}:{post['status']}")

    if changed:
        say(f"mirrored {len(changed)} update(s): "
            + ", ".join(changed[:12])
            + (" ..." if len(changed) > 12 else ""))
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
