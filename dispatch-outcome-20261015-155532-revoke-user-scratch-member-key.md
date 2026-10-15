# Dispatch outcome — revoke-user-scratch-member-key

Card: `revoke-user-scratch-member-key-20943c` (SEC-0482) · runner: tony-omen · 2026-10-15

## What was found

`user-scratch-member` existed in two ada key stores on idc03:

| Store | Backend | State before | State after |
|---|---|---|---|
| `~/.config/secrets/ada-ha-tony-keys.json` | ada-ha-tony :8002 | already `revoked:true` @ 2026-10-12 20:33 | unchanged (revoked) |
| `~/.config/secrets/ada-ha-dev-keys.json` | ada-dev :8005 | pending invite, `approved:false`, issued 2026-10-14 | `revoked:true` @ 2026-10-15 15:59 |

Not present on ada-pi-pwa :8001's store or anywhere in tony-dell's secrets. mn01 (standby
lane) is offline >1d and could not be checked — the key was minted on idc03 lanes so it is
almost certainly absent there; flagged in the card comms.

## What changed

- `POST http://127.0.0.1:8005/api/auth/keys/user-scratch-member/reject` on idc03 with the
  ada-dev admin key (pulled server-side from `ada-dev.env`, never echoed) →
  `{ok:true, status:revoked}`. Verified in the keys file.
- Board: request `revoke-user-scratch-member-key-now-6282e7` was already answered
  (Tony: "revoke now ★" — that dispatch is the answer); result comms posted; card moved
  backlog → done.
- Job trail: `docs/ssot/jobs/ada/2026-10-15-revoke-user-scratch-member-key.yml`.

## Note for next time

Pending member keys (`approved:false`) take `POST /api/auth/keys/{name}/reject`;
`DELETE /api/auth/keys/{name}` is for issued keys — the API refuses the wrong verb.
`ada_member_keys` is no longer on the ada-pi tool surface; revocation is a direct call
to the lane backend's `/api/auth/keys` endpoint with that lane's admin key.

## Verify

```sh
ssh idc03 'python3 -c "
import json
for f in (\"ada-ha-dev-keys.json\",\"ada-ha-tony-keys.json\"):
    e = json.load(open(f\"/home/tony/.config/secrets/{f}\"))[\"user-scratch-member\"]
    print(f, \"revoked:\", e.get(\"revoked\"))"'
# ada-ha-dev-keys.json revoked: True   ·   ada-ha-tony-keys.json revoked: True
```
