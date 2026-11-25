# Plesk admin request — create the Education Cargo table (OPS-0038)

**Fill in the blanks and paste the evidence back to Tony / the ada-ocb card `OPS-0038`. Do not paste credentials into chat.**

| Field | Fill in |
| --- | --- |
| Request ID / card | OPS-0038 (`wiki-education-cargo-table-setup`) |
| Requested by / date | Tony / 2026-11-25 |
| Wiki host / Plesk subscription | ______________________________ |
| Access method (SSH / Plesk Terminal / File Manager) | ______________________________ |
| Admin performing the work | ______________________________ |
| Access window (date/time) | ______________________________ |
| Approval for host maintenance | Yes / No — date: ______________ |

## Why

Cargo is installed and approved on wiki.h3, but no Cargo tables exist: `action=cargotables` returns `[]`. Adding `{{#cargo_declare}}` and `{{#cargo_store}}` to `แม่แบบ:Education` and a declaration page did **not** create the table (template revids 481/482; both reverted at 483/484). Table creation needs a host-level Cargo maintenance action that the board-api `/wiki/page` door cannot perform.

## Action for the admin

1. Back up `LocalSettings.php` and note the backup path: ______________________
2. From the wiki docroot (typical path, confirm on host):

   ```bash
   cd /var/www/vhosts/ultimate-official.com/www/wiki.h3.gizmo-thailand.com
   php maintenance/run.php Cargo:rebuildCargoTables
   ```

   If that entrypoint is not present on MediaWiki 1.46, use the extension script instead (fill in which one worked):

   ```bash
   php extensions/Cargo/maintenance/rebuildCargoTables.php
   php extensions/Cargo/maintenance/cargoRecreateDB.php
   ```

   Alternative if shell is unavailable: `Special:CargoTables` in the MediaWiki admin UI → create/rebuild the `Education` table.

3. Verify on the wiki API and paste the JSON:

   ```bash
   curl -s 'https://wiki.h3.gizmo-thailand.com/api.php?action=cargotables&format=json'
   curl -s 'https://wiki.h3.gizmo-thailand.com/api.php?action=cargoquery&tables=Education&fields=_pageName,topic,next_review&limit=5&format=json'
   ```

## Evidence to paste back

- Command(s) actually run: ________________________________________________
- `cargotables` JSON (must include `Education`): __________________________
- `cargoquery` JSON (must include `Education:Ada-Ocb-Skills` / topic `ada-ocb-skills`): ________________________________________________
- Timestamp (host time): __________________  Admin initials: ______________
- Rollback / notes: ______________________________________________________

## After the admin fills this in

The agent will run `python3 scripts/wiki-cargo-check.py` in the ada-ocb worktree; it must exit 0. Only then will the declare/store be re-applied and verified (card `OPS-1350`). Until the table exists, **do not** re-apply the template edit — no half-configured template should be left live.

## Guardrails

- Keep wiki writes behind board-api (`/publish`, `/wiki/page`); no direct MediaWiki writes from agents.
- `Education:` is Lockdown-protected/private; keep private content off the public `wiki`/`News:` surface.
- Secrets stay in the Plesk/secret store and environment variables, never in chat or this file.
- Disruptive host changes need Tony's approval and a recorded rollback.
- Expiry default: if no Plesk/admin access by **2026-12-08**, close `OPS-0038` and `OPS-1350` as declined optional polish — `Education:Due` and `Education:Index` already work without Cargo.
