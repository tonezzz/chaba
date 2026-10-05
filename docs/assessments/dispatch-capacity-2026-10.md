# Dispatch Capacity Benchmark — 2026-10-04

Card: `dispatch-capacity-bench`. Question: how many concurrent `devin -p`
dispatches can each host safely run, and should remote runners use bare
`systemd-run` or a podman-wrapped devin-dispatch image?

All measurements taken live on tony-dell (baseline) and idc02 (podman path)
on 2026-10-04 ~20:45–21:00 +07. Raw monitor logs:
`docs/assessments/dispatch-capacity-2026-10/`.

## 1. tony-dell baseline (bare systemd-run — production path)

Mechanism: `devin-dispatch start` → `git worktree add` →
`systemd-run --user devin-task-<id>` → `devin -p --permission-mode smart`.

| Metric | Trivial task (n=3) | Real task (observed) |
|---|---|---|
| Dispatch call → unit queued | ~6.5 s (worktree add dominates) | same |
| Unit active → first transcript write | ~23 s (CLI + session init + first stream) | same order |
| cgroup MemoryPeak | 549–660 MB | **1.07 GB** (`add-batteries`, npm work) |
| Steady-state RSS during agent work | 360–530 MB | ~980 MB |
| Unit lifetime, trivial | ~60–90 s | task-bound |

Concurrency run: 4 live devin sessions (2 trivial benchmarks + 1 real +
this session) dropped `MemAvailable` to **3.09 GB min** and recovered to
4.8 GB after. No OOM, no thrash beyond the already-heavy swap baseline
(9.6 G used / 16 G).

**Per-task memory for capacity math: ~1.1 GB** (real tasks roughly double
the trivial floor; tool calls like `npm`/`tsc` spawn inside the same
cgroup). `MemoryMax` is `infinity` on all units today — nothing caps a
runaway session; `DISPATCH_UNIT_PROPS=--property=MemoryMax=...` is already
supported by `devin-dispatch.sh` and is the zero-cost fix.

## 2. Remote host state (verified 2026-10-04, corrects card premise)

The card's "devin CLI absent on omen/idc01/mn01/idc02" is **stale**:

| Host | devin CLI | Auth (`credentials.toml`) | dispatch script | Podman | RAM avail | Load | Dispatchable today? |
|---|---|---|---|---|---|---|---|
| tony-omen | `~/.local/bin/devin` 3000.10.31 | present (Sep 15) | yes | 5.7.0 | 6.1 GB | 8.7–10.9 | **yes — bare** (load-limited) |
| mn01 | `~/.local/bin/devin` 3000.10.31 | present (Sep 26) | yes | 5.7.0 | 2.9 GB | 4.7 | **yes — bare** (RAM-limited) |
| idc01 | absent | — | no | 4.9.3 | 28.7 GB | 0.2–0.7 | container path only |
| idc02 | absent | — | no | 4.9.3 | 12.9 GB | ~0.1 | container path only |
| tony-dell | bundled 3000.10.35 | present | yes | — | ~4.5 GB | ~21 | yes (production) |

So bare-systemd dispatch to **tony-omen and mn01 needs zero installs** —
the only blockers are per-host repo checkouts and their current load/RAM.
idc01/idc02 need either CLI+auth install (deferred per card answer:
token provisioning spreads secrets) or the podman image.

## 3. Bare-remote prerequisites (per host, if CLI path is ever used)

- `devin` binary — 184 MB static-pie ELF, scp-able, no deps (verify arch;
  the old mn01 3000.2.17-stale-binary trap is documented in
  `devin-dispatch.sh` — resolution order env → PATH → `~/.local/bin` →
  bundled desktop path).
- `~/.local/share/devin/credentials.toml` (331 B, mode 600) — the only
  auth file. **This is the heavy lift Tony deferred**: provisioning it
  per-host spreads the login token.
- `~/.local/bin/devin-dispatch` + `DISPATCH_DIR` (~/.local/share/devin-dispatch).
- `git` + a **fresh local checkout** per whitelisted repo — worktrees are
  cut from local HEAD; stale checkouts dispatch stale code.
- systemd `--user` manager reachable over ssh (both omen/mn01 report
  `is-system-running=degraded` — units still run).
- `python3` for the meta/mddb job-ledger helpers (best-effort).

## 4. Podman evaluation (idc02, measured)

Containerfile (built on idc02, `~/devin-img/`):

```dockerfile
FROM docker.io/library/debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    git python3 openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY devin /usr/local/bin/devin
CMD ["/bin/bash"]
```

| Metric | Value |
|---|---|
| Image size | **401.6 MB** (78 MB base + ~140 MB toolchain + 184 MB devin) |
| Build time (warm) | ~20 s |
| Container start (`run --rm img devin --version`) | **0.27–0.46 s** |
| `systemd-run --user` on same host | 0.02–0.03 s |
| Rootless `--memory=512m` | works — `memory.max=536870912` inside |
| Rootless `--cpus=0.5` | works — `cpu.max=50000 100000` inside |
| `devin -p` inside container | initializes, stops at `Login canceled` without creds |
| `devin -p` + creds bind-mounted | **works end-to-end** — real session ran, replied `ok`, rc=0 (verified 2026-10-05 with `--memory=1536m --cpus=1.5`) |

