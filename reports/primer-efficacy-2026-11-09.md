# Primer efficacy measurement — 2026-11-09

Card: `primer-efficacy-measurement` (OPS-1270).
Analysis: `python3 scripts/board/primer_efficacy.py --md|--json`
(read-only; scans `docs/ssot/kanban/cards/**` + `dispatch-outcome-*.md`).

## Verdict: CONTRADICTED — the mechanism is not running

The claim under test: *"each failure makes the next dispatch smarter —
compounding quality."* The numbers show the compounding mechanism has
been effectively inert since 2026-10-11. Whether primed dispatches do
*better* is untestable: only 15 injections exist, all in a 40-hour
window, and the primer has produced zero since.

## The numbers

### Coverage — how often does the primer actually fire?

Dispatches are reconstructed from card comms. Two lanes exist:

| lane | marker | dispatches post-2026-10-09 | primed | coverage |
|---|---|---|---|---|
| kanban-dispatch | `dispatched <task> on <repo>` | 41 | 15 | **37%** |
| runner-agent | `started devin-task-<id> on <host> (dispatch)` | 893 | 0 | **0%** (no primer code path) |
| **all** | | **934** | **15** | **1.6%** |

- Line-count distribution: every recorded injection was the full 8 lines `{8: 15}`.
- **Last recorded injection: 2026-10-11 06:15** — one month before this
  scan. The kanban lane logged 15 injections over ~40h (10-09 19:35 →
  10-11 06:15), then nothing across the next 26 dispatches.
- Pre-era context: 213 dispatches before launch.

### Why it died — three independent kills

1. **Lane shift (structural, ~96% of traffic).** The runner-agent fleet
   was provisioned 2026-10-11 and now carries ~96% of dispatches.
   `runner-agent.py` never calls `lesson_primer` — that lane is primer-
   free by construction. Even a perfectly healthy primer only ever
   covered the kanban-dispatch lane.
2. **`lesson_primer.build()` crashes on the live corpus — fail-open
   hides it.** `_comms_candidates` does `(c or {}).get("text")` on every
   comms entry; `kraut-rain-events.yml` and `kraut-weather-bakeoff.yml`
   contain plain-string comms entries (`[context] …`, `[done] …`),
   so the build raises `AttributeError` on **every** dispatch.
   kanban-dispatch catches it warn-only ("primer is advisory"), leaving
   `LAST_PRIMER_LINES` empty — no KNOWN_PITFALLS block, no comms line.
   Reproduced live: `lp.build()` on this corpus today raises exactly
   that. With string entries tolerated it returns 8 lines — the crash is
   the sole current blocker.
   The same failure class probably explains the 10-13→10-16 gap on
   tony-dell (kanban-dispatch.timer ran the writer checkout, code
   present, zero lines logged): a bad comms entry that has since been
   normalized. Mechanism unproven for that window — but the observable
   signature is identical.
3. **Observability gap.** The `primer injected` comms is only written
   `if LAST_PRIMER_LINES:` — a 0-line or crashed primer is
   indistinguishable from `KANBAN_PRIMER=0` in the corpus. Dead-primer
   is invisible by design.

### Repeat-failure — did we fail on warned topics? (n=12)

For the 15 injections, 12 subsequent failure events exist in comms:

| class | count | warned | unwarned |
|---|---|---|---|
| test-gate | 10 | 6 | 4 |
| merge-held | 1 | 0 | 1 |
| merge-conflict | 1 | 1 | 0 |

