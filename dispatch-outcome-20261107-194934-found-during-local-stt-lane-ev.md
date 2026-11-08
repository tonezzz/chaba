# dispatch-outcome — idc02-ambient-cpu-stt-latency (zombie-claim re-run)

**Result: nothing new to do — prior session's work verified live, residual
decision carded.** This session was a zombie-claim restart: the 190904
session had already run the full quiet-vs-busy RTF matrix, applied
`CPUWeight=1000` on idc02/con01/idc03, merged the report
(`docs/ssot/jobs/voice/2026-11-07-stt-cpu-contention-matrix.yml`,
merge 94206109), and finished the card to `review` at 19:49. The
dispatcher had committed this second claim before the finish landed.

## Re-verification (2026-11-07 ~19:50)

- `CPUWeight=1000` persisted on all three hosts (user.control drop-ins):
  idc02 `ada-stt` active 2wk+, idc03 active (load ~4.5/4), con01 active
  (load ~10/8 vCPU).
- Live RTF re-measurement, 4 voice-bench fixture clips (1.8–2.8s):
  - **con01 (prod, :8914)**: RTF 1.7–3.0 under load ~10/8 — consistent
    with the post-weight range; all clips transcribed correctly.
  - **idc02 (standby, :8914)**: RTF 0.50–0.82 warm (one 5.95 cold hit);
    host currently quiet (load ~0.8).
- Health 200 on both `http://100.72.146.39:8914/health` (prod) and
  `http://100.123.163.11:8914/health` (standby). Note: idc02's
  audiocpp_server binds the tailscale IP, not 127.0.0.1 — localhost
  curl returns refused even when healthy.

## Board actions

- Posted verification comment (above numbers) on the card.
- Raised request `nice10-escalation`: accept current batch-lane RTF
  (★ suggested) vs escalate to system-unit `Nice=-10` (validated
  RTF 0.69–1.39 under total saturation; needs sudo, also covers
  journalctl/system.slice bursts that cgroup weight can't reach).
- No `/action finish` — card already `review`/`done`/`verified:true`;
  a second finish call would error (`not running`).

## Repo changes

None — this session made no file changes beyond this outcome file.
All artifacts were merged by the prior session (commit 8107c010d).

## How to verify

1. `ssh con01 'systemctl --user show ada-stt -p CPUWeight'` → 1000
   (same on idc02, idc03)
2. `curl -s http://100.72.146.39:8914/health` → 200
3. Full re-run rig: `ssh idc02 'cd ~/stt-contention-test && ./run-matrix.sh'`
