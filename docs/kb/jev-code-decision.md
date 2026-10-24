# Jev code-decision layer — design for review (OPS-0825)

Tony's idea (2026-10-24): *"maybe jev can help us make a decision if we
should use for, while or do loop. or which template of code,
replacement, modifications we should apply to the original code or even
choose from library."*

This doc extracts the useful parts, splits what Jev can and cannot do,
and shapes it as a nest-style mix-and-match system.

---

## 1. The idea, decomposed

| sub-idea | can Jev do it? | why |
|---|---|---|
| choose for / while / do loop | **partially — as a router, not a writer** | Jev returns a *choice* over candidates you provide. It cannot invent the loop; it can score "which of these N constructs fits this task/constraint" |
| choose code template / pattern | **yes — its best shape** | template choice is classification over a known set (the repo's established patterns) — exactly Choice's envelope |
| choose replacement / modification | **yes, as a gate** | Noul per candidate diff: "does this minimal change satisfy the requirement?", "does it preserve semantics?" — the review-gate pattern |
| choose a library | **yes** | the scout decision (like scout-thai-tts): given candidates + criteria (maintenance, license, size, familiarity), Jev scores them |
| *write* the loop/template/diff | **no** | Jev generates no text — the LLM (agent) writes; Jev decides around it |

**The rule from the ecosystem: let Jev route/verify/guard; let the LLM
write inside the boundaries your code enforces.**

## 2. The system (nest-style mix-and-match)

Three pieces, each reusing an existing nest pattern:

### 2.1 `code-decision` service (the decision endpoint)
A small service (or a board-api-style door op) that answers one question
shape: `{state, questions}` → typed answers.

```
state: {
  task: "refactor this loop to be idiomatic",
  code: "<the snippet>",
  constraints: ["prefer clarity", "repo uses list comprehensions", "perf non-critical"],
  candidates: {
    "for-loop": "for x in items: ...",
    "comprehension": "[f(x) for x in items]",
    "while": "i=0; while i < len(items): ...",
  }
}
questions:
  construct: Choice(instructions="which construct fits best?",
                    criteria={...candidates...})
  semantics: Noul("does the chosen construct preserve the original semantics?")
  convention: Noul("does it match the repo's established style?")
```

Backend: **real Jev API** (`api.typesafe.ai/v1/systemone`, $0.042/MTok,
~100 ms — needs an API key; no-waitlist via Vercel AI Gateway or
Cloudflare Workers AI) with **jev-student noul fallback** for the
Noul gates only (our local student: noul 10/10 proven, choice broken).

### 2.2 The agent skill (how the agent uses it)
Before applying a code change, the agent calls the service:

1. propose candidates (the construct/template/library options it would
   actually write/use)
2. `Choice` → winner
3. `Noul` gates → if semantics/convention fail, re-propose
4. apply the winner, record the verdict (for the eval bench)

This is the **stagnation-gate fusion** (BEN-0824): the same call shape
gates agent loops (CONTINUE/REPLAN/HALT).

### 2.3 The eval pack (`jev-code-eval`)
The honest question: *does Jev's construct-choice match a human's?*
A bench over a small corpus of real changes from this repo:
- take N real commits/diffs from chaba history
- for each: state = {task, before-code, candidates} with the ACTUAL
  choice the human made as ground truth
- run Jev's Choice → score accuracy vs ground truth
- same corpus, three backends: real Jev / jev-student / (optional) LLM
  JSON — the comparison table (like jev-bench's structure)

This decides whether the layer is production-ready or just a gate.

## 3. Phased rollout

| phase | what | gate |
|---|---|---|
| 1 | the `code-decision` service + agent skill (noul-gates first — proven) | card OPS-0825 |
| 2 | `jev-code-eval` bench (construct-choice accuracy vs real commits) | card BEN-0825-ish |
| 3 | stagnation gate wired into the runner loops | card BEN-0824 |
| 4 | library-choice as a scout pack (reuse scout-thai-tts shape) | after the eval |

## 4. Honest limits (from our own 2026-10-24 test)

- **jev-student**: noul production-quality; choice broken; no
  generalization — routing/grading needs the real Jev API
- Jev's code judgments are **rubric-bound**: the criteria quality
  decides the decision quality (garbage-in)
- Jev replaces brittle regex/JSON-parsing decisions — it never
  replaces the LLM's writing or the human's review