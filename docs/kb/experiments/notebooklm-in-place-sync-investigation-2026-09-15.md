# NotebookLM in-place Drive sync investigation

Date: 2026-09-15
Notebook: fdfd3483-6b7e-4cb0-85f3-7f060698769c

## Goal

Determine whether we can replace the current "delete + re-add" KB sync with
in-place updates of Google Drive files, so that NotebookLM's automatic Drive
syncing can keep sources fresh without deleting and re-creating them.

## Findings

1. `nlm source --help` shows no `update` subcommand.
   Supported source actions: `list`, `add`, `get`, `describe`, `content`,
   `rename`, `delete`, `stale`, `sync`.

2. `nlm source sync` exists, but it only syncs **Drive sources** that were
   added from an existing Google Drive file.

3. Our current sources are typed `google_docs` (created/uploaded via the API)
   rather than `drive`.

4. The automatic Drive-sync feature announced by Google only applies to
   files that were already in Drive when added to a notebook.
   Native Docs/Sheets/Slides are supported; Markdown/YAML generated chunks
   are not.

5. To use in-place updates we would need to:
   - Keep one stable Google Drive document per source.
   - Update its content in place via the Drive API (or a tool that preserves
     the `drive_id`).
   - Add it to NotebookLM as a `drive` source, not a new `google_docs` source.
   - Rely on `nlm source sync` (or the auto-sync) to refresh.

6. The current `nlm-add` pipeline is built around creating new Google Docs,
   so switching would require a non-trivial rewrite of the upload path.

## Recommendation

Do not migrate the main Chaba KB yet. Keep the deterministic delete/re-add
pipeline for generated Markdown/YAML chunks. The in-place + auto-sync pattern
is promising for stable, manually-maintained Google Docs only; it is not a
drop-in replacement for the custom Git-to-NotebookLM sync.
