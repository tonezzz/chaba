# Chaba Nest — concept source: Neal Asher's Polity

Status: active guidance, 2026-10-08. Adopted by Tony as the conceptual
direction for Chaba Nest. Personal copy of the reading notes lives in
`devin-kb` (`docs/neal-asher-polity.md`).

## Attribution

Chaba Nest borrows its organizing ideas from **Neal Asher's Polity novel
series** (the "Polity universe" — Agent Cormac, Spatterjay, Transformation,
Rise of the Jain arcs). This is a deliberate, credit-where-due borrowing:
Asher worked out a coherent model of *hierarchical machine intelligence* and
we adopt his vocabulary and architecture intuitions as our compass. When we
say a Nest piece "is the EC persona pattern" we mean: the concept comes from
Asher; the implementation is ours.

Umbrella idea borrowed: the **AI hegemony** — a civilization run by a
hierarchy of minds (post-Quiet-War Polity). Nest is our small hegemony:
many narrow minds, coordinated, kept on leashes.

## What we borrow, and where it lives

| Asher concept | Nest implementation | Where |
|---|---|---|
| Earth Central / AI hegemony | Chaba orchestration layer; L0–L3 capability tiers | ada-pi `tests/bench/topologies.yml` |
| Lesser persona for a job | Dispatch sessions; L0 rules / L1 student specialists | `ssot.jobs`, dispatch pipeline |
| Tuned persona + telemetry leash | Shadow-deploy posture: a scorer observes & reports, never enforces until promoted; epoch fencing on brains | `ssot.nest-training.yml`, `ssot.nest-brains.yml` |
| Reprogram lesser minds at will | `nest-train-loop.py` train→bench→promote; promotion gated by a human-approved board request | `ssot.nest-training.yml` |
| Persona transported / respawned | Portable brains: versioned bundles, manifest, epoch fencing, `.nest-brain-state` lineage | `ssot.nest-brains.yml` |
| Compound intelligence (Penny Royal) | Collective-intelligence topologies: series/parallel/router/verifier cascades | card `nest-collective-bench`, `impl:chain` executor |
| Jain tech (corrupting supertech) | Adversarial bench tier; human-gated promotion is the anti-Jain safeguard | `tests/bench/suites.yml` |
| Runcible / U-space fabric | Tailnet + gdrive transport that makes the hegemony reachable | `ssot.nest-brains.yml` brain store |
| Black AI (rogue mind) | Split-brain respawn failure mode; fencing + manual respawn authority | `ssot.nest-brains.yml` policy_defaults |
| Haiman (human-AI symbiote) | Tony-in-the-gate: every promotion/deploy needs human approval; Tony+agent sessions | card promotion gates |

## Research log — new concepts mined (2026-10-08)

Findings from the first research sweep (author interviews, novel text,
secondary scholarship). Each row is a *candidate* — it lands in the table
above only when we adopt it.

