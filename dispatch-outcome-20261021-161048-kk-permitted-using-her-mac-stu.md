# dispatch-outcome: kk-mac Ada Nest onboarding (ADA-0765)

## What was found

- Prior session (~15:56) state stands: pmset sleep=0/disksleep=0/displaysleep=15,
  Xcode CLT 16.4, Homebrew /opt/homebrew, Ollama 0.40.7 serving :11434 via
  nohup under kkkakk, tmux, llama3.2:3b bench 123 tok/s eval.
- **NEW GAP — SSH auth**: no fleet key authenticates to `kkkakk@kk-mac`.
  Probed every key on tony-omen (incl. all 8 agent identities), tony-dell,
  mn01, idc03, and via tony-macbook — all `Permission denied (publickey)`;
  port 22 answers on .80 (en0) and .92 (en1). Whatever credential the
  earlier session used was never persisted to authorized_keys. tony-dell's
  known_hosts did gain kk-mac host keys at 15:20, so that session did
  connect — auth method unknown (likely password typed during KK's visit).
- KK sign-off request `kk-sign-off-for-kk-mac-ada-nest-install-ae6c5d`
  remains **open** — no answer in answers.jsonl.

## What changed (worktree, commits fa5830491 + 5004ec2b5 on dispatch branch)

- `scripts/ops/kk-mac-onboard.sh` — idempotent executor for kk-mac, bash-3.2-safe.
  Steps: preflight (hw.model interlock), power, user (hidden `adanest`
  service account), keys (fleet key seeding), ollama-daemon
  (`ai.adanest.ollama` LaunchDaemon, ditto-migrates kkkakk's model pulls,
  retires the nohup server), tailscale (cask + printed GUI checklist —
  the extension approval genuinely needs KK's hands), models, verify,
  teardown (CONFIRM_TEARDOWN=1 — honours the "all reversible" promise).
- `docs/kb/ada-nest-kk-mac-onboarding.md` — runbook: SSH re-seed
  (§1), script usage, Tailscale GUI steps, surface-level verification
  (reboot+logout test is the real bar), teardown.
- `docs/ssot/jobs/infrastructure/2026-10-21-kk-mac-ada-nest-onboarding.yml` —
  job trail with blockers + next-dispatch hint.
- `ssot.host-roles.yml` — kk-mac block: `access_note` documenting the
  auth gap; `cannot_run` updated (power fixed; reachability is
  LAN-hours-only until Tailscale).
- Board comment posted to the card summarizing all of the above.

## Result

Blocked on two gates, both converging on one KK visit: (1) the open
sign-off request (items a–e), (2) SSH re-seed via `ssh-copy-id` with KK
typing her password once. Everything that can be staged is staged — the
visit is now one script run plus the Tailscale GUI clicks.

## How to verify

- `bash -n scripts/ops/kk-mac-onboard.sh` — clean; ssot-validate-all:
  my files valid (1 pre-existing error in unrelated ncm-thai-toy-train.yml).
- After sign-off + re-seed: `ssh -J tony-dell adanest@192.168.2.92 hostname`,
  `curl 127.0.0.1:11434/api/tags` surviving logout, `tailscale status`.

## Next dispatch hint

When `kk-sign-off-*` is answered (check answers.jsonl/card), run runbook
§1 then §2, record the tailnet name in host-roles + mac-registry, close
the card.
