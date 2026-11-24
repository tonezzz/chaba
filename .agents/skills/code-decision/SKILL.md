---
name: code-decision
description: Jev decision door for code changes — call before applying a change that involves a construct/template/library/replacement choice. Jev routes and gates; the agent still writes.
allowed-tools:
  - exec
  - read
  - grep
  - find_file_by_name
triggers:
  - model
---

# code-decision — Jev gate before applying a code change

Card: `jev-code-decision-layer-construct-templa-77e184` (OPS-0825).
Design: `docs/kb/jev-code-decision.md`. Service:
`scripts/jev/code-decision.py` (CLI + `POST /decide` via `--serve`).

**Jev decides around the change; the agent writes it.** Use this skill
when you are about to apply a change that involves a real choice:

- loop/construct selection (for vs while vs comprehension vs map)
- which template/pattern to follow (repo idiom vs novel approach)
- which library/util to use (stdlib vs dep, which helper)
- which of several candidate diffs/replacements to apply

Skip it for mechanical edits (renames, typo fixes, single obvious
changes) — the door costs a backend call and adds nothing there.

## How to call

Pipe JSON on stdin (preferred — no quoting pain):

```bash
python3 scripts/jev/code-decision.py <<'EOF'
{"task": "what the change must accomplish",
 "code": "the snippet/context being changed (or the proposed diff)",
 "candidates": {"name": "rubric description or snippet", ...},
 "constraints": ["repo uses X", "stdlib only", "perf non-critical"],
 "assume_winner": "your own pick — used for gates if choice is down"}
EOF
```

Or flags: `--task --code-file --candidates file.json --constraints a,b
--assume-winner name`. Or HTTP: `code-decision.py --serve --port 8890`
(8790 is already a voice service on tony-omen), `POST /decide` with the
same body. `GET /health` shows backend reachability.

## Building good candidates (the rubric IS the decision)

- 2–6 candidates max; Jev picks over a shortlist, never invents options.
- Each candidate value is a **rubric**: what it is + why it fits/doesn't.
  "comprehension: `[f(x) for x in xs]` — repo's pervasive idiom for
  transform-collect, one line, lazy-friendly" beats "comprehension".
- Include the honest alternatives, including "do nothing / keep as-is"
  when that's a real option. A choice set with only one plausible answer
  measures nothing.
- `constraints` carry repo conventions ("scripts/ uses urllib not
  requests", "comprehensions preferred") — the convention Noul reads them.

## Reading the verdict

| verdict | meaning | what to do |
|---|---|---|
| `accept` | choice backend picked a winner AND all 3 noul gates passed | apply the winner |
| `re-propose` | a gate failed (semantics/convention/minimality p < 0.5) | reconsider — the winner may be wrong; fix candidates or pick another |
| `gated-unverified-choice` | choice backend down; gates ran on YOUR `assume_winner` and passed | proceed with own judgment; record verdict |
| `gates-ood-suspect` | noul backend answered but collapsed (all gates identical near-zero p — known jev-student OOD failure) | gates unusable; fall back to own review |
| `choice-only` | winner picked, no noul backend | apply winner; gates unverified |
| `no-choice-backend` | nothing answered Choice | apply own judgment; record verdict |

Always check `degraded[]` and `backends{}` — they name which backend
answered. Never treat a degraded verdict as a clean pass.

## Current backend reality (2026-11-24)

- Real Jev API (`api.typesafe.ai`): **needs key — KNB-0822 open**. Set
  `JEV_API_KEY`/`JEV_API_URL` to enable; it serves BOTH choice and noul.
- `jev-student` (tony-omen:8780): noul-only AND out-of-domain-fragile —
  code-decision gates collapse (p≈0.005 ×3, flagged `gates-ood-suspect`).
- `jevos` (:8017): choice-capable per arena (tool 0.81, stag 0.92) but
  currently down fleet-wide; was ad-hoc on idc03.
- Net: today the door mostly returns `no-choice-backend` /
  `gates-ood-suspect`. That is honest data, not a bug — the eval pack
  (`scripts/jev/code-decision-eval.py`) measures when a real backend lands.

## Record the verdict (feeds the eval pack)

After applying (or rejecting) the change, append one JSONL line to
`evals/results/jev/code-decision-live.jsonl` when the case is interesting
(non-obvious choice, gate disagreement, degraded run):

```json
{"ts":"...","task":"...","winner":"...","verdict":"...",
 "backends":{"choice":"...","noul":"..."},"human_agree":true|false}
```

This is the corpus growth loop — human-verified verdicts are what the
eval pack scores Jev against.
