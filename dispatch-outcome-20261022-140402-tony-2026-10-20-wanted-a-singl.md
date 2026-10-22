# Dispatch outcome — roster-agents-tab (2026-10-22)

## What the card asked

Ship a single chat UI on chaba-admin to talk to ada/chaba/kaewta/klaut over the
existing ada lanes (roster console + Agents dashboard view + per-lane
roster-tony chat keys). Card was in `review` with one open request to Tony:
open the Agents tab, seed lane keys once, confirm all four contacts connect.

## What I did

Re-verified every producer and consumer surface from this runner (idc02):

- `https://idc02.taila0626a.ts.net/apps/roster/` → 200, sha256 byte-identical to
  `stacks/web/public/apps/roster/index.html` on master (deployed copy is current).
- `http://127.0.0.1:8099/apps/roster/` (web origin direct) → 200.
- `ada-webchat-card.js` on the idc03 tailnet mount → 200.
- All four lane ws mounts alive and enforcing auth — h1 upgrade probe with a bad
  key returns 403 (not 404/timeout) on ada-tony (:8002), ada-kk (:8007),
  ada-dev (:8005), ada-michael (:8003).
- Live `chaba-admin` dashboard on **tony-ha :8123** (ws `lovelace/config`)
  confirmed to contain the `agents` view after `board`, iframe →
  `https://idc02.taila0626a.ts.net/apps/roster/` — matches the repo snapshot.
- Public edges `tony-ha.surf-thailand.com` and `ada-ha.surf-thailand.com` are
  CF-Access gated as normal (302 to cloudflareaccess).
- idc03 `~/CascadeProjects/chaba-tony-dell` checkout: the mid-merge stall noted
  in FIX2 is resolved (no MERGE_HEAD); 3 autostash entries linger, and local
  card edits are normal board-api writes between kanban-commit cycles.

## Bug found and fixed

The card `note:` (and the open request) told Tony to verify at
`https://ada-ha.surf-thailand.com/chaba-admin/agents`. That edge proxies to
`tony-omen:8125` — the **ada-ha** lab instance, whose "Ada admin" dashboard
(url_path also `chaba-admin`) has **no agents view**. Tony would have landed on
a dashboard without the tab. Correct URL:
`https://tony-ha.surf-thailand.com/chaba-admin/agents` (edge catch-all →
tony-omen:8123, "Chaba admin", agents view live).

- Posted a board comment with the full re-verification + the corrected URL.
- Fixed `note:` in `docs/ssot/kanban/cards/roster-agents-tab.yml`, committed on
  the dispatch branch (`8959bdb8`, CHABA_ALLOW_CARD_COMMIT=1 — sanctioned
  dispatch-worktree card edit). board-api has no endpoint to edit `note` or a
  request `ask`, so the durable fix lands via merge.

## Result / state

- Card stays in `review`; the open request `open-chaba-admin-agents-and-seed-…`
  remains Tony's — browser key seeding is inherently his step (localStorage on
  his browser, keys in `~/.config/secrets/roster-bootstrap.txt`, canonical on
  tony-macbook which was unreachable over ssh at check time — host key
  verification failed; file absent on idc02/idc03/tony-dell/tony-omen).
- Nothing else blocking: all infrastructure-side verification is green.

## How to verify

1. Open `https://tony-ha.surf-thailand.com/chaba-admin/agents` (Tailscale up).
2. Paste the bootstrap URL from `~/.config/secrets/roster-bootstrap.txt` into
   the Seed box (bottom of the contacts rail).
3. All four contacts should show `connected`; clicking each mounts its
   `ada-webchat-card` on chat_id `web-tony`.
