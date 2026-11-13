# Dispatch outcome — kk-mac routing proposal (card kk-mac-routing-proposal-fold-local-qwen2-4d513b)

## What changed (committed on dispatch branch, commit 747b44bbd)

- **Proposal doc**: `docs/ssot/jobs/devnest/2026-11-13-kk-mac-routing-proposal.yml` —
  full routing proposal: where `ollama-qwen32b-kkmac` sits in llm-gateway
  fallback chains vs paid flash-lite, per job_class verdicts, savings
  evidence path, risks, and the rerun cadence.
- **`scripts/devnest/kk_mac_executor.py` + `kk_mac_llm.py`**: model default
  repinned `qwen3:8b` → `qwen2.5:32b` (eval evidence: qwen3:8b = 0.674 acc,
  16 parse-fails; qwen2.5:32b = 0.857/0.878/0.909/1.0, 0 parse-fails).
- **`scripts/board/lane-savings.py`**: `card_lane()` now honors
  `action.executor` (`kk_mac_local`, `jules`, `nlm_batch`, `opencode`)
  before the type fallback; those lane ids added to `CHEAP_LANES`.
  Previously every executor-pinned kk_mac run reported as lane `devin` —
  savings were invisible. Verified live: the 2026-11 report now shows
  `kk_mac_local=3, jules=15, nlm_batch=1`.
- **`docs/ssot/infrastructure/ssot.devnest-lanes.yml`**: kk_mac_local
  `expected_tokens` note updated to the repinned model.

## The proposal (summary)

- **Adopt**: `ollama-qwen32b-kkmac` as **leg 1** on `summary`, `classify`,
  `bench`; **leg 2** on `chat-local` (after tonydell-qwen7b, always-on).
- **Defer**: `tool-call` gets leg-3 resilience position only after a
  3-consecutive-run gate — deference 0.878 < 0.90 bar; llama3.2:3b remains
  the better-behaved local defer-fallback.
- **Excluded**: voice-aux (latency), chat (quality parity), vision/image
  (modality), embedding (768d space poison rule).
- **Savings evidence**: lane-savings.py (now executor-aware) + LiteLLM
  ledger delta on `gemini-3.5-flash-lite`; movable spend ~$22/window.
  Token-evidence gap noted: kk_mac usage lives in taskdir artifacts, not
  yet scanned — counted runs only until wired.
- **Risks**: member-device availability (leg-1 only on batch classes),
  no admission gate at LiteLLM layer (proposed shim card), qwen3:8b
  exclusion, deference gap, 36GB capacity, live-vs-repo config drift.
- **Rerun cadence**: `kkmac_eval.sh qwen2.5:32b` each kk-mac online
  window ≥24h apart, 3 runs in ~2 weeks via
  `jevnest-kk-mac-capacity-loop`; corpus rebuild/model bump resets streak.

## Verification

- `pytest tests/devnest/test_kk_mac_executor.py test_kk_mac_admission.py
  tests/board/test_executor_contract.py` → 109 passed.
- `lane-savings.py --month 2026-11` runs clean and surfaces kk_mac_local.
- Pre-commit SSOT validation passed; commit on
  `dispatch/20261113-202232-card-judgment-eval-done-2026-1`.

## Board activity

- Progress + result comments posted; **board request raised** for Tony's
  decision on gateway leg placement (recommended / canary-only /
  executor-only). No `config.yaml` chain edits made — those wait for the
  decision + rerun gate.
