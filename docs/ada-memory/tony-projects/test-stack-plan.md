---
kind: note
status: active
subject: lab-stack
attribute: plan
---

# Lab stack — self-sufficient HA + Ada test environment

Status: v4 draft, 2026-09-26. Host moved to **idc01** per Tony's decision
(was mn01 in v3). Purpose: an isolated, resettable replica of the
production stack (Home Assistant + MDDB + Ada + embeddings) for stable
testing — break things freely without touching production data, quotas,
or audit state.

## Locked decisions

| Decision | Value |
|---|---|
| Host | idc01 (100.74.146.0, 2 vCPU / 7.8 GB / 96 GB) |
| Pod form | `.pod` + `.container` quadlets (per-service systemd control) |
| Embeddings | Pod-local Ollama (`nomic-embed-text`), no prod dependency |
| HA seeding | Golden tar of onboarded+configured `ha-config` |
| HA image | `homeassistant/home-assistant` pinned tag (e.g. 2026.9.0) |
| MDDB image | `tradik/mddb` pinned tag (e.g. 2.15.3) |

## Architecture

Single rootless pod `lab-pod` on idc01; all members share one network
namespace and talk on `127.0.0.1` inside the pod:

```
stacks/lab/
  lab.pod               # shared netns; publishes 8125 (ha) + 8004 (ada)
  lab-ha.container      # homeassistant/home-assistant:<pinned> → vol lab-ha-config
  lab-mddb.container    # tradik/mddb:<pinned> → vol lab-mddb-data (pod-internal only)
  lab-ollama.container  # ollama/ollama → vol lab-ollama (nomic-embed-text; llama3.2 opt)
  ada-lab.container     # ada-pi build; ADA_INSTANCE_ID=lab; env lab-ada.env
  lab-seed.sh           # onboard HA, mint token → secrets/lab-ha.env, mocks, golden tar
  lab-reset.sh          # stop pod → wipe vols → untar golden → start
  install.sh / verify.sh
  compose.yaml          # authoring sketch + docs (podlet can convert)
```

Internal wiring (pod netns):

- ada-lab → lab-ha `127.0.0.1:8125`
- ada-lab → lab-mddb `127.0.0.1:11033`
- lab-mddb embeddings → lab-ollama `127.0.0.1:11434`

Published to host only: `8125` (lab-ha UI) and `8004` (ada-lab API/WS).
lab-mddb and lab-ollama stay pod-internal.

## Isolation boundaries

- **Collections**: `ada-ha-*-lab` / `ada-lab-*` — never prod bank names;
  bank registry gets a `lab` instance scope.
- **Secrets**: `~/.config/secrets/lab-ha.env`, `lab-ada.env`; distinct
  `ADA_API_KEY`; HA token minted on lab-ha only.
- **No prod writes**: lab Ada's `chaba_event` → lab-ha only; no prod
  MDDB, no prod NotebookLM (dedicated lab notebook or none).
- **Ports**: lab uses 8125/8004/11033/11434(pod-internal)/9586 — clear
  of idc01 prod (8001-8003, 11023/11024, 11435, 3010, 3011, 3002,
  8443-8445, 9000, 80/443).
- **Blast radius**: co-locating with prod Ada/MDDB means a runaway lab
  can hurt production → every lab container gets `MemoryMax`/`CPUQuota`
  limits; lab excluded from the prod audit suite.

## Edge / access

- `tailscale serve --https=8125 http://127.0.0.1:8125` →
  `https://idc01.taila0626a.ts.net:8125` (HA needs a dedicated port —
  root-relative assets break under subpaths).
- Ada PWA via path mount: `--set-path /apps/lab-ada → 127.0.0.1:8004`
  (same pattern as `/apps/ha/ada-tony`).

## Data seeding

- `lab-ha`: onboard via REST (ha-testcontainer-style scripted onboarding,
  or onboard once then golden-tar `~/.local/share/lab/ha-config`).
  `demo:` integration for generic entities + `lab_mocks.yaml` for
  project-specific analogs (plug_tv, gate, weather station).
- `lab-mddb`: empty or seeded with non-personal banks only (general,
  home, people — never personal*/devin-handoff).
- `lab-reset.sh`: deterministic reset without re-onboarding.

## Code changes needed

- `ada-pi/backend/instance.py`: accept `lab` as a valid instance ID
  (currently fail-fast pins tony/michael).
- `ssot.apps.ada-memory-banks.yml`: `lab`-scoped bank set.
- `stacks/lab/` skeleton in chaba (above).
- SSOT: `ssot.apps.lab-stack.yml`, port additions in `ssot.values.yml`,
  lab-scoped audit section (or explicit exclusion).

## Known caveats

- **Resource budget**: idc01 has 7.8 GB total; prod services already run
  there. Lab adds ~3–4 GB (HA ~1 GB, Ollama ~1–2 GB, MDDB ~0.4 GB,
  Ada ~0.4 GB). M0 must verify headroom. Fallback: point lab-mddb
  embeddings at prod Ollama via `host.containers.internal:11434`
  instead of running lab-ollama (breaks full self-sufficiency).
- **Vector-space divergence**: lab recall uses nomic embeddings; prod
  uses Gemini — lab is fine for functional tests but not for judging
  recall quality.
- **Gemini is the one external dep**: dedicated test API key preferred;
  shared key works with quota caveat.
- **Fidelity gap**: `demo:` + light mocks ≈ 80% scenario coverage;
  energy/dashboard tests may want `mha_mirror_*`-style mirrors later.

## Phases

- **M0** — idc01 resource/port audit; `stacks/lab/` scaffold; limits set
- **M1** — lab-ha + `demo:` + mocks + golden tar
- **M2** — lab-mddb + lab-ollama + seed banks
- **M3** — ada-lab against lab-ha + lab-mddb (`instance.py` lab support)
- **M4** — tailscale serve, verify.sh, scenario runner → ada-lab
- **M5** — lab-reset runbook, SSOT, audit exclusion, this doc finalized

## Collaboration

This doc is the shared plan surface: Tony edits in the vault/Obsidian,
Devin edits + commits + syncs, Ada recalls via
`ada_memory_search(bank="tony-projects")` and drops findings via
`ada_remember` → `inbox/` → promote. Task items fan out to
`devin-handoff` when execution starts.

## Review log

- v3 (mn01): simulated Ada review — flagged standby-role conflict,
  subpath warning, audit exclusion (all accepted); Devin added
  vector-space, Gemini-quota, reachability, fidelity caveats.
- v4 (idc01): host changed per Tony; standby concern replaced by
  prod-contention + resource limits requirement.
