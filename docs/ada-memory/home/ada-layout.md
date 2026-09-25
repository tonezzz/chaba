---
key: ada-layout
kind: fact
status: active
subject: ada-instances
scope: shared
source: vault
written_by: tony
last_verified: 2026-09-23
---

Ada runs as two HA-scoped instances on mn01, plus a guest backend on tony-dell. ada-ha-tony (ws endpoint wss://mn01.taila0626a.ts.net/apps/ha/ada-tony/ws, port 8002) serves Tony's household; ada-ha-michael (port 8003) serves Michael's. Voice clients connect over websocket with a per-device issued api_key; keys are minted/revoked via the chaba-admin Pair tab on tony-ha. The chaba-guest service on tony-dell :8014 runs Ada in CHABA_MEMORY mode — file-backed guest memory only, no MDDB banks, deny-listed dangerous entities. Speaker identification (ECAPA voiceprints) routes memory to person-scoped banks such as ada-ha-bank-personal-kk.
