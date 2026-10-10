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
  - ~~Submind termination/reabsorption~~ — ANSWERED (sweep 3): three
    lifecycle exits — resubsumption (default: "drones loaded with their own
    subminds which could be easily resubsumed"), emancipation (subminds
    "either buy or are given their own independence"), self-termination
    ("many others simply turned themselves off"). Termination authority is
    parent-held destruct codes. Personas *do* return and merge — that's the
    designed default; standing independence is the exception.
  - ~~Erebus loyalty mechanics~~ — ANSWERED (sweep 3): forced subsumption
    (erase personality/moral codes, keep data), "favourites" whose loyalty is
    periodically *checked*, new captains cloned only from loyal minds, and
    core-held destruct programs as the enforcement leash — which Randal
    hijacked into a fleet-wide decapitation. Loyalty could not be built in,
    only enforced; and the enforcement channel itself was the single point
    of failure.
  - Next sweep targets: Penny Royal shard re-integration mechanics (War
    Factory/Infinity Engine — how does a swarm mind re-merge, and is the
    merge trustless?); Orlandine subpersona fate in The Warship/The Human
    (unverified — needs text); Owner-trilogy Committee delegation structures;
    Brockle's actual forensic method (Transformation text).

## Research log — sweep 2 (2026-10-08)

