# dispatch outcome — nest-lane-metrics (2026-10-08)

## What changed

- **open-jev repo** (`~/CascadeProjects/open-jev` on tony-omen / idc02 / idc03,
  editable installs — checkout *is* the served code):
  - vendored `openjev/lane_metrics.py` — verbatim copy of chaba
    `scripts/jev/lane_metrics.py` (stdlib-only).
  - `openjev/server.py`: `lane_metrics.attach(app)` in `create_app()`; the
    `/v1/systemone` handler now calls `METRICS.observe(elapsed_s,
    questions=len(resp.answers), escalations=0)` — this server answers every
    question type for real, so there is no stub/heavier-tier path to count.
  - **uncommitted** on all three checkouts (upstream is
    github.com/daseinlabs/open-jev; no push/commit per dispatch policy).
    idc02's pre-existing bf16-CPU RAM patch in `torch_backend.py` untouched.
- **idc03 `~/jev-student/serve.py`** (distilbert prod gate — a snowflake file
  outside any repo, served by `jev-student.service`): vendored
  `lane_metrics.py` beside it, wired `attach(app)` + `observe()`; non-noul
  answers are stubs → counted as escalations (same semantics as chaba's
  `serve-seqcls.py` / `serve-gemma-head.py`).
- **idc03 `localhost/openjev:cpu` image rebuilt** from the checkout (Containerfile
  copied over from tony-omen — it was untracked there) so the 8779 quadlet lane
  carries the new code.
- Trail: `docs/ssot/jobs/nest/2026-10-08-lane-metrics.yml`.

## Restarts / verification

| lane | unit | result |
|---|---|---|
| idc02:8777 heavy-a | `open-jev.service` restarted | `/metrics` 200; systemone probe → requests_total=1 |
| idc03:8778 jev-student | `jev-student.service` restarted | `/metrics` 200; mixed probe → escalations_total=1 for the stub choice answer |
| idc03:8779 student-b | image rebuild + `openjev-student.service` restart | `/metrics` 200 |
| tony-omen:8777 heavy-b | `open-jev.service` started (was leash-parked) | `/metrics` 200 |
| tony-omen:8778 student-a | `open-jev-student.service` started | `/metrics` 200; probe → requests_total=1 |

Omen note: units bind the tailscale IP (100.75.102.88), not loopback — probe
`http://100.75.102.88:PORT`, not 127.0.0.1. gemma-3-4b took ~380s to warm
(swapping host); metrics endpoint answers immediately anyway.

## Acceptance

`python3 scripts/ada/nest-overview.py --dry-run` — all five jev lanes show real
decision counters (↻ first-baseline marks) and esc%; only `ollama` prints
"no metrics", as expected.

## Left running

The two omen units were started for verification and left up — the hourly
`open-jev-leash.timer` re-parks them past 2.5h uptime, and Monday's 04:30
bench picks up the new code either way.