Notes:
- cgroup delegation under rootless podman needs **no setup** on
  systemd ≥252 (Ubuntu 24.04's `user@.service` delegates
  `cpu memory pids` by default; confirmed `subtree_control` on idc02).
  Older systemd needs `systemctl edit user@.service Delegate=cpu memory pids io`.
- Gotcha hit during testing: `ENTRYPOINT ["/bin/bash"]` swallows
  `podman run img <cmd>` args (`bash <cmd>` → ENOEXEC). Use `CMD`, not
  `ENTRYPOINT`.
- Overhead vs bare: ~0.25 s per launch — noise next to the ~23–30 s
  session init.
- Auth: **decided 2026-10-05 — copy `credentials.toml` + `config.json`
  to each runner host** (option b), bind-mount into the container.
  Verified recipe on idc02 (`~/dispatch-wt-test` as scratch worktree):
  ```
  podman run --rm --memory=1536m --cpus=1.5 --userns=keep-id \
    -v $HOME/.local/share/devin:$HOME/.local/share/devin \
    -v $HOME/.config/devin:$HOME/.config/devin \
    -v <worktree>:/wt -w /wt -e HOME=$HOME \
    devin-dispatch:test devin -p --permission-mode smart \
      --respect-workspace-trust false -- "<prompt>"
  ```
  `--userns=keep-id` keeps files host-owned; `$HOME` mounts avoid the
  `/root` path mismatch. Needs `--respect-workspace-trust false` (same
  as `devin-dispatch.sh`) or the CLI refuses an untrusted worktree.
- Image distribution: no registry today → `podman save | ssh host podman load`
  (~400 MB) or a tailnet registry. Build-on-host is 20 s once the binary
  is there.
- Repo freshness inside a container: mount a host-side checkout
  (`-v ~/CascadeProjects/chaba:/repo`) and still `git worktree add`
  inside — worktrees land in the host fs via the mount.

## 5. Capacity table — recommended per-host caps

Memory per task ≈ **1.1 GB** peak. CPU: sessions are I/O/API-bound most of
the time but spike hard during tool calls (tsc, npm, pytest) — assume ~1
core per active session for comfort.

| Host | Constraint | Safe concurrent tasks | Evidence |
|---|---|---|---|
| tony-dell | RAM (15.3 G total, ~4.5 G avail, heavy swap + desktop) | **3** (current cap — validated) | 4 live sessions → avail 3.1 GB min |
| idc02 | CPU (4 cores; 12.9 GB avail fits ~10 by RAM) | **4** | idle VPS; RAM headroom large; cores are the binding limit |
| tony-omen | load (12 cores but load already 8–11; 6.1 GB avail) | **2** when load < 6, else 0 | RAM fits ~5; the box is doing real work |
| mn01 | RAM (2.9 GB avail) + load 4.7 | **1** | 1 task ≈ 1.1 GB; leave standby headroom |
| idc01 | prod host (ada + mddb), 2 cores | **0** (avoid; 1 max in emergency) | RAM is huge but it's the memory/memory-stack host — don't add agent load |

Enforcement: caps are advisory in `dispatch-queue.sh` today (counts
`devin-task-*` units). Add `--property=MemoryMax=1536m` (≈1.4× observed
real-task peak) via `DISPATCH_UNIT_PROPS` on every runner — kills a
runaway session instead of the host. In podman: `--memory=1536m --cpus=1.5`
per task container.

## 6. Recommendation

1. **tony-dell stays bare systemd-run + add MemoryMax.** Containerizing
   the local runner buys nothing: 0.25 s launch overhead, plus worktree/
   credential plumbing, for isolation the worktree+cgroup already gives.
   Do add `DISPATCH_UNIT_PROPS=--property=MemoryMax=1536m` — today's
   units are unbounded.
2. **Remote runners: podman image, not per-host CLI installs** — for
   idc01/idc02. One 402 MB artifact carries binary+toolchain, versions
   stay pinned fleet-wide, rootless memory/cpu caps verified working,
   and the auth surface is a single bind-mounted `credentials.toml`
   (vs. installs that litter state across hosts).
3. **But: omen and mn01 are already bare-dispatchable** (CLI 3000.10.31 +
   creds + script installed). For those two, prefer bare — the podman
   layer adds nothing except on hosts that lack the CLI.
4. **First runners: idc02 (podman, cap 4)** — idle VPS, verified end-to-end
   except authenticated inference, which needs Tony's call on mounting
   `credentials.toml`. **Then tony-omen (bare, cap 2)** once its load
   drops — it needs nothing installed.
5. **Skip** mn01 (standby, 2.9 GB) and idc01 (prod ada+mddb, 2 cores)
   except emergencies.

Resolved 2026-10-05: credentials distribution = **copy `credentials.toml`
+ `config.json` to each runner** (Tony, board request answer "b").
idc02 provisioned and verified end-to-end — full recipe in section 4.

Remaining follow-ups before multi-host dispatch ships:
- Repo-checkout freshness on remote runners (per-host pull cron or
  fetch-during-dispatch; worktrees cut from stale HEADs dispatch stale code).
- Task routing: queue is dell-local today (`dispatch-queue.sh` +
  `devin-task-*` unit count). Multi-host needs a per-host cap table +
  ssh-level `devin-dispatch start` fan-out (podman hosts need the
  `podman run` wrapper above instead of `systemd-run`).
- Image versioning/distribution (podman save/load or a small tailnet
  registry; rebuild path when devin CLI revs).
