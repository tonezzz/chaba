# Dispatch outcome — audit-miss-ada-chaba-home-snapshot

Date: 2026-11-24 · Branch: `dispatch/20261124-170951-reconcile-the-live-ada-ha-chab` · Commit: `702c18d10c0`

## What was found

- `docs/home-assistant/dashboards/ada-ha-chaba-home-current.json` was deleted in `86ae90671` (2026-10-20) with the note "dashboard no longer exists" — that was wrong. The live `lovelace.chaba_home` storage dashboard on ada-ha (tony-omen, `/home/tony/.config/ada-ha/.storage/lovelace.chaba_home`) exists and was verified read-only over SSH.
- Live views: `ai → chat → calendar → gesture → report → nobito` — identical set to the SSOT note and to the 2026-10-29 read-only lookup cited in the card.
- The stale SSOT reference was `docs/ssot/infrastructure/ssot.home-assistant.instances.yml` → `ada-ha.dashboards.chaba-home.note` → "Snapshot: docs/home-assistant/dashboards/ada-ha-chaba-home-current.json".

## What changed

- **Regenerated the snapshot** via the supported read-only sync path: `scripts/home-assistant/sync-ada-ha-chaba-admin.py --host tony-omen --remote-path .../lovelace.chaba_home`. Output is the sanitized `{views: [...]}` format (same as `ada-ha-chaba-admin-current.json`), NOT the raw `.storage` envelope the deleted file had last been committed in. Verified `snapshot == live config` exactly.
- `scripts/home-assistant/sync-ssot-from-live.sh`: `--instance ada-ha` now syncs chaba-home alongside chaba-admin, so the snapshot stays fresh through the documented entry point.
- `scripts/home-assistant/sync-ada-ha-chaba-admin.py`: `sanitize_snapshot` gained path tracking; `key` fields under `pfg_charts` are exempt from redaction (pfg3d chart series identifiers, not credentials — the sanitizer was false-positiving `"key": "nobito"`).
- `tests/test_ada_ha_dashboard_snapshot.py`: added coverage for the pfg_charts exemption (4/4 pass).
- `ssot.home-assistant.instances.yml`: chaba-home note records the regeneration, the `{views}` format, and that the 86ae90671 deletion was a false "dashboard gone" call.
- `ssot.home-assistant.dashboards.yml`: `manual_steps` snapshot line updated to mention both ada-ha snapshots.

## Live dashboard

Not mutated — only `ssh tony-omen cat .storage/lovelace.chaba_home` (read).

## Credential / privacy check

- Sanitizer reported **0 redactions** needed for this dashboard (no api_key/token/secret fields or query params present).
- Grep of the committed file for `api_key|token|secret|password|bearer|eyJ|sk-|ghp_|xox` → no matches.
- The only personal datum is the Google Calendar embed URL (`src=tonezzzz@gmail.com` + `en.th#holiday`) — both sources already documented in SSOT and previously committed in `600ae258344`; no calendar *event* data is in the config (embed URL only). No new exposure.

## Verification

- `node scripts/ssot-validate-all.mjs` on both touched YAML files → valid, 0 errors/warnings.
- `python3 scripts/ssot-validate-refs.py` → OK: 6164 files, no broken refs.
- `pytest tests/test_ada_ha_dashboard_snapshot.py` → 4 passed.
- Pre-commit SSOT gate passed (hostname/prose warnings are pre-existing, unrelated blocks).

## How to verify

```
python3 scripts/home-assistant/sync-ada-ha-chaba-admin.py \
  --host tony-omen \
  --remote-path /home/tony/.config/ada-ha/.storage/lovelace.chaba_home \
  --output /tmp/chaba-home-check.json   # should equal the committed file
git show --stat HEAD
```

## lessons:

- `sync-ada-ha-chaba-admin.py` is generic despite the name — `--remote-path`/`--output` args make it the read-only snapshot path for any ada-ha lovelace storage file.
- The sanitizer's `key` field-name rule false-positives on pfg3d-card `pfg_charts.*.key` series ids; now exempted path-scoped — other `key` fields still redact.
- ada-ha snapshot files use the sanitized `{views}` envelope-less format; tony-ha/michael-dev `*-current.json` files are raw `.storage` envelopes — don't assume one format repo-wide.
- "Dashboard no longer exists" claims should be verified against `.storage/lovelace.*` on the host before deleting snapshots — 86ae90671's premise was wrong.
