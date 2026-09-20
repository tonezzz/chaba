# Ada Memory Vault

Human-authored, git-tracked mirror of Ada's curated memory banks. This
directory is the **authoring tier** — edit notes here (Obsidian or any
markdown editor), then push them into Ada's recall store with:

```bash
python3 scripts/ada/sync-ada-memory-to-mddb.py            # vault → MDDB
python3 scripts/ada/sync-ada-memory-to-mddb.py --dry-run  # preview
python3 scripts/ada/sync-ada-memory-to-mddb.py --export-inbox  # voice notes → inbox/
```

## Tiers

1. **This vault** — canonical curated memory, edited by humans, audited by git.
2. **MDDB `ada-ha-bank-*`** — the recall serving tier Ada queries (synced
   from this vault plus `ada_remember` voice writes).
3. **NotebookLM** — append-only deep archive (unchanged).

## Layout (folder = bank)

| Folder | MDDB collection | Scope |
|---|---|---|
| `general/` | `ada-ha-bank-general` | shared |
| `home/` | `ada-ha-bank-home` | shared (read-only for Ada) |
| `people/` | `ada-ha-bank-people` | shared |
| `personal/tony/` | `ada-ha-bank-personal-tony` | tony only |
| `personal/michael/` | `ada-ha-bank-personal-michael` | michael only |
| `tony-projects/` | `ada-ha-bank-projects-tony` | tony only |
| `note/` | `ada-ha-bank-note-tony` | tony sandbox |
| `inbox/` | *(not synced)* | voice-written notes land here for review |

Mapping is derived from `docs/ssot/apps/ssot.apps.ada-memory-banks.yml` —
rename/restructure banks there, not here.

## Note format

Each `.md` file is one memory document. YAML frontmatter maps 1:1 onto the
memory meta schema (`ssot.apps.ada-memory-schema.yml`):

```markdown
---
kind: note            # fact | preference | person | procedure | note
status: active        # active | superseded | retracted | expired
subject: gate-remote  # what it's about (update join key)
attribute: location   # which aspect
valid_until:          # optional ISO date TTL
applies_to: [cover.gate_motor]  # optional HA links
supersedes:           # optional key this doc replaces
---
The gate remote is kept in the hallway cabinet, not the kitchen drawer.
```

- `key`, `scope`, `bank`, `source`, `valid_from`, `last_verified`,
  `written_by` are managed by the sync — no need to set them.
- Doc key = `{bank}/{filename-stem}` unless frontmatter sets `key`.
- Files starting with `_` or `.` and `README.md` are skipped.

## Rules

- **Vault wins** for human-edited fields; MDDB revisions still audit writes.
- Voice writes (`ada_remember`) go to MDDB first; `--export-inbox` pulls
  them into `inbox/` — review, then move the file into the right bank
  folder to promote it.
- `writable: false` banks (e.g. `home`) block *Ada* from writing — this
  vault is human authority and syncs regardless.
- **`personal/*` is git-ignored** — the chaba repo is public on GitHub, so
  private notes stay local-only (decided 2026-09-20: no private mirror, no
  encryption). The pre-commit hook hard-blocks staged `personal/**` files.

## Backup & restore

- `ada-memory-backup.timer` (nightly 04:30, tony-omen) dumps every bank +
  recall-summary collection to `backups/ada-memory/` (shared, in git) and
  `~/.local/share/ada-backups/ada-memory/` (personal, never git).
- `ada-memory-backup-mirror.timer` (weekly Sun 05:00, tony-omen) pushes the
  dumps to `mn01:~/.local/share/ada-mddb-mirror/` — a warm copy off the
  primary host.
- **Restore:** `scripts/ada/restore-mddb-banks.py <dump-dir>` — verified in a
  drill 2026-09-20 (content + meta identical). RTO ≈ minutes once a dump
  exists; the mn01 mirror covers tony-omen loss.
- If MDDB is down but the vault is intact, recall falls back to NotebookLM
  deep tier until MDDB is restored.
