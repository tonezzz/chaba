# Colab MCP job pattern — the 4-step standard

Standard shape for any ad-hoc job driven through the `colab` MCP server
(`googlecolab/colab-mcp`, registered as `colab` in mcp_config.json).

The publish step is **part of the job**, not a follow-up — a job is not
done until its output has a durable home (artifact-landing rule,
`ssot.procedures.yml`).

## Steps

1. **Attach** — `open_colab_browser_connection` → user connects in browser →
   cell tools unlock. MCP attaches to the **scratch notebook**, not the
   serve-worker (whose kernel is busy in keep-alive).
2. **Setup cell** — install what the job needs (ollama via
   `ollama-linux-amd64.tar.zst` + `apt install zstd`, or pip). Pull datasets
   via `colab-gdrive-cache` (drive mount → packed artifact → extract local)
   or a fast mirror — never the slow origin directly.
3. **Job cell(s)** — the actual work. Write intermediate output to
   `/tmp` on the runtime AND return it in cell output (MCP fetches outputs
   via `get_cells includeOutputs`).
4. **Publish (mandatory)** — the agent turns output into a durable home in
   the same step it collects it:
   - report/analysis → CMS leaf page in `ada-cms-pages` (`mddb add_document`,
     meta: `report_role`, `generated_by`, `sources`, `parent`) —
     `ssot.apps.cms-reports.yml` format
   - card outcomes → `comms:` via board-api
   - reusable artifacts → gdrive cache (`rclone` on tony-dell if mount fails)
   - parked ideas → `docs/ssot/focus-inbox/`
   Never: output in `/tmp` only, or pasted in chat only.

## Verified example (2026-10-12)

Backlog triage: ollama + `gemma3:12b` installed on scratch T4 (147s), 100
kanban cards classified in 2x50 parallel batches (204s+296s), published as
`ada-cms-pages/backlog-triage-2026-10-12`.

## Gotchas

- `run_code_cell` may return `Canceled`/empty — the cell often still runs
  server-side; poll `get_cells includeOutputs` instead of re-firing.
- Kernel serializes cells — a blocking cell (keep-alive, hung download)
  stalls everything queued behind it; interrupt via the notebook stop button.
- `drive.mount()` in an MCP-run cell can fail (`ValueError: mount failed`)
  — run the mount cell manually in the notebook, or push artifacts from a
  fleet host via `rclone` (`gdrive:` remote on tony-dell).
- Runtime type (T4 etc.) is a UI-only pick — no MCP tool for it.
- Colab ends sessions on idle/quota — treat the runtime as ephemeral;
  anything worth keeping must land in step 4 before it dies.
