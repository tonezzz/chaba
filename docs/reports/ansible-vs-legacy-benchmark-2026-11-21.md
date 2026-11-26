# Ansible vs legacy fleet tooling — benchmark (2026-11-21)

Card: `ansible-vs-legacy-fleet-benchmark`. Read-only: every run was an
audit/`--check`; nothing was applied, restarted, or written on any host.

- **Controller:** tony-macbook, ansible-core 2.22.0 (`~/.local/bin`).
  tony-dell's uv env (2.21.6) not needed — this host has the ssh mesh.
- **Reachability:** all 7 Linux hosts reachable. Inventory uses Tailscale
  IPs, but tony-macbook's `known_hosts` only carries *hostname* keys for
  mn01/con01/itself — runs used `ANSIBLE_HOST_KEY_CHECKING=False` (env
  only, no file changes). On tony-dell the IP keys likely already exist.
- **kk-mac:** offline (ssh timeout) — excluded from all timing claims;
  the audit-runner-tools run correctly marked it UNREACHABLE and moved on.

New artifacts: `ansible/playbooks/audit-fleet-services.yml`,
`disk-headroom.yml`, `verify-ada-stagger.yml`, a `sync_mode` play appended
to `audit-runner-tools.yml`, and `ansible/playbooks/templates/{service-audit-deltas,disk-headroom,ada-stagger-verify}.j2`.
Per-host evidence: `reports/ansible-benchmark/{services,disk,stagger}/`.

## Results

| # | Job (ansible vs legacy) | Legacy wall | Ansible wall | Findings parity | Verdict |
|---|-------------------------|-------------|--------------|-----------------|---------|
| 1 | Service audit — `audit-fleet-services.yml` vs `audit-hosts.py --all` | **66.3s** (7 hosts, sequential ~9s/host) | **30.9s** (1 parallel probe + controller diff) | Yes — identical delta sets modulo live-state flap between runs | **Ansible** — ~2× faster at 7 hosts, scales better; same deltas |
| 2 | Disk headroom — `disk-headroom.yml` vs `disk-trend-watch.py` (sandboxed) | **24.5s** | **27.8s** (~15–20s is controller-side SSOT parse/Jinja, not ssh) | Yes — same 2 crits (idc03 `/`, tony-dell `/`) | **Tie** — split by use-case (below) |
| 3 | ada-start-stagger verify — `verify-ada-stagger.yml` vs manual ssh | **0.63s** (one ssh one-liner) | **11.0s** | Yes — same verdict, 11 declarative checks | **Tie** — ad-hoc: legacy; periodic encoded check: ansible |
| 4 | Runner-tool convergence — `audit-runner-tools.yml -e sync_mode=true --check --diff` vs `sync-runner-tools.sh` | n/a — **no dry-run exists** | audit 13.2s; `--check --diff` 58.8s | Preview-only capability | **Split** — ansible is the only safe preview; legacy owns convergence semantics |

## Per-candidate detail

### 1. Host service audit — **ansible**

`audit-fleet-services.yml` probes each host once (JSON blob: systemd
user+system lists, failed units, free/df, OOM greps, uptime), then renders
the *same delta strings* `audit-hosts.py` produces from the same
`ssot.audit.hosts.yml` — a strict port of `diff_against_ssot()` including
`expected_services`, `expected_absent`, `allowed_running` globs,
`known_failed`, `min_free_ram_mb`, `oom_kills_tolerance`, and all four
noise regexes verbatim.

- Wall: legacy 66.3s vs ansible 30.9s. Legacy runs hosts strictly
  sequentially (9 ssh commands each); ansible fans out 10 forks. The gap
  widens with fleet size — at 15+ hosts ansible wins bigger.
- Parity: delta sets matched on all 7 hosts; residual diffs were live
  flap (log-shipper/device-telemetry failed between runs ~60s apart;
  `yomi-process` entered failed mid-benchmark; `snapd.session-agent`
  started later — a same-window recheck agreed).
- Legacy keeps its edge where the audit *feeds the ecosystem*: meta.yml +
  timeline + `audit-auto-*` kanban cards (`--cards`) + the report-graph
  FLEET-REPORT rollup. The ansible port emits per-host YAML and stdout;
  it does not write meta/cards (would need board-api calls to match).
- Also surfaced: `ssot.audit.hosts.yml:432` has a **duplicate `action`
  key** — YAML keeps the last; worth a cleanup (not touched, SSOT is
  out of dispatch scope).

### 2. Disk headroom guard — **tie (split by use-case)**

- Findings identical: **idc03 `/` 98% (8.1 GiB free), tony-dell `/` 99%
  (3.7 GiB free)** — both under the 15 GiB mddb-guard floor and over the
  flat-90 crit. Real, verified by direct `df`. Production disk-trend will
  open `disk-auto-idc03-root` / `disk-auto-tony-dell-root` itself on its
  next tick (it did in the sandboxed run), so the alert pipeline covers it.
- Instantaneous check: ansible enforces *more* of the declared contract —
  per-host `max_root_disk_percent` (85 on dell/omen/mn01, 90 macbook)
  plus the absolute 15 GiB floor — while `audit-hosts.py` declares those
  thresholds in the SSOT **but never enforces them** (coverage gap), and
  disk-trend only applies the flat 90 + slope.
