# dispatch-outcome — kk-mac-jev-adapter-integration (idc02, 2026-10-29)

Added the explicit `kk_mac_local` executor contract end-to-end. New
`scripts/devnest/kk_mac_executor.py` implements the full contract —
admission (fresh Ada Nest heartbeat, `ollama_ok`, disk≥20G, node-not-busy,
bounded task class) → execution through `kk_mac_llm.run_task` → durable
usage/admission/response artifact under the allowed repo roots → an
independent deterministic verifier (JSON classes must parse;
`expect.required_keys`/`enums`/`facts` checked against the response, never
the model) → verdict `pass`/`fallback`/`fail`. `kk_mac_admission.py` gained
the overload gate (`tmux_jobs` non-empty, `load_ok=false`, or
`load1/cpu_cores>1` all defer; `--allow-busy` bypass). Board-side,
`dispatch_repos.py`/`board-api.py` admit `kk_mac_local` and validate
`task_class` (required, only for this executor), `prompt` (≤6000),
`expect` (bounded lists), and artifact roots. `runner-agent.py` serves it
behind `KK_MAC_LANES=1` (default 0): claimable defers live-lane cards to
capable runners, lets any host claim a card whose lane is ineligible, and
fails closed on broken contracts; `start_task`/`finish_pass` implement the
try-first semantics — one lane attempt per claim, then same-claim fallback
to the next lane with the stale worktree cleaned up; merge/verified is
gated on `verdict=pass` + landed artifact. Verified: 59 board contract
tests, 18 executor tests, 126 devnest tests all pass; full suite shows
only pre-existing failures (missing pytest for ada tests, one unrelated
ops test). Not done, by design: the supervised live dispatch — idc02 has
no `kk-mac` ssh key and a prior answer scoped KK-Mac to deterministic-only
runs, so a board request asks Tony to pick host/authorization; the runbook
is in the card comms and `docs/ssot/jobs/devnest/2026-10-29-kk-mac-executor-contract.yml`.
`KK_MAC_LANES` stays 0 until that dispatch passes.
