# micro-bench — micro-AI input-polish harness

Tests the hypothesis (card `micro-ai-input-polish`, BEN-0465): a small local
model sits in front of each receiving AI and rewrites raw user input —
ASR mishearings, Thai/Eng code-switch, typos, fragments — into the phrasing
that AI performs best on, for better accuracy **and** fewer downstream
tokens. Bench-first per the `model-eval` procedure; adopt only on measured
gain.

## Pipeline

```
raw fixture ──[optional polish model]──> sent text ──> downstream AI ──> verdict
                normalize_v1 prompt                 fixed HA-tool JSON protocol
```

- **direct variants** (`polish: null`) are baselines — raw goes straight
  downstream.
- **polish variants** add the micro-AI step; each pairs with the `direct-*`
  variant on the *same downstream* so deltas are apples-to-apples.

## Layout

- `fixtures/manifest.yml` — 40 inputs across 10 categories: en/th ASR noise,
  Thai-Eng mix, typos, fragments, entity-heavy (preserve-check), **clean
  controls** (regression detector), chit-chat, **ambiguous + gibberish**
  (fabrication detector — a tool call where none is expected is scored
  `fabricated`).
- `variants.yml` — `{id, polish, downstream, host_labels}` per run. Providers:
  `openai_compat` (ollama/llama.cpp /v1), `ssh_openai` (same call over an
  ssh prefix to a remote loopback server — incl. multi-hop like
  `tony-dell ssh macbook`; token usage survives), `ssh_cmd` (opaque pipe,
  no tokens), `gemini` (generateContent, needs `GEMINI_API_KEY` or
  `~/.config/secrets/gemini-api-key.env`), `mock`.
- `bench.py --variant <id>` — per fixture: tool_call match, entity
  preservation, polish similarity to gold, per-stage latency, **net tokens**
  (polish + downstream — the efficiency claim counts both). Writes
  `results/<variant>-<ts>.json` (schema `micro-bench-result` v1).
- `report.py [--card <id>]` — renders `reports/micro-polish/LATEST.md`
  (variant × metric + per-category table + **adopt-gate verdict**),
  appends `trend.md`, posts a card comment via board-api.

## Adopt gate

From the card: polish is adopted at an insertion point only if
match-rate >= the direct baseline **and** net-tokens OR latency is
neutral-or-better **and** fabricated calls don't increase. If only the
noisy categories improve, verdict = SCOPE (deploy on that lane, e.g.
Ada's ASR path — not a universal layer).

## Smoke

```
python3 scripts/micro-bench/bench.py --variant dry-run-dummy --dry-run
python3 scripts/micro-bench/report.py
```

Real run (idc03 llama3.2:3b, fully local):

```
python3 scripts/micro-bench/bench.py --variant direct-llama32
python3 scripts/micro-bench/bench.py --variant polish-llama32-llama32
python3 scripts/micro-bench/report.py --card micro-ai-input-polish
```

## Bench hosts (provisioned 2026-10-13)

The spec'd polish lanes run llama.cpp b11583 + Llama-3.2-3B-Instruct
Q4_K_M on loopback `:8114`, behind user unit `micro-bench-llama.service`:

- `idc02` — CPU build, direct ssh from any tailnet runner.
- `tony-macbook` — Vulkan build (Radeon Pro 450 / RADV + HD 530 via
  `--fit`). Runners reach it through the dell hop
  (`ssh tony-dell ssh macbook`); mn01 has no macbook key. Laptop — the
  server is only expected up while benched.

Both variants go through `provider: ssh_openai`, so no tailnet listener
is opened. Start before a run:

```
ssh idc02 systemctl --user start micro-bench-llama
ssh tony-dell ssh macbook systemctl --user start micro-bench-llama
```

Omen's lane is plain `openai_compat` to ollama `100.75.102.88:11434/v1`
(phi3-gguf — the :8001 llama-router of ssot.gpu.yml is retired; the port
now serves sensor-reader).

## Runner card (action.type=script)

```yaml
action:
  type: script
  script:
    repo: chaba
    cmd: >-
      python3 scripts/micro-bench/bench.py --variant <id> &&
      python3 scripts/micro-bench/report.py --card micro-ai-input-polish
```
