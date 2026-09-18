# NotebookLM Apps

Mini web frontends and helper tools for the central NotebookLM deployment on tony-dell.

## Subapps

| Subapp | Path                  | Purpose                                                                  |
| ------ | --------------------- | ------------------------------------------------------------------------ |
| v0     | `apps/notebooklm/v0/` | Static landing page and quick reference for NotebookLM CLI/REST helpers. |

## Related infrastructure

- `~/.local/bin/nlm` — CLI wrapper for the `notebooklm-mcp` container
- `~/.local/bin/nbapi` — REST API helper
- `~/.local/bin/nlm-add` — Upload local files to Google Drive and add to a notebook
- Caddy: `https://tony-dell.taila0626a.ts.net/apps/notebooklm/api` (REST)
- SSOT: `docs/ssot/infrastructure/ssot.values.yml` → `notebooklm`