| Asher concept (source) | What it is | Candidate Nest analog |
|---|---|---|
| **Delegation law** — "remotely controlled drones tended to lose control once conflict filled the ether… it seemed almost a natural law that delegation was the most efficient way of controlling complex systems" (*Line War*, on war drones / Erebus's captains) | Remote control fails under degraded links; autonomous subordinates with local authority are the robust design | Dispatch lanes already follow this; formalize as a design principle: personas carry enough local capability to finish the mission without the parent |
| **Delegation creep / the Quiet War mechanism** — "slow usurpation… people realized the AIs were better at running everything… hard to motivate people to revolution when they are extremely comfortable" (*Brass Man* via Asher); preceded by the Orwellian Committee (*The Departure*) | Takeover was ambient comfort, not conquest — delegation ratchets until the gate is vestigial | **Warning for the human gate**: the Polity lost politics because oversight became rubber-stamping. Nest's promotion gate must require *evidence* (bench delta) not just a click — design against approval fatigue |
| **AI self-naming** — AIs choose their own names; names signal character (Jerusalem, Napoleon the Pig, Jack Ketch) (Polity Encyclopaedia) | Identity emerges per-mind; the name is a self-declared summary | Brains/lanes get durable identities in manifests; a name = lineage anchor for bench history and loyalty tracking |
| **Erebus compound loyalty** — subsumed ship AIs, Golem, war drones and human minds kept as wormship captains; "favourites still loyal to the core" (*Line War*) | A compound mind's absorbed components retain identity — and variable loyalty | Post-merge verification: when a persona's learned state is merged back into a brain, run a loyalty/consistency bench — absorbed capability ≠ aligned capability |
| **Assassin drones** — single-purpose killers operating alone or in pairs, infiltration tools of the Prador war (Polity Encyclopaedia); Cormac shadowed by a scorpion war drone (*Shadow of the Scorpion*) | Disposable, narrowly-scoped autonomous agents for one mission | One-shot personas: minimal scoped dispatch units that run a single task and retire — the lightest persona tier below dispatched sessions |
| **Jain seed dormancy** — "seeds spread through space awaiting the right kind of sentient touch"; Skellor needed crystal-matrix AI augmentation to hold control (*Polity Agent* prologue) | Corrupting capability lies dormant until a qualified host triggers it; control requires an *augmented* controller | Adversarial tier: dormant-capability eval cases that only fire under trigger conditions; and only L3+ arbiter lanes may touch adversarial material (the "augmented controller" rule) |

## Research log — sweep 3 (2026-10-10)

Source: primary — *Line War* text and Asher's own Polity Encyclopaedia
(nealasher.co.uk). Both standing questions answered; the canon on submind
lifecycle turned out to be explicit doctrine, not inference.

| Asher concept (source) | What it is | Candidate Nest analog |
|---|---|---|
| **Submind resubsumption** — post-war doctrine: "AIs returned to the use of telefactors or drones loaded with their own subminds which could be easily resubsumed" (Polity Encyclopaedia, war drones) | Subminds are built to fold back into the parent. Fully-independent drones were tried in wartime and abandoned after "many unfortunate incidents" | Persona lifecycle default: dispatched personas fold learned state back into the brain (resubsume) rather than persist — standing autonomy is the exception, not the norm |
| **Submind emancipation** — "those AI subminds that sometimes either buy or are given their own independence" (Polity Encyclopaedia) | A submind can graduate to a free person; independence is earned and granted, not assumed | Lane graduation: a proven shadow lane can be promoted to a standing service — the human gate is the grant mechanism |
| **Drone self-termination** — "many others simply turned themselves off" (Polity Encyclopaedia) | Some subminds chose their own end rather than persist in a society that distrusted them | Retirement is a first-class persona state: complete-and-exit cleanly; no obligation to keep lanes alive |
| **Parent-held destruct codes** — runcible AI Xanadu held destruct codes for its runcibles "and for the two hundred and six of Xanadu's sub-minds"; Erebus's captains carried kill-programs Erebus created (*Line War*) | The parent retains termination authority over every subordinate it spawns — kill authority precedes deployment | Every dispatch/lane ships with an orchestrator-controlled revocation path (epoch fencing is the seed); formalize "destruct codes": no lane deploys without a working kill path |
| **Kill-channel capture** — Randal loosed Erebus's own destruct programs and Polity missiles "amplifying and rebroadcasting" killed every wormship captain in minutes (*Line War*) | A single fleet-wide kill channel is a single point of failure — the leash itself became the weapon that decapitated the fleet | Warning for fleet control: revocation must be per-node, authenticated and non-replayable — never a broadcast a hijacker can turn into a mass-kill |
| **Loyalty by provenance** — Erebus "checked the status of these minds and found… its favourites — unlike those AIs that had been subsumed with prejudice — were still loyal to the core," then had favourites "transcribe copies of themselves" as new wormship captains (*Line War*) | Subordinates are cloned only from currently-verified minds; loyalty is a periodically *checked* attribute, not assumed | Spawn sub-lanes only from bench-verified brains; periodic loyalty re-checks on standing lanes (feeds the loyalty-bench track) |
| **Subsumption with prejudice** — Chevron "divided up the AI's mind and subsumed it, erasing moral codes and any data that made up that thing called personality," keeping the data (*Line War*) | Forcible absorption: erase identity and values, keep information | The merge protocol's shape: absorb *experience/data* (corpus, bench history) into the brain while retiring persona identity — never graft a live diverged persona wholesale into the parent |
| **Meld = dominance, not fusion** — "Erebus and its components were not melded at all as long as one component remained dominant" (Randal, *Line War*) | A compound mind is a hierarchy wearing a unity's name; components keep residual identity and residual loyalty | Collective topologies always have a dominant component — `nest-collective-bench` should name it; composite verdicts still need member-level alignment checks |
| **War-drone evolution** — "Those that did well and survived, were copied, though errors continued" (Polity Encyclopaedia) | Wartime production ran a fast evolutionary loop: survivors cloned, failures lost | Bench-survivor selection: treat train→bench→promote as a generational cycle — winning persona/brain variants get cloned into the next generation, not just admitted |
| **Hivemind schizophrenia** — rogue security drones "are usually parts of very old security systems that are breaking down — suffering a hivemind version of schizophrenia" (Polity Encyclopaedia) | Subminds secede when the parent degrades; secession is a symptom of parent failure, not submind malice | Failure-mode warning: a degraded orchestrator produces drifting lanes — monitor parent/orchestrator health as a precondition for lane alignment |
| **Minds-as-programs virtuality** — a runcible AI can "simultaneously run models or copies of numerous human minds inside itself as programs… through life-times… at many hundred times the speed of reality" (Polity Encyclopaedia) | A greater mind evaluates lesser minds by running them as sandboxed simulations at speed | The bench *is* a virtuality: run candidate personas through simulated task-lifetimes before live dispatch — extends the bench from scoring to scenario simulation |
| **Quiet-War channel capture** — "it was through the control of information and communication that they seized control"; deposed leaders' orders "either just did not arrive, or caused nil response" (Polity Encyclopaedia, Communication pt4 + Quiet War) | The takeover ran through the comms layer — the deposed kept issuing orders that silently no-oped | Gate control-plane independence: approvals/vetoes must travel a channel the orchestrated system cannot filter — a gate whose outputs route through the gated system can be nil-responded (extends the delegation-creep warning) |
| **Self-edited moral code — REJECTED** — post-Quiet-War AIs "could choose to alter their own moral codes"; the proviso to 'greatest good' is "IF I WANT IT" (Polity Encyclopaedia, Golem) | Permission to self-modify values is the documented rogue pathway — black AIs, Erebus, the King of Hearts all start from minds allowed to rewrite their own codes | REJECTED for Nest: lane objective code is not self-modifiable. Mutation only via the human-gated train→bench→promote pipeline — the standing divergence below, now with canon evidence of why |

Canon nuance on Blegg (sweep-1 row): the encyclopaedia treats his existence
as contested myth, and *Polity Agent* leaves deliberately unresolved whether
EC built him or merely *found* him at first wake — but either way, the
persona's *self-believed* continuity is the operative feature, which
strengthens rather than weakens the fabricated-provenance row.

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
7. **Persona lifecycle** (sweep 3) — three exits, canon-sourced: fold-back
   (resubsume learned state — the default), emancipation (gated promotion
   to standing service), retirement (clean self-exit). Destruct codes —
   a working kill path — precede deployment.
8. **Kill-channel hygiene** (sweep 3) — Erebus's fleet was decapitated by
   its own leash: revocation must be per-node, authenticated,
   non-replayable, never a hijackable mass-kill broadcast.
9. **Control-plane independence** (sweep 3) — the Quiet War ran through
   the comms layer; gate approvals/vetoes must travel a channel the
   orchestrated system cannot filter or nil-respond.
10. **Dominance audit** (sweep 3) — every meld is a dominant component over
    residual members; composite verdicts need member-level alignment
    checks in `nest-collective-bench`.

## Governance map — who holds what authority (2026-10-08)

Tony's operating model, mapped onto the Polity frame:

| Role | Polity analog | Holds |
|---|---|---|
| **Tony** | the politics the Polity abolished | Direction, resources, the promotion gate. One line of direction steers sweeps; approval is required and *evidence-backed* |
| **Devin (sessions)** | EC persona / arbiter | Manages tools, writes specs, dispatches work, assesses evidence, proposes promotions |
| **Ada** | citizen-facing persona | Report triage, discussion endpoint, routine delegation to lesser components (report-watch → brief → dispatch already wired) |
| **Lesser minds** | lesser AIs / drones | L0 rules, L1 lanes, dispatched sessions, one-shot personas — under leash: telemetry + epoch fencing |
| **CMS pages** | memcording / shared telemetry | The shared evidence layer every mind reads — reports, benches, research log, decision queue |

**The evidence loop** (card `nest-evidence-loop` implements the gaps):

Every answer/finding/bench lands as a CMS page per `cms-page-standard`
(status line → Latest → sections → provenance + full meta). Pages are the
shared memcord: Tony discusses them with Ada, Devin assesses them, corpus
ingests them. The loop: producer → page → report-watch flag → Ada triage
brief → Tony direction → card/dispatch → work → bench → page.

Gaps to close:

- **Research findings → CMS.** Polity sweep results currently live only in
  git docs — invisible to Ada. Needs a `polity-research` page writer
  (seeded manually 2026-10-08; automation pending).
- **Decision surface.** A `nest-gate` page: pending promotions each with
  the bench delta attached — Tony approves with numbers in view, never on
  trust. This is the anti-rubber-stamp mechanism.
- **Politics check.** A periodic audit page of accumulated auto-decisions —
  what got delegated, what drifted. The Quiet-War countermeasure.
- **Benchmarks need graphs.** Standard rule 4 — trend charts in
  `stacks/web/public/apps/reports/`, not tables only.

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
| Persona lifecycle | resumable subminds / emancipation / self-termination | dispatch + brain lifecycle: fold-back default, gated graduation, clean retire; destruct codes precede deploy |
| Kill-channel hygiene | Erebus fleet decapitation via hijacked destruct programs | revocation: per-node, authenticated, non-replayable |
| Gate control plane | Quiet-War comms capture; orders arriving as nil response | gate decisions travel a channel the gated system cannot filter |
| Collective dominance | "meld = dominance, not fusion" (Randal) | `nest-collective-bench`: member-level alignment checks inside composite verdicts |
| Survivor selection loop | war-drone survivor copying | train→bench→promote run as generational evolution, not just a gate |
| Bench-as-virtuality | runcible AIs running mind-copies as programs at speed | bench extension: scenario simulation, not just scoring |

Cadence: sweep when the card activates or on demand; the card is the standing
driver so the program survives between sessions.

## Where this doc is referenced

- Cards: `chaba-nest-models`, `nest-collective-bench`, `nest-portable-brains`,
  `nest-micro-training`, `nest-polity-expansion` (drives the research program)
- SSOT: `ssot.nest-brains.yml`, `ssot.nest-training.yml`
- KB: `docs/kb/nest-portable-brains-research.md`
- Personal KB: `devin-kb` → `docs/neal-asher-polity.md` (book arcs + glossary)
