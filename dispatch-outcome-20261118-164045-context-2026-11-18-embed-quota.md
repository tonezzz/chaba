# Dispatch outcome — spike-migrate-mddb-cms-plane-11027-embed-8f86af

**Result: PROVEN on scratch.** A CMS-plane migration to local bge-m3 embedding works with a 3-line env change on the existing prod image, writes never block, and search gets ~6–30× faster. Rankings shift (~31–36% top-10 overlap vs gemini), so a golden-set eval should gate any prod cutover.

## What was done

1. **Scratch instance** — `mddb-scratch-embed` rootless quadlet on idc02 `:11029`, own data dir, image `localhost/mddb:2.18.10-merge` (identical to prod :11027), env copied verbatim from the live `mddb-embed` :11028 unit: `PROVIDER=ollama`, `API_URL=http://100.102.134.91:11436` (embed-pool-shim), `MODEL=bge-m3`, `DIMENSIONS=1024`.
2. **Data** — 931 real docs read-only copied from :11027 via paginated `/v1/search` → `/v1/add`: chaba-lessons 174, kb-development 11, kb-features 59, kb-operations 267, kb-system 20, ada-cms-pages 400-doc subset.
3. **Measured** — ingest 538 docs/min, 0 fail; embed drain 931 jobs/~3.8k chunks in ~42 min wall clock (~2–3 docs/min while the pool was degraded → ~20–36 docs/min warm); recall top-10 overlap vs gemini :11027: **scratch 36.3%, prod bge bank :11028 31.0%** — identical per-query on shared collections (scratch exactly reproduces bank retrieval); search latency **160 ms scratch / 32 ms bank vs 1099 ms gemini**.
4. **Runbook** — `docs/ssot/jobs/mddb/2026-11-18-cms-plane-bge-m3-migration-runbook.yml`: exact env diff (3 lines), `POST /v1/vector-reindex {collection, force:true}` procedure (plain reindex skips wrong-space vectors via content-hash check), drain sizing (~6–12h for the 9.8k-doc plane), rollback (revert env + force-reindex), and :11023 leader notes for MEM-1129 (followers carry no embed env — vectors replicate via binlog).
5. **Report** — `reports/2026-11-18-mddb-cms-bge-m3-spike.md` + raw `spike-cms-bge-recall-pass{1,2}.json`; scripts in `scripts/mddb/spike-cms-bge/`.
6. **Teardown** — scratch unit stopped/disabled/removed, quadlet deleted, data dir removed via `podman unshare`, port 11029 free. No prod containers touched; :11027/:11023 only ever read.

## Key findings

- **Pool cold-model trap**: an upstream with lapsed bge-m3 keep_alive cold-loads ~21 s > shim's 8 s deadline → dead-cooldown flapping. Warming omen moved drain 2→14+ docs/min instantly. Fix: per-upstream warm-ping cron (~4 min).
- Racing fans every call to all upstreams — ~4× duplicated compute; capacity ≈ fastest warm upstream. `127.0.0.1:11445` (dead kk-mac tunnel) is stale in `EMBED_POOL_UPSTREAMS`.
- mddb embed workers are hardcoded at 2 — the real drain ceiling when the pool is healthy; no env knob exists.
- Fail-closed confirmed: `dropped=0, retried=5` through a degraded window — the resilience the outage demanded.

## Verify

- `reports/2026-11-18-mddb-cms-bge-m3-spike.md` — numbers + interpretation
- `reports/spike-cms-bge-recall-pass2.json` — per-query overlaps/latency
- Runbook yml — env diff + reindex + rollback
- idc02: `systemctl --user list-units | grep mddb-scratch` → nothing (torn down)
- Card comms: two status comments posted (interim + final)
