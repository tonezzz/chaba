# kk-mac Ada Nest onboarding runbook

KK's Mac Studio (`kk-mac`, Mac16,9 M4 Max 14-core, 36 GB unified, macOS
15.7.3, user `kkkakk`) as an Ada Nest member node. Card:
`kk-mac-ada-nest-onboarding` (ADA-0765). Sign-off checklist lesson:
`ada-nest-hardware` (post 1775) — **every step that changes the machine
needs KK present and consenting.** Teardown path is in the script
(`teardown` step) so consent is honest.

## State (as of 2026-10-21)

Done by the 15:5x session:

- pmset: `sleep 0 disksleep 0 displaysleep 15` (womp already on)
- Xcode CLT 16.4, Homebrew `/opt/homebrew` (API mode), tmux
- Ollama 0.40.7 cask, serving :11434 via `nohup` under kkkakk —
  **login-bound, dies on logout; the LaunchDaemon step replaces it**
- Bench: llama3.2:3b = 123 tok/s eval / 254 tok/s prompt, 1 s load

Open:

- **SSH auth**: no fleet key currently authenticates to `kkkakk@kk-mac`
  (probed omen/dell/mn01/macbook keys 2026-10-21 ~16:20 — all denied,
  port open on .80 en0 and .92 en1). Whatever credential the earlier
  session used was not persisted. Re-seed at install time (§1).
- KK sign-off request on the card covers: adanest user, Tailscale,
  boot-time ollama, sleep=0 on AC, ~20 GB of model pulls.
- Tailscale, adanest user, ollama LaunchDaemon, model pulls — staged in
  `scripts/ops/kk-mac-onboard.sh`, not yet run.

## 1. Restore SSH access (gate for everything remote)

At install time with KK present — she types her password once:

```bash
# from tony-omen or tony-dell
cat ~/.ssh/id_ed25519.pub ~/.ssh/id_cascade.pub > /tmp/fleet-kk.pub
ssh tony-dell 'cat ~/.ssh/id_ed25519.pub ~/.ssh/id_mcp_debug.pub' >> /tmp/fleet-kk.pub
ssh-copy-id -i /tmp/fleet-kk.pub -J tony-dell kkkakk@192.168.2.92
# fallback IP: .80 (en0 wired, :22 intermittently filtered)
```

Standard inbound set per `docs/kb/new-host-onboarding.md` §2: omen +
dell fleet keys. Verify: `ssh -J tony-dell kkkakk@192.168.2.92 hostname`.

## 2. Run the onboarding script

On kk-mac, as `kkkakk` (admin — sudo prompts are the sign-off moments):

```bash
scp -J tony-dell scripts/ops/kk-mac-onboard.sh kkkakk@192.168.2.92:/tmp/
scp -J tony-dell /tmp/fleet-kk.pub kkkakk@192.168.2.92:/tmp/
ssh -t -J tony-dell kkkakk@192.168.2.92 \
  'FLEET_KEYS_FILE=/tmp/fleet-kk.pub SEED_KKKAKK=1 bash /tmp/kk-mac-onboard.sh'
```

Steps (each idempotent, individually selectable):

| step | what | sudo? |
|------|------|-------|
| preflight | assert hw.model=Mac16,9, brew+ollama, disk ≥30 GB | no |
| power | `pmset -a sleep 0 disksleep 0 displaysleep 15 womp 1 powernap 0` | yes |
| user | create `adanest` — standard, hidden, `Password '*'`, ssh group | yes |
| keys | seed FLEET_KEYS_FILE into adanest (+kkkakk if SEED_KKKAKK=1) | yes |
| ollama-daemon | `/Library/LaunchDaemons/ai.adanest.ollama.plist` → `ollama serve` as adanest, KeepAlive+RunAtLoad; ditto-migrates kkkakk's `~/.ollama` so the 3b pull survives; stops the nohup server | yes |
| tailscale | `brew install --cask tailscale` + prints the GUI steps | partial |
| models | `ollama pull` as adanest — default `llama3.1:8b qwen3:14b` (~14 GB; override MODELS=) | via adanest |
| verify | pmset, `id adanest`, `launchctl print`, `/api/tags`, tailscale status | mixed |

## 3. Tailscale — the one part that needs KK's hands

Cannot be scripted on macOS: the app installs a Network/System
Extension that macOS only approves from a logged-in GUI session.

1. `open /Applications/Tailscale.app`
2. Approve the extension prompt (System Settings → General →
   Login Items & Extensions → Network Extensions if deferred).
3. Sign in — browser flow, or headless with an auth key minted at
   login.tailscale.com/admin/settings/keys:
   `sudo /Applications/Tailscale.app/Contents/MacOS/Tailscale up --authkey tskey-…`
   (`TAILSCALE_SSH=1` adds `--ssh` for tailscale-ssh in.)
4. Verify `tailscale status` shows the node; then it is reachable
   away-from-home like kk-macbook.

## 4. Verify (by surface, not by service)

- From a fleet host: `ssh -J tony-dell adanest@192.168.2.92 hostname`
- `ssh -J tony-dell kkkakk@… 'curl -s 127.0.0.1:11434/api/tags'` —
  models listed under the daemon, surviving logout
- Reboot test: after a reboot with nobody logged in, :11434 answers and
  `tailscale status` is up — that is the real member-node bar.
- Update `ssot.host-roles.yml` kk-mac block + `ssot.mac-address-registry.yml`
  note with tailnet name once Tailscale is up.

## 5. Teardown (the reversibility promise)

```bash
CONFIRM_TEARDOWN=1 bash kk-mac-onboard.sh teardown
```

Deletes the adanest user + home + LaunchDaemon. Then manually:
`brew uninstall --cask ollama tailscale`, delete `/opt/homebrew` if brew
is otherwise unused, `sudo pmset -a sleep 1 powernap 1` to restore her
desktop power policy, and remove the tailnet node in the admin console.

## Notes / gotchas

- Wi-Fi at her desk is 2.4 GHz-only (en1, RSSI -68 dBm, ~28 Mbps).
  Wired en0 (.80) is primary; en0:22 is intermittently filtered —
  prefer .92 for SSH.
- Script is bash-3.2-safe (macOS ships 3.2 as /bin/bash).
- Ollama binds 127.0.0.1 by design — LAN/tailnet exposure is a separate,
  explicit decision (`OLLAMA_BIND=` + a note in host-roles).
- Machine travels with KK → Tailscale is what makes it a node rather
  than a desk ornament; without it, treat every remote capability as
  home-hours-only.
