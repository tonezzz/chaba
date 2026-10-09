# dispatch outcome — vcast-claim-tombstone

Card: `vcast-claim-tombstone` — replace the `/claim` force path (revoke+re-mint) with the ada member-invite resurrect chain, auto-fallback on conflict, `/^screen-\d+$/` guard, rival-claimant atomicity.

## What changed

**`stacks/web/input-bridge/server.mjs`**
- New `adaResurrectScreenKey(adminKey, name)`: `POST /api/auth/invites {name}` → `POST /api/auth/keys/{name}/approve` → `POST /api/auth/invites/{name} {path:"/", redirect:"/apps/vcast"}` → returns `redeem_url`. Invite+approve are best-effort (idempotent 409/404 tolerated); the mint is authoritative — it only returns a `redeem_url` for an approved key.
- `/claim`: the `force` revoke path is deleted (field accepted-but-ignored). On `created.conflict`, a `screen-N` name auto-resurrects once; any other name stays a hard 409 (member tombstone semantics).
- Claim serialization: `withClaimLock` (single promise tail) makes resolution → mint/resurrect → redeem → slot-alloc → pair atomic. A `claimed_at` entry marker holds the name through the claim→register gap (cleared in `registerDisplay`); `nameHeld()` = live socket OR fresh claimed_at. Racing claims on a held name: explicit name → 409 `{name is in use}`; `want_screen`-derived → deflect to next free slot. Held names are checked before ANY ada call, so a claim (even `force:true`) can never revoke a live display's key — the re-tombstone bug is structurally gone.
- Claim body wrapped so ada timeouts answer 502 instead of hanging.

**Tests** — new `vcast-claim-check.mjs` (19 checks): tombstone→resurrect→redeem with ordered ada-call assertions, member-name guard, rival race (exactly one winner), `want_screen` deflect, live-held protection. `vcast-registry-check.mjs` + `vcast-handoff-check.mjs` stubs updated to the member-invite lifecycle (DELETE revokes but keeps the name taken; invites/approve/mint endpoints added); handoff-check now asserts one-shot auto-resurrect instead of the force retry.

**`pair.html`** — force checkbox removed (resurrect is automatic); 409 hint updated. **`sw.js`** — `vcast-v5` cache bump. **`vcast-headless.mjs`** — claim-contract comments updated. **`ssot.apps.vcast.yml`** — relay/re-pair/tests sections updated. **Job record**: `docs/ssot/jobs/vcast/2026-10-09-vcast-claim-resurrect.yml`.

## Result / verification

All loopback checks pass under podman `node:22-alpine` (idc02 has no local node):
- `vcast-claim-check.mjs` 19/19 — tombstone via /release → `/claim {name}` pairs on that name with zero manual ada calls; force-claim on a live-held name 409s with zero ada mutations.
- `vcast-registry-check.mjs` 19/19, `vcast-handoff-check.mjs` 6/6, `vcast-cast-check.mjs` 17/17, `vcast-flap-check.mjs` 7/7.

NOT deployed (dispatch mode). To go live: restart `input-bridge.service` on idc03; `pair.html`/`sw.js` land via the web public rsync.
