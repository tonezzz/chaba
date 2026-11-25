# Dispatch outcome — wiki-education-cargo-declare-verify

**Result: BLOCKED at the spec gate — no wiki writes performed.**

## What was checked

- Gate command `python3 scripts/wiki-cargo-check.py` (PR #215, merged as
  `ebee24797f`) exits **1** against the live wiki:
  - `action=cargotables` → `[]` — zero Cargo tables exist.
  - `action=cargoquery tables=Education` → MediaWiki error
    `Table Education not found` (server-side `CargoUtils::getTableSchemas`).
  - Site: MediaWiki 1.46.2, PHP 8.3.37, MariaDB 10.5 — Cargo extension present
    but no table schema has ever been created.
- Card spec says **DO NOT START until the check exits 0**. It does not, so
  steps (1)–(4) were not executed.

## Why it cannot be unblocked from this session

- Table creation is **host-owned** (card `wiki-education-cargo-table-setup`,
  ref OPS-1322, currently `doing` on idc02 under a separate claim): requires
  `php maintenance/run.php Cargo:rebuildCargoTables` (or
  `extensions/Cargo/maintenance/*`) via Plesk 8443 Terminal/Scheduled Tasks,
  or `Special:CargoTables` as wiki admin. Fill-in request:
  `~/.config/secrets/plesk-cargo-maintenance-request.md` (handoff posted to the
  card 2026-11-25 14:08).
- SSH 22/2222 to h3 is blocked; `~/.config/secrets/plesk-ssh.env` holds
  FTP-verified credentials only — FTP cannot run PHP maintenance, and
  uploading an executable helper to the production docroot is outside the
  guardrails ("disruptive host changes need Tony's approval").
- No board-api door performs Cargo maintenance (`/wiki/extension` is
  install/enable/disable only; `/wiki/page` cannot create tables).
- Re-applying declare/store now would repeat the verified 2026-11-24 failure
  (page saves + purge did not create the table) and risks a half-configured
  template — explicitly forbidden.

## State verified clean (no half-configured template)

- `แม่แบบ:Education` (pageid 42) is at **revid 483** — the byte-identical
  restore; wikitext contains no `cargo_declare`/`cargo_store`.
- `Education:` namespace is Lockdown-private (anonymous `api.php` reads return
  `accessdenied`) — private boundary intact.
- `POST /lesson {op:get, source:wiki, topic:ada-ocb-skills}` → OK,
  `Education:Ada-Ocb-Skills`, slug `lesson-d8b6938588d3` — the lesson content
  itself is live and unaffected; only the optional Cargo query layer is
  missing.

## Trail

- `docs/ssot/jobs/education/2026-11-24-skills-wiki-education.yml` — added a
  `BLOCKED` verify entry with the gate evidence.

## How to verify / resume

1. After the Plesk admin runs Cargo maintenance (OPS-1322), run
   `python3 scripts/wiki-cargo-check.py` — must exit 0.
2. Then re-dispatch this card: back up `แม่แบบ:Education`, add
   `{{#cargo_declare:_table=Education ...}}` on a dedicated `<noinclude>`
   declaration page and `{{#cargo_store:_table=Education}}` in the template
   via board-api `/wiki/page`, purge `Education:` pages, re-run the check for
   topic `ada-ocb-skills`, and record the revid here.

lessons:
- `wiki-cargo-check.py` requires BOTH the Cargo table AND the topic row, so it can only exit 0 after declare/store+purge — treat `action=cargotables` returning `[]` as the real "host work done?" precondition, not the full check.
- Cargo table creation on wiki.h3 is host-owned (Plesk Terminal `php maintenance/run.php Cargo:rebuildCargoTables` or Special:CargoTables); page saves and `action=purge` do not create tables — do not retry declare/store until `cargotables` lists `Education`.
- `Education:` is Lockdown-private: anonymous `api.php` reads return `accessdenied`; verify lesson content through board-api `POST /lesson {op:get, source:"wiki"}` instead.
- MediaWiki 1.46 `prop=revisions&rvprop=content` returns wikitext under the revision's `*` key (contentformat `text/x-wiki`), not under `slots`.
