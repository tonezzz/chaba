# Nemotron store-aware rate-limit probe — 2026-10-24

After the three-rep pinned baseline completed, the store-aware treatment
hit HTTP 429 twice at rep 1 tasks 4 and 5. After a cooldown, a two-task
probe on `t3-update-tailscale` and `t6-hub-ada-nest-heartbeat` also
returned HTTP 429 for both tasks, before any tool call.

No paid endpoint was used. The pinned treatment remains incomplete and
has no capability aggregate. Retry only after the free provider reports
capacity again.

Raw probe: `reports/bench-edu-manage-2026-10-24-nemotron-supervl-rate-limit-probe.json`.
