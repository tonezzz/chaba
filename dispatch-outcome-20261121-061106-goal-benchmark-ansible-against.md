# Dispatch outcome — ansible-vs-legacy-fleet-benchmark (2026-11-21)

## What was done

Benchmarked Ansible against the existing fleet tooling on 4 read-only
jobs, all run from tony-macbook (ansible-core 2.22.0; `ANSIBLE_HOST_KEY_CHECKING=False`
env-only workaround — this host's known_hosts lacks Tailscale-IP keys for
mn01/con01/itself; kk-mac offline, excluded from timings).

New playbooks committed on the session branch
(`dispatch/20261121-061106-goal-benchmark-ansible-against`, commit 970a4175b5):

- `ansible/playbooks/audit-fleet-services.yml` + `templates/service-audit-deltas.j2`
  — strict Ansible port of `scripts/audit-hosts.py`'s
  `diff_against_ssot()` (same delta strings, same noise regexes, same
  rules incl. scopes/globs/known_failed/min_free_ram/OOM tolerance).
- `ansible/playbooks/disk-headroom.yml` + `templates/disk-headroom.j2`
  — instantaneous fleet disk guard: flat-90 crit + per-host
  `max_root_disk_percent` (85/90 from SSOT) + 15 GiB mddb floor.
- `ansible/playbooks/verify-ada-stagger.yml` + `templates/ada-stagger-verify.j2`
  — 11-check verification vs `stacks/idc03/ada-start-stagger/stack.yml`.
- `ansible/playbooks/audit-runner-tools.yml` — appended an opt-in
  `sync_mode` copy play for `--check --diff` dry-run previews.

## Results (report: docs/reports/ansible-vs-legacy-benchmark-2026-11-21.md)

| Candidate | Legacy | Ansible | Parity | Verdict |
|-----------|--------|---------|--------|---------|
| Service audit (`--all`) | 66.3s | 30.9s | identical deltas modulo live flap | **ansible** (~2×, scales) |
| Disk headroom | 24.5s | 27.8s | same 2 crits | **tie** — ansible for the instantaneous SSOT-threshold guard, legacy for trend→card→push |
| Stagger verify | 0.63s | 11.0s | same verdict | **tie** — ssh for ad-hoc, ansible for encoded periodic check |
| Runner-tools enforce | no dry-run exists | `--check --diff` 58.8s | preview-only | **split** — ansible owns preview, legacy owns guarded convergence |

## Real findings (not benchmark artifacts)

- **idc03 `/` at 98% (8.1 GiB free)**, **tony-dell `/` at 99% (3.7 GiB
  free)** — verified by direct `df`; both under the 15 GiB mddb-guard
  floor and over the ssot 85% thresholds. disk-trend-watch's own sandbox
  run confirmed it will open `disk-auto-idc03-root` /
  `disk-auto-tony-dell-root` on its next production tick, so the alert
  path covers it.
- idc03 ada-start-stagger hook installed mode `0775` vs install.sh's
  `0755` (content identical) — minor perms drift.
- `ssot.audit.hosts.yml:432` duplicate `action:` key (YAML keeps last).
- `max_root_disk_percent` is declared per-host in the audit SSOT but
  `audit-hosts.py` never enforces it — the new disk playbook closes that.

## How to verify

```
cd ansible
ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook playbooks/audit-fleet-services.yml
ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook playbooks/disk-headroom.yml
ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook playbooks/verify-ada-stagger.yml
diff <(python3 -c 'import yaml;print(*yaml.safe_load(open("reports/ansible-benchmark/services/idc03.yml"))["deltas"],sep="\n")'|sort) \
     <(python3 -c 'import yaml,glob;f=sorted(glob.glob("reports/audit-hosts/idc03-*.yml"))[-1];print(*yaml.safe_load(open(f))["deltas"],sep="\n")'|sort)
```

lessons:
- ansible regex_search returns the whole match, not capture groups — use regex_replace backrefs to extract.
- inside .j2 templates '\1' is an octal escape (\x01), not a backreference — write '\\1' (silently corrupted a regex for a full run).
- folded '>-' YAML scalars inject spaces into multi-line regexes — keep long regex vars on one line.
- lookup('file')|hash('sha256') != sha256sum (content normalization) — use stat module checksum for byte-exact compares.
- ~15-20s of each ansible run was controller-side include_vars+Jinja on the 2.5k-line SSOT, not ssh — template rendering is the bottleneck, not fan-out.
