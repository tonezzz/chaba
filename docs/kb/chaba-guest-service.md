# Chaba Guest Service — procedure

Card: `ada-rebrand-chaba` (ADA-0519) decision `guest-is-chaba` — one house
persona, tiered service. "Polity ship-AI" model: the same Chaba serves
everyone; what she can *do* depends on who's talking and where.

## Tier model

| Tier | Who | Lane | Memory | Tools |
|---|---|---|---|---|
| owner | Tony | `ada-ha-tony` (:8002, persona `chaba`) | personal bank `ada-ha-bank-personal-tony` | full surface |
| member | KK | `ada-kk` (:8007, persona `kaewta`) | `ada-ha-bank-personal-kk` | `persons.kk.tools` |
| guest | visitors | a dedicated guest lane (planned) | file-backed chaba store — PUBLIC notes only | allowlist below |

Name collisions are resolved by design: there is no "Ada vs Chaba" —
`@ada` is a routing alias to the owner lane, `chaba` is the persona name
everywhere. Guests never get a LINE persona; they talk to Chaba on a
guest device.

## Guest mode mechanics (already built in ada-pi)

- Activation is a per-lane env flag: `CHABA_MEMORY=1` in the lane's
  `~/.config/secrets/ada-*.env` (idc03).
- When set, `realtime_provider.py` appends `CHABA_INSTRUCTIONS`
  ("You are Chaba… in guest mode" — name, enroll, disclose, limits) and
  `CHABA_DECLARATIONS` (guest-scoped re-declares of `ada_remember`,
  `ada_memory_search` plus `ada_enroll_speaker`, `home_status`,
  `control_entity`, weather/pool/battery reads).
- Memory is the file-backed chaba store, **not** MDDB banks — guest
  notes can't pollute personal banks and don't need MDDB keys.
- `ada_remember` is forced `kind='guest'` (public); `private=true`
  fails for guests — promoted users only.
- Actuation: `control_entity` is restricted to on/off + media_player
  verbs at the instruction layer. Movers (`cover`, `gate`, `button`)
  are refused by policy — there is no code-level block, so the HA
  credential scoping below is the real fence.

## Standing up a guest lane (checklist)

1. **Service**: new `ada-guest.service` on idc03 — same
   `pwa_server.py` ExecStart pattern, own port (pick next free,
   ~8010), `EnvironmentFile=~/.config/secrets/ada-guest.env`.
2. **Env** (`ada-guest.env`):
   - `CHABA_MEMORY=1` — the whole point.
   - `ADA_PWA_NAME=Chaba` (or "Chaba — guests").
   - No `ADA_IDENTITY_INSTRUCTIONS` override needed — CHABA_INSTRUCTIONS
     owns the persona in guest mode.
   - Gemini: shared **free** pool (`…UCiA`) — guests should never burn
     the paid quota.
   - OR fallback: fleet daily key (`…5528`) is acceptable; do NOT give
     a per-lane paid key.
   - `ADA_EXCLUDED_TOOLS` — extend beyond the guest allowlist only if a
     read leaks (e.g. battery detail exposing routines).
3. **HA credentials — the real fence**: if the guest lane needs
   `HOME_ASSISTANT_*`, use a dedicated `svc-chaba-guest` HA account on
   tony-ha with an entity allowlist (lights/media/common areas only) —
   never the owner token (see `ha-ada-isolation`). Guest mode with no
   HA token is also valid (state reads 404, still answers).
4. **Keys store**: dedicated `ada-ha-guest-keys.json` (device pairing)
   — don't share the tony lane's key file.
5. **Bank/CMS**: none — guest mode ignores MDDB banks by design. Do
   not set bank envs; the file store lives under the service's own dir.
6. **Deploy membership**: add `ada-guest` to `deploy-ada.sh` SERVICES
   explicitly (isolation decision — see `ha-ada-isolation`).
7. **Cgroup caps**: guests get the tightest caps — `MemoryMax=512M`,
   `CPUQuota=50%` in a drop-in (they're the least-trusted lane).
8. **LINE**: do NOT add a guest persona to `LINE_NAME_BACKENDS` —
   guests reach Chaba on the guest device, not the family group.

## Guest session flow (what Chaba does)

1. First contact → ask the visitor's name → `ada_enroll_speaker`
   with `who='guest'` + name (registers them; an admin can promote to a
   named user later).
2. Before the first `ada_remember` in a session → say clearly that
   saved notes are **visible to the household** (public by design).
3. Read-only state/sensors + lights/media control; refuse anything
   that moves (covers, gates, buttons) politely.
4. `ada_remember(kind='guest', key, text)` for preferences/notes —
   e.g. "favorite-drink". `ada_memory_search(scope='guest')` recalls
   them on return visits.

## What-ifs

| Scenario | Expected behavior |
|---|---|
| Guest asks to open a gate/cover | Polite refusal — "moving" devices are off-limits to guests |
| Guest asks for personal info about the household | Refuse — guest scope can't reach personal banks (file store only) |
| Guest tries `private=true` memory | Tool call fails — promoted users only |
| Guest lane's token leaks | `svc-chaba-guest` is allowlisted — revoke token, blast radius is lights/media reads |
| Guest lane floods Gemini | Free-pool key + cgroup caps; worst case = slow guest answers, family lanes unaffected |
| Guest becomes a regular | Admin promotes the enrolled speaker to a named user → they get a member lane or PWA key with private memory |
| Someone mentions `@chaba` in LINE | Routes to the owner lane (8002) — guests are never in the family group |

## Audit & monitoring

- `session-audit` / transcript audits flag `fail:ada_enroll_speaker`
  and guest-mode failures — watch the `audit-fail-ada-enroll_speaker`
  card while a guest lane soaks.
- Guest notes live in the lane's file store — review periodically;
  they are intentionally not in MDDB.
- The `ha-ada-isolation` scorecard picks up the guest lane's caps/key
  once it exists (`iso-shared-fate`).

## Open decisions (logged on card)

- Device: which surface runs guest mode — dedicated wall-tablet PWA,
  or a `?guest` mode flag on the shared PWA? (A `CHABA_MEMORY` lane is
  per-service today; a per-connection guest flag doesn't exist yet.)
- Whether `svc-chaba-guest` gets an entity allowlist at all, or the
  lane ships with zero HA credentials first.
