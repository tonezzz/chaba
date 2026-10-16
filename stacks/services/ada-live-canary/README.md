# ada-live-canary

Minimal Gemini Live connect probes on idc03 (user systemd). Each run
opens one `client.aio.live.connect`, closes immediately, and appends a
verdict line to a JSONL ledger — the cheapest possible "is this lane
alive" signal. `scripts/ada/gemini-live-canary.py`.

## Lane policy (card bench-off-paid-lanes, 2026-10-14)

Automated probes never bill a paid project:

- `ada-live-canary.timer` — **hourly :17, FREE key**
  (`GEMINI_API_KEY_FREE`). Maps the free-tier ceiling that the
  scenario-suite budget ramps against. Free connects are disposable.
- `ada-live-canary-paid.timer` — **daily 06:12, PAID key**
  (`GEMINI_API_KEY_PAID`). Exactly 1 connect/day: enough to detect
  paid-lane dunning (`402/1011` = depleted wallet, `429` = per-key
  quota, `auth` = key rotated out) without measurable spend.
- `gemini-wallet-watch.timer` — hourly :47, ~1-token `generateContent`
  REST probe per paid lane key (`scripts/ada/gemini-wallet-watch.py`
  `--key-var` repeat: PAID + TONY + KK + MICHAEL). This is the
  depletion/cap **alerting** path (LINE notify per key on ok→credit
  transitions — tony DM for all, kk group only for KK's own key), not
  a Live connect — ~96 tokens/day is not a billing concern. Per-key
  coverage added 2026-10-16: the ada-ha-tony 1011 incident was
  GEMINI_API_KEY_TONY hitting its project cap while the shared PAID
  probe stayed green. If policy later wants it daily too, it is a
  one-line `OnCalendar` change.

Ledgers: `~/.local/share/ada-live-canary.jsonl` (free) and
`~/.local/share/ada-live-canary-paid.jsonl` (paid). Both land in the
spend-ledger audit trail via journald.

## Install (idc03)

```bash
cd stacks/services/ada-live-canary && ./install.sh
```

## Read the ceiling

```bash
jq -r '[.ts,.verdict]|@tsv' ~/.local/share/ada-live-canary.jsonl | tail
journalctl --user -u ada-live-canary-paid --since today
```