**Warned rate 8/12 (67%)** — and the match is semantically real, not
just token overlap: `tests/test_calendar_providers.py` failed the merge
gate repeatedly across 10-09→10-11, and injected previews literally
carried prior cards' `test gate failed — merge held:
tests/test_calendar_providers.p` lines into the next dispatch
(spot-check: `ada-deploy-gate-tests` line 28→56 — injected with the
calendar-test lesson, then failed on exactly that test).

Caveat on interpretation: a "warned failure" means the signature
matched, not that the lesson was actionable. The calendar-test failures
were a broken shared gate — an environmental failure no dispatch could
avoid — not an agent repeating a mistake. Keyword signatures can't
distinguish "agent didn't learn" from "infra was down". The matching
itself works; lesson *quality/actionability* is the unmeasured part.

### Success comparison — raw numbers, confounds flagged

Card-level cohorts (era set by first dispatch):

| cohort | cards | verified | merged | mean attempts |
|---|---|---|---|---|
| pre-era (<10-09) | 159 | 38 (24%) | 52 (33%) | 1.0 |
| post-era primed | 13 | 13 (100%) | 10 (77%) | 1.08 |
| post-era unprimed | 17 | 15 (88%) | 14 (82%) | 1.25 |
| post-era runner lane | 411 | 276 (67%) | 312 (76%) | 1.2 |

Do **not** read causality into this:

- The `verified` stamp was introduced alongside the primer-era tooling —
  pre-era cards that merged fine were never stamped (merged 33% >
  verified 24%). `merged` is the fairer comparator: primed 77% ≈
  unprimed 82% ≈ runner 76%. No visible lift.
- Primed/unprimed split is not random: primed dispatches cluster on
  10-09→10-11 (fresh corpus, ada-pi card mix); unprimed are later cards.
- n=13 primed cards; a single card swings the rate ~8pt.
- Post-era verified rate (67–100%) vs pre-era (24%) reflects pipeline
  maturation (merge-sweep, auto-close, exit-evidence), not the primer.

### Self-seeding — is the corpus even growing?

`lessons:` block required in outcome docs since 10-09: present in
**22/311 post-launch docs (7%)**. The flywheel's input side is also
mostly not running — though the job-doc/comms/kb sources mean the
corpus still grows indirectly.

## A/B design — how to get a real answer

Prerequisites (the experiment is meaningless while the treatment doesn't
fire):

1. Fix `_comms_candidates` non-dict tolerance in `lesson_primer.py`.
2. Wire `lp.build()` into the runner-agent prompt path, or accept that
   the A/B only covers ~4% of traffic (too thin to measure).
3. Always log the injection line — `primer injected 0 lesson(s)
   (dead|disabled)` — so coverage is measurable and `KANBAN_PRIMER=0`
   is distinguishable from a corpus gap.

Assignment mechanism (in `kanban-dispatch.build_task`, before the
`KANBAN_PRIMER` check):

```python
import hashlib
arm_pct = int(os.environ.get("KANBAN_PRIMER_CTL_PCT", "0"))  # 0 = off
if arm_pct and int(hashlib.sha1(
        card["id"].encode()).hexdigest(), 16) % 100 < arm_pct:
    arm = "control"          # skip lp.build entirely
else:
    arm = "treatment"
```

- **Hash on `card_id`, not `task_id`** — stable across a card's retries,
  so a warned card can't flip arms mid-recovery (contamination).
  Deterministic → reproducible, no state file, survives restarts.
- Log `primer arm=<arm>` in the dispatch comms for unambiguous scoring.
- Run 50% control for ~4–6 weeks.

Primary metric: **mean attempts to verified** (re-dispatch count —
the direct "did it avoid the repeat" proxy), with verified-within-2-
attempts rate as the summary. Secondary: warned-class failure rate
(failures whose signature matches previously-injected lessons), and
time-to-merge. Guardrail: prompt token cost (~1.5k/dispatch, already
bounded by MAX_CHARS=5500).

Power sketch: post-era runner cohort verifies at ~67%; detecting a 10pt
lift at 50/50 needs roughly 350 dispatches/arm — at the current
~30 dispatches/day that's ~3–4 weeks, *if* the runner lane participates.

## Spot-checks performed

1. `ada-acl-explain` — comms 08:06 `dispatched …`, 08:06 `primer
   injected 8`, 08:36 `test gate failed` → counted primed + warned
   failure. YAML confirmed.
2. `ada-deploy-gate-tests` — injected previews include
   `[ada-acl-explain] test gate failed … calendar_providers`; card then
   failed the same test. Warned failure confirmed literally.
3. `line-file-doc-ingest` — `dispatched 20261013-100558` at comms line
   36, zero `primer injected` in file → counted dead dispatch. Confirmed.

## What would change the verdict

The compounding claim is *untested*, not disproven-in-principle: when
the primer fired (n=15), its keyword matching surfaced the right prior
failure 2/3 of the time. Fix the crash, cover the runner lane, make
zero-injection observable, then run the A/B above — that is the honest
path to a supported/inconclusive verdict. Today the claim fails on the
simplest ground possible: nothing is compounding.
