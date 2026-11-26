# dispatch-outcome — system-report-chain-17h-stale-watchdog-e-ab1511 (attempt 2)

## Result: DONE — all done-conditions verified live

### runner-agent fleet converge (pin 4259ca6f)
Commit `264f9616881` (per-executor claim caps) bumped runner-agent.py +
its manifest pin to sha256 `4259ca6f…b855` at 20:39 +07; the 03:55–04:06
drift defers were the fleet catching up. Verified `sha256sum` of BOTH
`~/.local/bin/runner-agent` and `<checkout>/scripts/board/runner-agent.py`:

| host | action | installed == checkout == pin |
|---|---|---|
| idc02 | scp + restored 2 files to HEAD (see below) | ✅ 4259ca6f |
| idc03 | self-converged (repo-sync + _self_update) | ✅ 4259ca6f |
| tony-macbook | waited for 21:00 repo-sync, then scp | ✅ 4259ca6f |
| tony-dell | self-converged during session | ✅ 4259ca6f |
| mn01 | self-converged via _self_update | ✅ 4259ca6f |
| con01 | self-converged (was on ancient 8c28da6b) | ✅ 4259ca6f |
| tony-omen | self-converged | ✅ 4259ca6f |
| kk-mac | old-but-consistent 1514c75c; heals on next sync | n/a |

idc02 needed extra care: its 20:01 repo-sync autostash-pop conflict left
119 staged files (index = old tree). I restored ONLY
`scripts/board/runner-agent.py` + `scripts/devin/runner-tooling.manifest.json`
to HEAD so the drift/pin checks read canonical bytes; the rest of the
residue is untouched (follow-up carded).

### system-report chain (generator on con01 → delivers idc02)
- Chain never actually stuck — attempt-1 was right; the Nov-10 freeze was
  ancient history. Re-verified live: ran `chaba-system-report.service`
  on con01 manually twice; both runs clean (audit-hosts fleet →
  pull-report-metas → report-system.py → CMS publish → scp to idc02).
- Served `system-report.yml` on idc02: `generated_at
  2026-11-26T21:18:51+07:00` (minutes old vs 26h threshold) — advancing.
- **Red nodes: 17+ → 0.** Fixed the last two:
  - `audit-hosts/kk-mac unreachable` — con01 was missing kk-mac's host
    key (documented prereq in ssot.jobs.yml); ran `ssh-keyscan kk-mac`
    on con01, audit now writes a clean snapshot.
  - `nest-lanes/kk-llm missing` — the declared producer
    `jevnest-kk-llm-metrics` (ssot.jobs.yml, 15m) had generated units in
    `systemd/generated/tony_dell/` but was never installed; copied the
    committed units to `~/.config/systemd/user/`, enabled the timer,
    first run published `reports/kk-llm/meta.kk-llm.yml`.

### How to verify
- `ssh idc02 'python3 -c "import yaml;d=yaml.safe_load(open(\"$HOME/CascadeProjects/chaba/stacks/web/public/apps/system-report/data/system-report.yml\"));print(d[\"generated_at\"],[n[\"id\"] for n in d[\"nodes\"] if n.get(\"status\") in (\"error\",\"missing\",\"unreachable\")])"'` → fresh timestamp, `[]`
- `ssh <host> 'sha256sum ~/.local/bin/runner-agent'` on any runner host → `4259ca6f…`
- `systemctl --user list-timers jevnest-kk-llm-metrics.timer` on tony-dell → active

### Follow-ups carded
- idc02 exec checkout: ~117 staged files of autostash-pop residue keep
  chaba-repo-sync exiting 1 (HEAD still advances; worktree stays stale).

lessons:
- Drift-defer compares `~/.local/bin/runner-agent` BYTES vs the checkout WORKTREE file — scp the new pin before the checkout pulls and you manufacture a fail-closed drift window; converge checkout first, then install.
- `ssh idc03` from tony-dell: the configured `ProxyJump tony-omen` is administratively prohibited — use `ssh -o ProxyJump=none idc03` (direct tailscale works).
- con01 has no ssh-config entry; `ssh tony@con01` (short name) works, the FQDN fails host-key verification.
- Attempt-1 "failed" purely for producing zero commits — merge-sweep needs a landed dispatch branch; always commit the outcome doc.
- ssot.jobs.yml-declared jobs can have committed generated units that were never installed — check `systemctl --user list-unit-files` before assuming a producer runs.
