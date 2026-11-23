---
description: Inject bounded Chaba L0 resume context (pointer-first, read-only)
---

Load bounded Chaba resume context for this session$ARGUMENTS.

## Steps (read-only)
1. Refresh if stale: run `~/.local/bin/chaba-session-capture render --if-stale` (or `python3 scripts/chaba/render-memory.py --if-stale` from the repo root). If unavailable, continue with the existing context file.
2. Read `~/.local/share/chaba/context.md` (fallback: `.local/share/chaba/context.md` under the current home). If missing, say so clearly.
3. Inject only a **bounded head** (max ~4000 chars / first sections) as resume signal. Treat it as pointer-first context: follow canonical refs/SSOT for detail; do not treat stale volatile facts as truth.
4. Report: `as_of`/render timestamp from the file header, what was loaded, and any missing/stale caveats.

## Guardrails
- Read-only; no fake events/writes.
- No secrets, no copied SSOT bodies, no stale volatile snapshots presented as current truth.
- If context is stale/missing, say so and fall back to SSOT-first retrieval (`docs/ssot/ssot.knowledge-capture.yml`).