- Legacy keeps the trend story: jsonl history → least-squares slope →
  "fills in ≤7d" → card + push, plus top-grower `du` watchlists. Ansible
  runs are stateless — trend math has no home there. Cost of that state:
  the legacy probe is heavier per host (du watchlists, 45s/dir cap).
- Verdict: **ansible** for a declarative instantaneous fleet guard
  (single artifact, per-host SSOT thresholds);
  **legacy** for the alerting lifecycle (trend, cards, push). They're
  complementary, not rivals — ansible could plausibly *feed* the same
  card pipeline.

### 3. ada-start-stagger checksum — **tie**

- Ansible: 11s, rendered `reports/ansible-benchmark/stagger/idc03.yml` —
  11 checks: hook sha256 vs `stat` checksum, mode, 8 drop-ins vs
  `stack.yml` offsets, live `ExecStartPre`. Verdict: **10/11 pass; one
  real drift — installed mode `0775` vs install.sh's `0755`** (content
  identical; minor, group-writable).
- Manual ssh equivalent: 0.63s, same verdict, no artifact, nothing
  encoded — the "checklist" lives in the operator's head.
- Verdict: for a one-shot question legacy ssh wins on speed. For the
  *periodic contract verification* this stack actually needs (declared
  in `stack.yml`), ansible's encoded 11-check verdict + durable artifact
  is the better tool at a cost that's irrelevant at cron cadence.

### 4. Runner-tool convergence enforcement — **split**

- `sync-runner-tools.sh` has **no dry-run** — the only preview is the
  read-only audit playbook itself. `ansible-playbook ... --check --diff
  -e sync_mode=true` shows per-host, per-tool would-be diffs (e.g. con01
  would gain missing `dispatch-queue` + `devin-dispatch-prune`). No
  equivalent exists in legacy → **ansible wins on safe preview**.
- But the copy module lacks the shell script's guards: manifest pins,
  never-downgrade mtime check, dirty-checkout skip, and — critically —
  the provisioning-evidence rule (never install runner tools on a host
  that isn't a runner). `--check` showed it *would* install missing
  tools everywhere, which the legacy script deliberately doesn't. It
  also converges onto the **controller's** copy vs legacy's per-host
  `~/CascadeProjects/chaba` checkout — a different (arguably better)
  convergence model, but a semantic change. → **legacy wins on
  convergence semantics**; ansible `--check` is the missing preview
  front-end it could use.
- kk-mac unreachable handled correctly (marked, skipped, run continued).

## Aggregate

| Metric | Ansible | Legacy |
|--------|---------|--------|
| Fleet-parallel fan-out | strong (forks, one round-trip/host) | weak (sequential ssh loops) — except disk-trend (ThreadPool=6) |
| Dry-run / preview | `--check --diff` built-in | audit yes, enforce **no** |
| Declarative contract | inventory + SSOT vars + templates | SSOT read by bespoke python |
| State/trend/alerting | none (stateless runs) | strong (jsonl history, card lifecycle, push, report-graph) |
| Per-host artifacts | yes (rendered YAML) | yes (report + meta + timeline) |
| Guard logic on writes | thin (copy module) | strong (pins, never-downgrade, provisioning evidence) |
| Jinja/template footguns | real (see gotchas) | n/a |

## Gotchas hit (worth a line each)

- ansible `regex_search` returns the **whole match**, not capture groups —
  extract with `regex_replace` backrefs.
- Inside `.j2` templates `'\1'` is an **octal escape** (`\x01`), not a
  backreference — write `'\\1'`. Silently corrupted a regex for a full run.
- A folded `>-` YAML scalar **injects spaces** into alternation regexes —
  keep long regexes on one line.
- `lookup('file') | hash('sha256')` ≠ `sha256sum` (lookup normalizes
  content) — use the `stat` module's `checksum` for byte-exact compares.
- `loop_control: loop_var:` removes `item`; template search path is
  `playbooks/templates/`, not `ansible/templates/`.
- ~15–20s of each run is controller-side SSOT `include_vars` + Jinja —
  not ssh. Caching/parsing the 2.5k-line SSOT per template render is the
  main ansible-side cost; would amortize if the diff became a real module.

## Take

Ansible wins where the job is **parallel read-only fan-out** (service
audit: ~2× faster, full parity, better scaling) and is the *only* tool
with a real change preview (`--check --diff`). Legacy wins where the job
needs **state or guarded convergence** (disk trend slope → cards → push;
runner-tool pins/never-downgrade). Keep audit-hosts.py for the
card/meta/report-graph pipeline; `audit-fleet-services.yml` is the
faster engine for "what's drifting right now" and the natural front-end
for a future `audit-auto` card emitter via board-api.

Real findings worth their own attention: idc03 `/` 98%, tony-dell `/`
99% (disk-trend will card both on its next tick), idc03 stagger hook
mode 0775 vs declared 0755, `ssot.audit.hosts.yml` duplicate `action`
key at :432, and `max_root_disk_percent` is declared per-host but no
tool enforced it before this playbook.
