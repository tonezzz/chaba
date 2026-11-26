# Dispatch outcome — devin-cli-fleet-update-20261108 (2026-11-17)

## Result: DONE — no updates needed; all hosts already on latest

| host | CLI | `devin update` | doctor | auth |
|---|---|---|---|---|
| tony-dell | 3000.12.57 | already latest | 3/3 pass | logged in |
| tony-omen | 3000.12.57 | already latest | 3/3 pass | logged in |
| tony-macbook | 3000.12.57 | already latest | 3/3 pass | logged in |

The card's 2026-11-08 evidence (Omen 3000.11.205 / Dell 3000.11.234) was
stale: the approved 11-08 interactive update plus auto-update and the
11-15 MacBook installer brought every host to 3000.12.57 (symlink into
`~/.local/share/devin/cli/_versions/current`, auto-update-enabled).

## New runbook nugget

`devin update` exits 130 without a TTY. Instead of an interactive SSH
session, wrap it in `script` to allocate a PTY on the remote:

    ssh -o BatchMode=yes <host> \
      'script -qec "$HOME/.local/bin/devin update" /dev/null'

Verified working over BatchMode non-interactive SSH on omen and
macbook. Trail: `docs/ssot/jobs/infrastructure/2026-11-17-devin-cli-fleet-update-verify.yml`.

## Notes

- `devin` is not on PATH in non-interactive SSH shells — use
  `$HOME/.local/bin/devin`.
- MacBook reached directly as `tony-macbook` (100.77.76.112) over
  tailscale from dell; `kk-macbook` resolves nowhere. Host reports as
  linux x86_64 despite the name.
- Constraints honored: Devin Desktop untouched, runner timers still
  paused, no mcp-debug on macbook, no git pushes.

## Verify

    devin update && devin doctor                       # dell
    ssh tony-omen    'script -qec "$HOME/.local/bin/devin update" /dev/null'
    ssh tony-macbook 'script -qec "$HOME/.local/bin/devin update" /dev/null'
