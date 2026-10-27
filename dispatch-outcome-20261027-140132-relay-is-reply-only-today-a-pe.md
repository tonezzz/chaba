# Dispatch outcome — line-proactive-persona

Card: `line-proactive-persona` (OPS-0468). Runner: idc02.
Repo: chaba (this worktree) delivering drop-in patches for ada-voice
(`tonezzz/ada-voice`, base `main` @ `56c67c1`) — same convention as the
16 prior drops in `integrations/ada-voice/`. Nothing deployed, nothing
pushed; install steps are in the drop's README section.

## What was built

The card's three asks, end to end:

1. **Outbound path** — `chat_send` already posted to the relay `/send`
   loopback; it now carries `intent='proactive'` (declared persona-
   initiated send) and `mention='<member name>'`, plumbed through the
   queue + photo/doc sub-flows (LINE-only fields; tg/web note the
   drop). The relay resolves `to=<member name>` to a DM userId through
   a new extended chain: label cache → `LINE_USER_CALLERS` →
   `LINE_PERSON_ALIASES` → **persisted member dir**
   (`LINE_MEMBER_NAMES`, learned from profile fetches + first-seen
   registry writes — survives restarts) → throttled mddb
   `line-user-registry` scan (`LINE_REGISTRY_LOOKUP_TTL_S`, 300s).
2. **In-group addressing** — `/send` `mention=` builds a real LINE
   `mention` object: `@<displayName>` prefix + `mentionees[]` with
   UTF-16 code-unit offsets (len() undercounts emoji), display names
   via the per-member group/room profile endpoint per the card.
   Unresolvable member → 400, the send aborts rather than silently
   dropping a ping.
3. **Policy** — relay-enforced `_proactive_gate`: instance must be in
   `LINE_PROACTIVE_ALLOW` (empty = deny-all; this is the
   backend-declared-intent gate), per-(instance,chat) and
   per-(instance,member) debounce `LINE_PROACTIVE_DEBOUNCE_S` (600s),
   `LINE_PROACTIVE_DAY_CAP` (8). Write-through state
   (`LINE_PROACTIVE_STATE`) survives restarts. Tool-side: secondary
   (guest) turns can't pass `mention=`/`intent='proactive'`/`to=<other
   chat>` — PermissionError. Ops trail: `proactive_sent/denied/
   debounced` + `mention_failed` events, `proactive_msgs` in the
   send-ledger rollup.

## Files produced (in this worktree)

- `integrations/ada-voice/backend/line_relay.proactive-persona.patch`
- `integrations/ada-voice/backend/tool_runner_chat.proactive-persona.patch`
- `integrations/ada-voice/backend/tool_runner.proactive-persona.patch`
- `integrations/ada-voice/backend/realtime_provider.proactive-persona.patch`
- `integrations/ada-voice/backend/tool_guide.proactive-persona.patch`
- `integrations/ada-voice/docs/kb/msg-lane-multihome-routing.proactive-persona.patch`
- `integrations/ada-voice/tests/test_line_proactive.py` (new ada-voice test file)
- `integrations/ada-voice/README.md` — Drop 17 section w/ install steps
- `docs/ssot/jobs/ada/2026-10-27-line-proactive-persona.yml` — job trail

## Verification done

- Developed + tested in a scratch copy of ada-voice @ `56c67c1`
  (`.scratch/`, gitignored): **98 relay tests green** incl. the 20 new
  ones; `test_tool_runner` shows only the 5 pre-existing
  CalendarPlanMerge failures (ADA_INSTANCE_ID unset on this host —
  identical on pristine base). `scripts/tool-lint.py` clean.
- All six patches `git apply --check` clean against a fresh copy of the
  base.

## To go live (not done — dispatch scope)

1. Apply patches per the README install block; ordering caveat: drop 15
   (`chat_send page=`) also touches `tool_runner/chat.py`.
2. Set `LINE_PROACTIVE_ALLOW=ada,kaewta` on idc03 `ada-line-relay` —
   unset denies all proactive sends by design.
3. Restart `ada-line-relay` + persona backends; live-test the kaewta →
   nhong mention in the shared group.

## Limits / honest notes

- The gate only restricts *declared* `intent='proactive'` — the relay
  can't infer turn semantics; an undeclared send to a member DM keeps
  today's rules (runner-side owner-tier gate still covers secondary
  turns). Model discipline via tool_guide.
- Proactive payloads stay class=urgent: under a spent quota month they
  park on 429 like any push.
- Proactive is LINE-only this drop.