| Asher concept (source) | What it is | Candidate Nest analog |
|---|---|---|
| **Subpersona sandbox** — Orlandine runs isolated "subpersonae" to control Jain-contaminated systems (*The Soldier*/*Rise of the Jain*) | A haiman spins off a compartmented lesser mind to handle dangerous material, on an isolated machine | Adversarial-tier corpus / untrusted inputs handled by a sandboxed subpersona lane that never shares memory with production tiers |
| **Fabricated persona provenance** — EC built Horace Blegg's mind 30s after coming online, gave him a manufactured history, ran him in Golem chassis then human substrate: "a probe into human society" (*Polity Agent*) | A dispatched persona carries a curated backstory and *engineered continuity* — EC: "he required continuity to give himself the necessary perspective" | Dispatch personas with seeded context bundles; persona continuity is a designed feature, not incidental memory |
| **HK programs / forensic read** — Jerusalem sends HK programs into the rogue ship King of Hearts, "riffling through his systems, inspecting memories," one-sided link (*Polity Agent*) | Greater mind directly inspects a lesser mind's internals — read access, not just telemetry | Audit lane: arbiter-tier introspection of lane logs/weights/state — bench "HK pass" on candidates before promotion |
| **The Brockle — forensic AI** — dedicated hunter-inspector AI pursuing Penny Royal (*Transformation*) | A specialist mind whose sole job is auditing other minds | `nest-forensic` concept: a watchdog lane scoring other lanes for drift/deception — distinct from the bench tier |
| **Swarm AI** — Penny Royal is "fractured into a swarm AI," later seeking reintegration (Asher's own site); Sverl becomes a tri-part prador-human-AI compound | Compound intelligence can be a single mind deliberately fragmenting into cooperating shards | Shard-and-merge topology: split a model's context/weights into parallel shards, merge verdicts — a new cascade pattern for `nest-collective-bench` |
| **Deal-with-the-devil outputs** — Penny Royal grants transformations that always cost (*Dark Intelligence*) | A powerful misaligned subsystem produces exactly-what-you-asked-but-wrong outputs | Verifier tier rationale: capable-but-untrusted L2 output gated by an L3 check; bench cases that are "technically correct, actually harmful" |
| **Skaidon hazard** — Iverus Skaidon mind-linked to the Craystein AI to invent U-space; "his mind blew like a fuse" (Asher, Pan Macmillan intro) | Full-bandwidth human-AI coupling destroys the human | Human gate as *throttle*, not just veto: bounded-bandwidth review (cards, dashboards, summaries) instead of raw model telemetry |
| **Polity-without-politics** — academic analysis of AI rule vs democracy (*Polity Without Politics?*, J. Evol. & Tech. 2015) | External scholarship on the hegemony model: AI rule improves outcomes but removes politics | Framing for the human-gate essay: Nest keeps "politics" (Tony's veto) precisely where Polity removed it |

## Research program — systematic expansion

Goal: keep mining the Polity corpus for concepts we don't yet have, and land
each in this doc as adopted / candidate / rejected-with-reason. Driven by card
`nest-polity-expansion`.

Axes of inquiry (each is a research question, not a vibe):

1. **Canon, per-arc** — re-extract AI mechanics per book rather than memory:
   Gridlinked→Line War (EC, Blegg, runcible AIs, HK programs), Spatterjay
   (post-hegemony edge worlds), Transformation (Penny Royal, Brockle, swarm
   minds), Rise of the Jain (Orlandine's subpersonae, haiman limits, Jain
   lifecycle), Owner trilogy (pre-Quiet-War Committee → how the hegemony
   *emerged*).
2. **Author intent** — interviews (B&N, SciFiNow, SFX, infinityplus), Asher's
   blog/newsletter: why he chose benevolent AI rule; what he considers the
   failure modes.
3. **Secondary scholarship** — e.g. *Polity Without Politics?* (2015); fan
   wiki consistency checks.
4. **Engineering translation** — for each adopted concept, the real-world
   analog must be named (MoE routing, sandboxed eval lanes, audit/observer
   models, shard-merge inference, human-in-the-loop throttles).

Intake discipline:

- Sources logged with book/interview citation; mark uncertain attributions
  "(unverified)" until confirmed in text.
- Every new concept lands in exactly one state: adopted (borrow-table row),
  candidate (research-log row with proposed analog), or rejected (recorded
  with reason — e.g., time-travel: no analog, don't force it).
- Open questions we don't have yet → next sweep targets:
  - How does Asher depict submind *termination/reabsorption* (do personas
    return? merging protocol)?
  - The Quiet War mechanics — how the handover was negotiated (informs our
    promotion-gate design).
  - Jain tech lifecycle detail — what exactly makes it corrupt (informs the
    adversarial tier).
  - EC's relationship to other planetary/run-cible AIs — federated peers or
    extensions of one mind? (Informs whether Nest lanes are one mind's facets
    or a population.)

## One deliberate divergence

In the Polity, EC reprograms subminds unilaterally. In Nest, the loop may
train and bench a replacement candidate but **promotion is human-gated**
(board request → approval → shadow → promote). The parent mind proposes,
Tony disposes. That gate is the anti-Jain property — nothing external gets
to rewrite the minds unchecked.

## Where this direction points next

1. **Persona continuity** — dispatched personas start amnesiac today; brain
   `memory` blob role exists but is unused. "Submind returns with what it
   learned" is the gap: scoped memory slices that flow back to the parent.
2. **Arbiter-label pass** — open question in `ssot.nest-training.yml`:
   L2/L3 adjudicating diverged corpus rows = the greater mind correcting
   the lesser one's labels. Turns retrain-same-labels into
   learn-from-divergence.
3. **Learned router** — the hegemony's allocation decision, learned from
   bench corpus rather than a hand-set feature router.

## Where this doc is referenced

- Cards: `chaba-nest-models`, `nest-collective-bench`, `nest-portable-brains`,
  `nest-micro-training`, `nest-polity-expansion` (drives the research program)
- SSOT: `ssot.nest-brains.yml`, `ssot.nest-training.yml`
- KB: `docs/kb/nest-portable-brains-research.md`
- Personal KB: `devin-kb` → `docs/neal-asher-polity.md` (book arcs + glossary)
