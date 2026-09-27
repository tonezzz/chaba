# LINE Bot — outbound messaging project

Date: 2026-09-27 · consolidated for review

## What it is

Outbound LINE notifications — system → Tony (alerts, dispatches,
Ada-initiated messages). Distinct from **Yomi**, which *reads* LINE.

## Current state — gaps found 2026-09-27

- **No Ada tool exists to send LINE messages.** When Tony asked
  "send me a test message" (session 7975f60c71, ~11:15), Ada could only
  call `ada_memory_search` + `web_search` — she guessed and checked the
  LINE Bot *API status page* instead of sending. Nothing arrived.
- **No LINE Messaging-API channel token** found in secrets on idc01 or
  on this box — the classic "bot account + push API" path isn't wired.
- The only working send path is **Yomi's `send_message`** (E2EE send as
  Tony's own account to any chatId) — but that MCP server is not
  reachable from Ada's tool layer, and its session is revoked (see the
  Line Yomi page).

## Proposed path

1. Re-login Yomi (passwordless secondary-device flow on Tony's phone —
   `login` → PIN → `login_complete`; ~3 min window).
2. Expose a thin `line_send` Ada tool: `tool_runner` → yomi
   `send_message` (a small HTTP shim or a local CLI wrapper on idc01).
   Tools needed: `line_send(to, text)` + `line_chats()` for resolving
   recipients. Gate under `ADA_DEV_TOOLS`-style confirmed writes —
   outbound messages are consequential.
3. Until wired, Ada's honest answer is: "LINE send is offline — needs
   Tony's re-login." (Memory note `yomi-vs-line-bot` updated with this.)

## Pending

- [ ] Tony: LINE re-login on the phone (allow-from-other-devices + PIN)
- [ ] Devin: `line_send`/`line_chats` Ada tools via yomi
- [ ] Optional later: dedicated LINE Messaging-API bot channel (cleaner
      identity — messages come *from Ada*, not "from Tony")
