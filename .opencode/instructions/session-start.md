# Session start — Chaba resume context

At the start of a session that continues prior work (resume, follow-up, status check, or when the user asks "where were we"), run the `/recall` command first: it refreshes the rendered Chaba L0 context (`render-memory.py --if-stale`) and injects a bounded (~4k char) pointer-first head from `~/.local/share/chaba/context.md`.

Rules:
- The rendered context is a **resume signal, not truth** — follow its canonical refs/SSOT for detail; verify volatile state live.
- If `/recall` output is stale or missing, say so and fall back to SSOT-first retrieval (`docs/ssot/ssot.knowledge-capture.yml`).
- Do not paste the whole context file into replies; summarize the relevant pointers.
