# Dispatch outcome — ada-voice drop rot audit (card chaba-merge-gate-ada-drops-rot-audit)

## What was found

Re-ran the 50-patch tri-state audit (`git apply --check` / `-R --check`,
same semantics as `tests/ada/_drops.py`) against **ada-voice main @
8223b56** — the task cited the 07119b1 audit, but upstream had moved 18
commits since. Result:

- **No rotted pending drops.** The two genuinely pending patches that
  diverged on the old base — `realtime_provider.cast-loop.patch` (drop
  10, already repaired by ADA-0080 and merged via PR #138 `b591a9b2`)
  and `realtime_provider.correction-command.patch` (drop 11) — apply
  forward cleanly on current upstream. No re-repair needed or done.
- **All 10 remaining diverged patches are post-merge drift on deployed
  drops** — the features are live upstream and the files evolved after
  merging, so the staged patches are stale record copies, not broken
  drops:
  - drop 2 `line_relay.file-doc-ingest` — deployed `6148f64` +
    `2c3ee2f`/`5f6ff95`/`0c2fe89`
  - drop 5 `line_relay.voice-enroll-recognize` — deployed `02c5058`
  - drop 7 `line_relay.image-delivery` — deployed `02c5058`
  - drop 8 `line_relay`/`tg_relay`/`tool_runner`/`pwa_server`
    `.reply-routing` — deployed `8f8f488`
  - drop 9 `line_relay`/`tg_relay` `.whisper-url` — deployed `af310ef`
    + `c8c07c7` (README's `daa0e0a` was a stale pre-push id)
  - drop 12 `ssot.tool-surface.cpt-post` — deployed `f015b52`
- **`voice-enroll-recognize` + `whisper-url` patch question answered:**
  they belong to drops 5 and 9 (deployed); no `tests/ada` file guards
  them — orphaned from the drop-guard's perspective but benign since
  the features shipped.
- **Pending drops verified genuinely absent upstream** (not
  accidentally duplicated by forward-applying patches): drops 3, 10,
  11, 14, 15, 16, 17, 18.
- Additional staleness found+fixed in README: drops 1 (trip_calendar,
  `6148f64`) and 13 (write-fidelity, `04154f6`) were deployed but
  unmarked; drop count said "Seventeen" but lists 18.

## What changed

- `integrations/ada-voice/README.md` — drop count 18; new "Patch
  currency" paragraph (tri-state rule + record-copy guidance); deployed
  markers + upstream commit refs for drops 1/2/9/12/13; per-drop drift
  notes for drops 5/7/8/9/12.
- `docs/ssot/jobs/ada/2026-11-13-ada-voice-drop-rot-audit.yml` — job
  record with the full per-patch verdict table.
- Committed on `dispatch/20261113-124849-evidence-2026-11-13-after-ada-`
  (`7c5fa92999`). No push, no deploy.

## Verification

```
ADA_PI=<ada-voice clone @ 8223b56> .venv-gate/bin/python -m pytest tests/ada -q -rf
=> 270 passed, 1 skipped (test_cms_render — pre-existing self-skip, needs jinja2)
```

Caveat for the merge gate: **idc02 has no pytest-capable interpreter** in
the gate's default resolution order and `~/CascadeProjects/ada-voice/.venv`
lacks pytest, so the inner drop tests cannot execute on this host — I
verified with a scratch venv (pytest 9.2.0) bridged into ada-voice's
site-packages via `.pth`, `ADA_PI` pointed at an in-worktree clone.
The gate itself runs on the merge-sweep host; if that host's ada-voice
venv has pytest the suite will go green there. If idc02 is ever meant
to run the gate, `pip install pytest` into the ada-voice staging venv is
the fix (noted in the job record followups).
