# Dispatch outcome — lab-crush-cli (crush CLI lab assessment)

**Verdict: adopt-as-alt-lane.** Job trail: `docs/ssot/jobs/lab/2026-10-09-crush-cli-assessment.yml` (in this worktree).

## What was done

1. **Install** — crush v0.98.0 on tony-dell at `~/.local/bin/crush` via the GitHub release
   tarball (`crush_0.98.0_Linux_x86_64.tar.gz`). go1.26.0 was present on both hosts, but the
   tarball is lower-friction. `crush --version` verified.
2. **Provider config** — `~/.config/crush/crush.json` on tony-dell with
   `providers.openrouter.api_key = "$OPENROUTER_API_KEY"` (env expansion works).
   `~/.config/secrets/openrouter.env` was copied from tony-omen (tony-dell had none).
   **The key is valid but the account has zero credits** — paid models return 402;
   the assessment ran on `nvidia/nemotron-3-super-120b-a12b:free`.
3. **Smoke tests** (scratch `/tmp/crush-lab-devin-omen`, never a live repo):
   - Task 1 (write fizzbuzz.py + test_fizzbuzz.py, run pytest): **28 s**, 5 tool calls
     (ls → write ×2 → pytest → verify output), 4/4 tests pass on independent re-run.
   - Task 2 (edit existing file: sys.argv bound + new test): **30 s**, surgical `edit`
     calls with view-before-edit, self-recovered from `python`→`python3`, 5/5 pass.
   - Tool-call behavior is sane; all writes stayed inside the scratch cwd.
4. **MCP check** — `mcp` stdio stanza pointing at a minimal read-only MCP server parsed,
   connected, and tools (`mcp_<name>_<tool>`) were discovered and called correctly.
   Global↔project config merge confirmed live.

## Gotchas found (worth remembering)

- `--yolo`/`-y` is listed in `crush --help` but **rejected by the v0.98.0 flag parser** —
  unattended runs need `"permissions": {"allowed_tools": [...]}` in config.
- **Parallel-agent collision:** a second agent ran the same lab procedure on tony-dell
  concurrently — overwrote files in shared `/tmp/crush-lab` mid-run and rewrote the
  *global* `~/.config/crush/crush.json`. Isolated my work to `/tmp/crush-lab-devin-omen`
  with a project-local `.crush.json`. For any multi-agent crush use, prefer project-local
  config.

## Verdict reasoning

- **crush beats devin-dispatch:** interactive TUI; model flexibility (any OpenRouter model,
  including `:free` tiers, one-line swap); trivial stdio/http MCP wiring; low ceremony for
  ad-hoc local tasks; `crush server` socket mode, `--continue`, session audit db.
- **dispatch beats crush:** unattended kanban lifecycle (claim/comms/requests/answers),
  TASK_RAILS (worktree confinement, no-push, merge gates), outcome artifacts, board
  integration — crush has none of this.
- **Recommendation:** keep installed on tony-dell as an interactive/manual lane; do not
  wire into the dispatch loop. Re-run with a paid coding model after OpenRouter top-up for
  a fairer harness comparison.

## How to verify

- `ssh tony-dell '~/.local/bin/crush --version'` → v0.98.0
- `ssh tony-dell 'cd /tmp/crush-lab-devin-omen && python3 -m pytest test_fizzbuzz.py -q'` → 5 passed
- `ssh tony-dell 'cat ~/.config/crush/crush.json'` → openrouter provider + mcp + allowlist
- Board card `lab-crush-cli` has progress + outcome comments.
