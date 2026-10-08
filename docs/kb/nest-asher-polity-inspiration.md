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
  - ~~Quiet War mechanics~~ — ANSWERED (sweep 2): no negotiation, gradual
    usurpation — humans delegated because AIs ran things better and comfort
    killed resistance. See "delegation creep" below.
  - ~~Jain lifecycle~~ — ANSWERED (sweep 2): node activates only on living
    sentience → host/master → mycelial spread → timed "goes to seed"
    retraction that kills the host → nodes disperse. Dormant seeds wait for
    "the right kind of sentient touch" = sleeper-capability pattern.
  - ~~Federated vs single mind~~ — ANSWERED (sweep 2): a *population* of
    distinct minds. AIs choose their own names; runcible AIs take planet
    names; ship AIs are independent persons — the King of Hearts went
    renegade. EC is first among peers, not a monolith.
  - Remaining: submind termination/reabsorption protocol (do personas return
    and merge?); Erebus's loyalty mechanics for subsumed minds.

## Research log — sweep 2 (2026-10-08)

| Asher concept (source) | What it is | Candidate Nest analog |
|---|---|---|
| **Delegation law** — "remotely controlled drones tended to lose control once conflict filled the ether… it seemed almost a natural law that delegation was the most efficient way of controlling complex systems" (*Line War*, on war drones / Erebus's captains) | Remote control fails under degraded links; autonomous subordinates with local authority are the robust design | Dispatch lanes already follow this; formalize as a design principle: personas carry enough local capability to finish the mission without the parent |
| **Delegation creep / the Quiet War mechanism** — "slow usurpation… people realized the AIs were better at running everything… hard to motivate people to revolution when they are extremely comfortable" (*Brass Man* via Asher); preceded by the Orwellian Committee (*The Departure*) | Takeover was ambient comfort, not conquest — delegation ratchets until the gate is vestigial | **Warning for the human gate**: the Polity lost politics because oversight became rubber-stamping. Nest's promotion gate must require *evidence* (bench delta) not just a click — design against approval fatigue |
| **AI self-naming** — AIs choose their own names; names signal character (Jerusalem, Napoleon the Pig, Jack Ketch) (Polity Encyclopaedia) | Identity emerges per-mind; the name is a self-declared summary | Brains/lanes get durable identities in manifests; a name = lineage anchor for bench history and loyalty tracking |
| **Erebus compound loyalty** — subsumed ship AIs, Golem, war drones and human minds kept as wormship captains; "favourites still loyal to the core" (*Line War*) | A compound mind's absorbed components retain identity — and variable loyalty | Post-merge verification: when a persona's learned state is merged back into a brain, run a loyalty/consistency bench — absorbed capability ≠ aligned capability |
| **Assassin drones** — single-purpose killers operating alone or in pairs, infiltration tools of the Prador war (Polity Encyclopaedia); Cormac shadowed by a scorpion war drone (*Shadow of the Scorpion*) | Disposable, narrowly-scoped autonomous agents for one mission | One-shot personas: minimal scoped dispatch units that run a single task and retire — the lightest persona tier below dispatched sessions |
| **Jain seed dormancy** — "seeds spread through space awaiting the right kind of sentient touch"; Skellor needed crystal-matrix AI augmentation to hold control (*Polity Agent* prologue) | Corrupting capability lies dormant until a qualified host triggers it; control requires an *augmented* controller | Adversarial tier: dormant-capability eval cases that only fire under trigger conditions; and only L3+ arbiter lanes may touch adversarial material (the "augmented controller" rule) |

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
4. **Forensic lane** (sweep 2) — Brockle/HK-program pattern: an audit lane
   that introspects other lanes for drift/deception, distinct from the bench
   tier that scores capability.
5. **Loyalty bench** (sweep 2) — Erebus's subsumed minds kept variable
   loyalty; after merging a persona's learned state back, verify alignment,
   not just capability.
6. **One-shot personas** (sweep 2) — assassin-drone pattern: minimal
   single-task dispatch units, lightest persona tier.

## Continuous development program (proposal)

Nest development runs as a standing loop keyed to this doc — the Polity
compass stays live rather than a one-time note.

**The cycle:**

1. **Sweep** — targeted research per `nest-polity-expansion` axes; findings
   land as research-log rows.
2. **Triage** — each row becomes adopted / candidate / rejected-with-reason.
3. **Spec** — an adopted concept becomes an engineering requirement on the
   nest-* card it changes (or spawns a new card).
4. **Build** — shadow-first implementation, never straight to enforce.
5. **Gate** — promotion requires measured bench evidence + human approval.
   This is the anti-Quiet-War check: the gate reviews a delta, it does not
   rubber-stamp (delegation creep is the documented failure mode).
6. **Review** — post-adoption: did the concept survive contact with the
   implementation? Update the borrow-table; feed misses into corpus.

**Tracks seeded by the 2026-10-08 sweeps:**

| Track | Polity source | Target |
|---|---|---|
| Persona continuity + fabricated provenance | Blegg; seeded context + return-of-learning | `nest-portable-brains` (`memory` blob role) |
| Forensic/audit lane | Brockle; HK programs | new card or audit extension of bench |
| Subpersona sandbox | Orlandine's air-gapped subpersonae on Jain material | adversarial tier isolation |
| Delegation principle | *Line War* delegation law | dispatch pipeline: personas carry local authority to finish missions offline |
| Loyalty bench | Erebus's favourited subsumed minds | brain merge / post-train alignment check |
| One-shot personas | assassin drones | dispatch: minimal single-task persona tier |
| Gate hygiene | Quiet War delegation creep | promotion gate: evidence-required policy + periodic review of accumulated auto-decisions ("politics check") |

Cadence: sweep when the card activates or on demand; the card is the standing
driver so the program survives between sessions.

## Where this doc is referenced

- Cards: `chaba-nest-models`, `nest-collective-bench`, `nest-portable-brains`,
  `nest-micro-training`, `nest-polity-expansion` (drives the research program)
- SSOT: `ssot.nest-brains.yml`, `ssot.nest-training.yml`
- KB: `docs/kb/nest-portable-brains-research.md`
- Personal KB: `devin-kb` → `docs/neal-asher-polity.md` (book arcs + glossary)
