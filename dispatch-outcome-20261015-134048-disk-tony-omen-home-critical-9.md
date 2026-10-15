# dispatch-outcome — disk-tony-omen-home-critical-9 (OPS-0405)

## Result
- **/home crisis already resolved before this session started** — verified, no emergency action needed.
- `/dev/nvme0n1p3` (/home): 99% / 4.1 GiB free during 10:31–13:15 → **57% / 127 GiB free now**.
- `/dev/nvme0n1p7` (/data): 61% → **88% / 36 GiB free** (it absorbed the moves — now the watch item).

## What happened (reconstructed)
- Oct 12→14: /home grew 199.6G→242.5G (~9 GiB/day baseline: devin-cli `sessions.db` backups ~5.5G each with no retention, CascadeProjects dispatch worktrees, .venvs).
- Oct 14 ~19:00–22:10: the **model-fleet-benchmark dispatch** pulled ~30G+ — `~/model-bench/gemma-3-27b-it-Q4_K_M.gguf` (15.4 GiB), `Llama-3.2-3B` (2G), `~/.ollama` blobs (~10G), `~/models/sd/sdxl-lightning` (2.6G), `~/.venvs/ada-whisper` CUDA libs (~1.3G). Job file: `docs/ssot/jobs/models/2026-10-14-model-fleet-bench.yml`.
- Oct 15 ~07:45→10:31: final ~19G pushed /home to 99% where it sat until 13:15 (side effect: EMFILE "Too many open files" in user journal ~13:26).
- 13:26 `wake-screens` fired; 13:30–13:36 a console cleanup (operator) moved `~/mddb-backups-idc01-retired` (64G) → `/data/backups/mddb-backups-idc01-retired` + symlink, and 3 devin-cli session-DB backups (~13G) → `/data/backups/devin-cli/`; ~55G more was deleted outright.
- This dispatch (13:40+) verified the end state and moved the one leftover `sessions.db.20261011-203232` (5.5G) to the same `/data/backups/devin-cli/` destination.

## Changed by this session
- `mv ~/.local/share/devin/cli/backups/sessions.db.20261011-203232 → /data/backups/devin-cli/` (+5.5G free on /home)
- New trail file: `docs/ssot/jobs/monitoring/2026-10-15-tony-omen-home-disk-critical.yml`
- Board comm posted on `disk-auto-tony-omen-home`

## Follow-ups flagged on the card
- `/data` at 88% (36G free) — needs retention/landing-zone decision (tracked by `disk-auto-tony-omen-data`).
- disk-trend watchlist blind spot: `DISK_TREND_DU_ROOTS` covers only `~/.cache/*` + `/var/log`; actual growers (`~/model-bench`, `~/.ollama`, `~/.local/share/devin`, `~/.venvs`, `~/CascadeProjects`) unmonitored.
- devin-cli session-DB backups have no keep-N (~5.5G each).
- FYI seen in same probe: tony-dell `/` at 98% — covered by `disk-auto-tony-dell-root`.

## How to verify
- `df -h /home /data` → expect ~57% / ~88%.
- `ls -la ~/mddb-backups-idc01-retired` → symlink to `/data/backups/mddb-backups-idc01-retired`.
- `ls /data/backups/devin-cli/` → 4 session-DB archives (~18G).
- Next disk-trend-watch sample should show /home below crit and auto-close the card.
