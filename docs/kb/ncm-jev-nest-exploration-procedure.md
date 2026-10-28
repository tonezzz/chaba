# NCM + JEV + Nest exploration procedure

Status: defined 2026-10-28

## First principle

NCM and JEV solve different problems:

- **NCM** is a generation architecture: a frozen/coarse-to-fine
  multiscale tokenizer plus a level-parallel next-concept generator.
- **JEV** is a decision plane: routing, choice, confirmation gates, and
  escalation.
- **Nest** is the execution plane: packs, workers, artifacts, retries, and
  durable publication.

The useful mix is therefore:

```text
task -> JEV chooses route
     -> Nest runs NCM / AR / LLM candidate workers in parallel
     -> verifier scores candidates
     -> JEV or deterministic policy selects/escalates
     -> artifact + metrics + Education
```

Do not describe this as “JEV inside NCM” unless a later research experiment
actually changes the NCM model. Start with orchestration around the model.

## Experiment ladder

### P0 — contract and replay, no GPU

Use the existing Sudoku and Thai fixtures plus a fixed set of short prompts.
Implement a common worker contract:

```json
{
  "task_id": "...",
  "input": "...",
  "candidate": "ncm|ar|llm",
  "seed": 42,
  "output": "...",
  "latency_ms": 0,
  "tokens_in": 0,
  "tokens_out": 0,
  "verdict": "pass|fail|escalate",
  "artifact_ref": "..."
}
```

Replay the same task through:

1. small Thai AR baseline;
2. NCM generator;
3. JEV route-only policy;
4. JEV route + NCM/AR candidates;
5. JEV route + parallel candidates + verifier.

The P0 gate is deterministic schema validity and reproducible seed/output
capture. No production routing changes.

### P1 — NCM Thai toy on Colab

Run the already implemented NCM tokenizer and generator on Colab GPU:

- frozen SentencePiece tokenizer;
- NCM tokenizer training;
- frozen VQ code encoding;
- NCM generator training;
- small Thai AR baseline;
- held-out generation and PPL/entropy/speed report.

Stop if the tokenizer reconstruction gate or data quality gate fails. Persist
checkpoints and reports to Drive; do not train on a live worker checkout.

### P2 — JEV replay benchmark

Give JEV only metadata/features and candidate summaries, not hidden labels.
Measure route accuracy, gate precision/recall, abstention, escalation, and
decision latency. Compare:

- deterministic rules;
- jevos;
- jev-student where it is in-domain;
- the best available LLM judge;
- human labels on a held-out set.

JEV is not allowed to declare success from its own confidence. The verifier
owns the outcome.

### P3 — mixed candidate benchmark

For each task, run the cheapest predicted candidate first or run a bounded
parallel set when latency is more important than cost. Compare:

```text
AR only
NCM only
JEV -> AR/NCM
parallel AR+NCM -> deterministic ranker
parallel AR+NCM -> LLM judge
```

Measure:

- Thai held-out PPL and generation entropy;
- validity/well-formed rate;
- semantic/task score;
- tokens/sec and time-to-first-output;
- total wall time;
- GPU/RAM/disk;
- token/API cost;
- verifier pass rate;
- escalation and human intervention rate;
- quality per dollar and quality per second.

### P4 — shadow production

Run the mixed route beside the existing lane without changing user-visible
output. Store paired results and judge them with frozen labels. Promote only
if the mixed route improves a declared metric without exceeding cost,
latency, safety, or maintenance budgets.

### P5 — production promotion

Promotion requires:

- three repeated benchmark runs;
- held-out data not used for routing;
- no secret or private-input leakage;
- deterministic fallback;
- artifact and audit publication;
- rollback route;
- human approval for user-facing or paid changes.

## Standard research/benchmark packet

Every experiment publishes these files:

```text
manifest.json       # models, revisions, data hashes, seeds, hardware
results.json        # one row per task/candidate
report.md            # method, metrics, failures, verdict
verdict.json         # adopt|watch|reject + confidence
education.html       # durable explanation and links
```

The same packet is valid as a Nest pack, a DevNest task, or a local replay.
Parallel workers may produce candidate results, but one reducer owns the
verdict and all writes to Education/board/news.

## Adoption rules

- **Adopt** only when a verifier-backed metric improves against the baseline.
- **Watch** when the idea is technically promising but data or hardware is
  missing.
- **Reject** when it adds complexity without measurable quality/speed gain.
- **Escalate** when confidence is below threshold or candidates disagree.
- Never replace the current Thai/LLM lane solely because NCM is novel.

The current honest prior is: NCM is a research generator with a working
Sudoku validation and a Thai pipeline ready for GPU training; JEV is already
useful as a decision plane but has known out-of-domain limits. The first
valuable result is therefore a replay/benchmark, not a production route.
