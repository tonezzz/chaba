# dispatch outcome — kk-mac-embed-lane-verify (2026-11-19)

## Result: done — kk-mac is an admission-gated embed-pool leg and already carrying traffic

## What was found

- kk-mac WAS registered in `EMBED_POOL_UPSTREAMS` on idc03 — but as
  `http://127.0.0.1:11445`, the **retired ssh tunnel**
  (`kkmac-ollama-tunnel.service` cleanly stopped+disabled 2026-11-17 09:05
  after ~19,002 restart flaps). 27,847 accumulated pool fails on a dead
  endpoint, and the leg bypassed the admission gate entirely.
- `kkmac-admission-shim.service` (:11447) — the fail-fast Ada Nest gate —
  was itself configured with upstream `http://127.0.0.1:11445`, so
  **LiteLLM's kk-mac legs were broken too** (upstream_errors piling up).
- Root cause of the topology change: kk-mac's adanest ollama now binds
  `0.0.0.0` — answering directly on tailnet `100.108.217.17:11434`
  (v0.40.8) and on LAN `192.168.0.101:11434`. bge-m3:latest is pulled
  (plus qwen2.5:32b, qwen3:8b, qwen2.5vl:7b, llama3.2:3b, qwen3:30b-a3b,
  gpt-oss:20b). This is option (b) of card `kkmac-ollama-durable-bind`,
  which is still backlog — commented there.

## What changed (live, idc03 user units — no repo deploy)

- `kkmac-admission-shim.service`: `KK_SHIM_UPSTREAM`
  `127.0.0.1:11445` → `http://100.108.217.17:11434`; dropped the retired
  tunnel from `After=`; description fixed. Restarts LiteLLM kk-mac legs
  too.
- `embed-pool-shim.service`: kk-mac pool leg `127.0.0.1:11445` →
  `127.0.0.1:11447` — embeds to kk-mac now pass the admission gate.
- daemon-reload + restart; both active.

## Verified live

- `POST :11447/api/embed` (bge-m3) → **HTTP 200** real vector (3.9s warm;
  ~11.8s first cold-load — cold calls lose the 8s race by design).
- Drain switch `kkmac-admission-shim.deny` → **instant 503**
  `admission_denied` in 0.7s — the gate is real on this path.
- `GET :11436/health` → upstreams include `http://127.0.0.1:11447`.
- Pool traffic: the :11447 leg shows **673 wins / 137ms last** — kk-mac
  is winning most races (M4 Max is fast); pool embeds 3× HTTP 200 ~4s.
- Bounded: the pool only races `/api/embed` + `/api/embeddings` at
  kk-mac; any deny → instant 503 → leg benched 60s, fleet races on.

## Docs reconciled (committed `69788ac5e2` on dispatch branch, not pushed)

- `ssot.audit.hosts.yml` — tunnel marked retired (expected_state:
  inactive, kept as disabled fallback); admission-shim/embed-pool notes
  updated to the gated topology; kk-mac ollama capability updated
  (0.0.0.0 bind, direct upstream, bge-m3 in model list).
- `docs/kb/kkmac-ollama-lane.md` — topology rewritten for the direct
  bind + gate-as-front-door.
- New job record `docs/ssot/jobs/infrastructure/2026-11-19-kkmac-embed-pool-gated-upstream.yml`
  with rollback steps.

## Caveats / follow-ups (board-noted)

- **LAN exposure**: `0.0.0.0` bind answers on KK's LAN too, not just
  tailnet — wider than SEC-0985's "don't bind publicly" intent. Narrowing
  to the tailnet IP needs adanest plist access (KK sign-off pending);
  noted on `kkmac-ollama-durable-bind`.
- Bind durability across reboots unverified (plist unreadable from
  kkkakk). If it reverts to loopback: repoint `KK_SHIM_UPSTREAM` back to
  `:11445` and `systemctl --user enable --now kkmac-ollama-tunnel`.
- One transient pool 504 was observed during the drain-switch probe —
  all legs happened to be benched/busy at that instant; recovered
  immediately (subsequent probes 200).

## How to verify

```bash
curl -s http://idc03.taila0626a.ts.net:11436/health   # upstreams include 127.0.0.1:11447
ssh idc03 'curl -s http://127.0.0.1:11447/health'      # upstream = 100.108.217.17:11434
ssh idc03 'curl -s -X POST http://127.0.0.1:11447/api/embed -d "{\"model\":\"bge-m3\",\"input\":\"x\"}"'
```
