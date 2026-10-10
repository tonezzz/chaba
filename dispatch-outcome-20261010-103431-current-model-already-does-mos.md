# dispatch-outcome — memory-lane-policy (2026-10-10)

## Result: DONE (chaba side) — registry contract landed; ada-pi runtime filed as follow-up card

## What changed (commit cb93641a on dispatch branch)

| Delta (card spec) | Implementation |
|---|---|
| 1. `home` writable | `writable: true` + `allowed_tools: [ada_remember, ada_forget, ada_outcome]`, `write_policy: confirmed` kept |
| 2. New `dev-scratch` bank | `instances: [dev, tony-dev, ada-dev]`, collection `ada-ha-bank-dev-scratch`, `writable` + `direct`, `status: testing`, `prompt_hidden: true`, `env: staging` |
| 3. Assignment rule | **Picked `instances_readonly: {tony-dev: tony, ada-dev: tony}` on all 24 tony-visible banks** — the card offered this OR "leave unassigned", but its verify requires dev sessions to *read* prod banks, which unassigned can't do. Map form (not a list) so `{instance}` collections expand to the prod twin (`ada-ha-bank-personal-tony`, not a nonexistent `-tony-dev`). kk-only banks (personal-kk/nhong) get no entry — a tony-dev twin mirrors tony's view, which excludes them. |
| 4. Provenance | `env` added to `meta_schema` (enum `prod|staging`, absent=prod); `dev-scratch.env: staging` is the marker — writers stamp `meta.env` from the bank, no instance-name heuristic needed |
| 5. Op collections | Already suffix per instance — doc'd in SSOT prose only |

Also: `dev-scratch` added to every restricted `person_policies` allow list (inert on prod — bank never loads there; on a dev backend it's each identity's sole writable bank). Doc updates: `ssot.services.yml` ada-dev banks line, `ssot.apps.ada-memory.yml` Instances, `ssot.apps.ada_ha.yml` ADA_INSTANCE_ID list, `docs/ada-memory/README.md`. Job note: `docs/ssot/jobs/ada/2026-10-10-memory-lane-policy.yml`.

## Split decision — why ada-pi got a follow-up card

`memory_banks.py` lives in the ada-pi repo; this dispatch worktree is chaba-only. The registry field is **forward-compatible**: the current loader ignores unknown keys, so dev instances today simply see only `dev-scratch` — "dev never writes prod" holds already. Filed `ada-memory-dev-lane-runtime` (queued, repo: ada-pi) with the exact ~10-line spec (`_add` readonly mount + `MemoryBank.env`/`read_as` + `memory_meta` stamping + tests + readonly-refusal message pointing at dev-scratch).

## Verified

- `yaml.safe_load` on all edited/created files; `render-memory-banks.py` renders 27 banks cleanly.
- Simulated `MemoryBankRegistry._add` against the rendered JSON for both code paths:
  - **Today (inert field)**: `tony-dev`/`dev` see only `dev-scratch` — sole write target.
  - **After ada-pi patch**: `tony-dev` mounts 24 prod banks readonly + writable `dev-scratch`; `personal` resolves `ada-ha-bank-personal-tony`; prod `tony` unchanged (11 writable banks, no dev-scratch).
- `node scripts/ssot-validate-all.mjs` could not run (no node on idc02 runner); YAML parse + render + simulation cover the changed surface.

## Heads-up / not done

- **Live drift**: `~/.config/ada/memory-banks.json` on idc03 carries hand-added `dev-lab`/`dev-bench`/`dev-dispatch` banks (`ada-dev-*` collections, per `ssot.services.yml`) absent from SSOT — the next render drops them for the `dev` instance. Collections stay in MDDB; re-add if they're missed.
- `ada-ha-bank-dev-scratch` collection doesn't exist in MDDB until first write; memory-banks audit will warn "declared but missing" meanwhile.
- No deploy/render-to-host/service restarts done — needs explicit approval (`render-memory-banks.py --host idc03`, restart ada-dev).
- Full card verify (live tony-dev session reading prod banks) is gated on the ada-pi patch + the tony-dev backend existing (ha-dev-instances).
