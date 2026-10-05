# Dispatch outcome — idc01→idc03 migration Phase 1 (inventory + plan)

**Result: done.** Read-only inventory of idc01 and idc03 completed; no production changes made.

## Deliverables (in this worktree)

- `docs/ssot/infrastructure/idc01-to-idc03-migration-plan.md` — full inventory, per-item migrate/retire decisions + dependency order, idc03 capacity check, cutover+rollback per item, what-stays list, 9 flagged approvals.
- `docs/ssot/jobs/infrastructure/2026-10-05-idc01-to-idc03-migration.yml` — job-lifecycle artifact.

## Key findings

- **idc01** (157.85.110.99 / 100.74.146.0, Siamdata): 2 vCPU, **31 GiB RAM** (SSOT says 8–12 G — drift), 96 G disk / 60 G used. Runs: **9 containers** (mddb leader, ollama, gemini-ollama-proxy, caddy-edge, camwall-edge, input-bridge, mddb-panel, vcast-headless ×2), **20 service units** (ada-pi-pwa/tony/michael/dev, line+tg relays, obsidian-vault, doc-archive, jev-student), **22 enabled timers**, no cron. ~30 G state (~12 G essential; 17 G is mddb-backups). Public TLS: `api.surf-thailand.com` (CF-proxied → :8001 + webhook routes) + sslip name. Tailscale serve → :8001-8004. ufw: public 80/443 only.
- **idc03** (157.85.102.125 / 100.102.134.91, Siamdata): tailnet-joined today ~13:15Z, online, but **ssh denied for every key** (tony/root from dell; idc01/idc02→idc03 also denied). Public :22 open (not yet hardened). **Capacity unverified — Phase-2 blocker, needs Tony to authorize a key via the provider panel.**
- Surprises: `input-bridge` binds **0.0.0.0:3010** (SSOT claims tailnet-pinned; ufw is the only guard); `doc-archive` listens on tailnet **:11025** — undocumented in security SSOT; `chaba-vault` repo on idc01 has **41 dirty files** (reconcile before rsync); `ada-dev` :8005 running but unit disabled; mddb quadlet has inline secrets to move to EnvironmentFile; ~18 orphan podman volumes + retired open-notebook residue marked retire/drop.
- Plan approach per card: mddb via replication (follower on idc03 → promote → idc02 repoints leader), then services+secrets via rsync, caddy-edge + CF DNS repoint last, 24–48 h soak. idc01 stays untouched until soak — every rollback is "repoint back".

## How to verify

```bash
cat docs/ssot/infrastructure/idc01-to-idc03-migration-plan.md
ssh idc01 'podman ps; systemctl --user list-timers --all | wc -l'   # spot-check inventory
tailscale status | grep idc03                                       # 100.102.134.91 online
ssh tony@100.102.134.91 hostname                                    # currently: Permission denied (the blocker)
```

## Waiting on Tony (flagged, non-blocking for Phase 1)

idc03 ssh authorization is the only hard blocker for Phase 2. Other approvals (DNS repoint, mddb promotion, backups scope, chaba-vault dirty files, ada-dev, mn01 aliases, idc01 keep-vs-cancel) are listed in §Flags of the plan.
