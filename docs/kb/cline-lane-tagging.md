# Cline lane — card tagging convention

The `cline` intake lane (`scripts/colab/packs/cline-kanban-nest-bridge/intake.py`,
timer on con01) turns backlog cards into disposable Cline drafting tasks.
Verified 2026-10-29: **the quality of the draft is decided by what the spec
contains, not by the model.** qwen2.5:7b cannot derive system truth it cannot
see — it will invent plausible enums, endpoints, and paths — but it uses real
facts verbatim when they are in the prompt.

## Rule: spec must contain the truth

A `cline`-tagged card should paste the relevant facts into `spec:` — real enum
values, endpoint names, file paths, field lists, write-owner rules — whatever
the deliverable must be accurate about. Derivation cards produce confident
fiction; fact-carrying cards produce honest drafts.

Measured: `job-package-status-storage-sop` — first run invented a fake status
taxonomy (`InPlanning`/`Finished`); same card retried with `JOB_STATUSES`
+ `/job` upsert + `JOB_META_KEYS` pasted into spec produced a PASS draft.

## Opt-in

```yaml
tags: [cline]
cline:
  deliverable: file.md      # required — the artifact that must exist
  sentinel: TOKEN           # optional — must appear in the file
  model: ollama/qwen2.5:7b  # optional — provider/model from the allowlist
```
or spec-line markers `cline-deliverable:`/`cline-sentinel:`/`cline-model:`.

## Shape

- Good cards: procedures, runbooks, checklists, standards — documents whose
  content the spec can fully carry.
- Bad cards: anything needing repo reads, live infra, or "figure out how X
  works" — route those to a lane with repository access.
- Output is always draft-for-review. The card moves to `review`; a human reads
  the patch (`out/intake/<job_key>/task.patch`) and merges by applying it — or
  rejects. Cline never commits, pushes, or opens PRs.

## Known model behavior (qwen2.5:7b)

- ~50% of sessions narrate the file as chat text instead of calling the editor
  tool — the bridge retries once with a fresh task.
- Output is structurally correct but thin when the spec is thin.
- `openrouter/or-free-*` lanes flap (pool saturation, upstream key errors) —
  usable opportunistically, not as a default.
