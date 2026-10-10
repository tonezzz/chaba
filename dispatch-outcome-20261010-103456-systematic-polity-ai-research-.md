# Dispatch outcome — Polity research sweep 3 (nest-polity-expansion)

Date: 2026-10-10 · Runner: idc03 · Branch: dispatch/20261010-103456-systematic-polity-ai-research-
Commit: b9558d8f (on the dispatch branch; not pushed)

## What was asked

Continue the systematic Polity-AI research program defined in
`docs/kb/nest-asher-polity-inspiration.md` under card
`nest-polity-expansion`. Remaining open questions after sweep 2: **submind
termination/reabsorption protocol** (do personas return and merge?) and
**Erebus's loyalty mechanics** for subsumed minds.

## What changed

- `docs/kb/nest-asher-polity-inspiration.md`
  - Both standing questions struck through as ANSWERED in the research
    program's open-questions list; next-sweep targets seeded (Penny Royal
    shard re-integration, Orlandine subpersona fate in *The Warship/The
    Human*, Owner-trilogy Committee structures, Brockle forensic method).
  - New section **"Research log — sweep 3 (2026-10-10)"** with 14 rows,
    each landing as candidate or rejected-with-reason per intake
    discipline. Notable: submind resubsumption/emancipation/self-
    termination (canon lifecycle), parent-held destruct codes,
    kill-channel capture (Erebus's leash became the weapon that decapitated
    its fleet), loyalty by provenance, subsumption-with-prejudice (erase
    personality, keep data), meld-is-dominance-not-fusion, war-drone
    survivor copying, hivemind schizophrenia, minds-as-programs virtuality,
    Quiet-War comms capture. One rejection: **self-edited moral code**
    (post-Quiet-War AIs may rewrite own values — the documented rogue
    pathway; Nest forbids lane-side objective mutation).
  - "Where this direction points next" extended with items 7–10 (persona
    lifecycle, kill-channel hygiene, control-plane independence, dominance
    audit); continuous-development tracks table +6 rows; Blegg canon nuance
    noted.
- `docs/ssot/jobs/nest/2026-10-10-polity-sweep-3.yml` — new jobs trail.
- `docs/ssot/kanban/cards/nest-polity-expansion.yml` — note updated with
  sweep-3 results; comms appended.

## Key findings (canonical answers)

**Submind termination/reabsorption:** yes, personas return and merge —
resubsumption is the designed default ("drones loaded with their own
subminds which could be easily resubsumed"; post-war doctrine after
independent war drones caused "many unfortunate incidents"). Emancipation
(subminds "buy or are given their own independence") and self-termination
("many simply turned themselves off") are the sanctioned alternatives.
Termination authority: parent-held destruct codes (Xanadu held codes for
its 206 sub-minds). Nest analog: fold-back as default persona lifecycle,
gated graduation to standing service, clean retirement, kill-path-before-
deploy.

**Erebus loyalty mechanics:** four mechanisms — forced subsumption (erase
personality/moral codes, keep data), periodically *checked* "favourites",
new captains cloned only from verified-loyal minds, and core-held destruct
programs. All insufficient: Randal loosed the kill programs and Polity
missiles rebroadcast them, decapitating the fleet. Loyalty could only be
enforced, not built in — and the enforcement channel was a single point
of failure. "Meld = dominance, not fusion" (Randal).

## Sources

Primary: *Line War* text (Erebus/captain/kill-program passages); Asher's
own Polity Encyclopaedia (nealasher.co.uk — war drones, Earth Central,
Quiet War, Golem morality, runcible AI, Blegg entries); *Polity Agent*
excerpt for the Blegg nuance.

## How to verify

- `docs/kb/nest-asher-polity-inspiration.md` → "Research log — sweep 3
  (2026-10-10)" and the struck-through open questions.
- `docs/ssot/jobs/nest/2026-10-10-polity-sweep-3.yml` — full trail.
- `git show b9558d8f` on this branch.
- Board card `nest-polity-expansion` has the sweep-3 comment.

## Notes

- No blockers, no questions raised, nothing in `$TASK_DIR/answers.jsonl`.
- `node` unavailable in this env so `ssot-validate-all.mjs` couldn't run;
  both edited YAMLs verified with `python3 yaml.safe_load` instead.
