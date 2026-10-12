# Where Things Go — the capture & recall map for Tony

Standard procedure for "where did my idea go / how do I get it back".
Everything said in a session lands in exactly one of these places —
there is no fifth destination.

## The capture map

| You said | It went to | Look there |
|---|---|---|
| idea, request, "what if we…", complaint | kanban card (`column: backlog` or `doing`) | the board |
| cross-session note ("save this for later") | `docs/ssot/focus-inbox/*.yml` | focus-inbox dir + `status?` output |
| fact to remember | Ada bank doc (`ada-ha-bank-<name>`) | ask Ada, or `info-find` over mddb |
| how-to / config / decision record | SSOT (`docs/ssot/…`) | `ssot-search` / repo grep |
| report-worthy finding | CMS page (`ada-cms-pages[-kk]`, meta.domain + kind + summary) | reports-index page / miniapp / ask Ada |
| pending question on you | `requests:` block on a card | the board — it resurfaces itself |

## The recall ritual (in order)

1. **`status?`** → one report from the board + inbox. Pending asks on
   you are in card `requests:` blocks — they are never lost, they wait.
2. **`find <thing>`** → agent runs `info-find`: searches MDDB docs,
   SSOT, code, health, then web. Covers banks, CMS pages, and files in
   one pass.
3. **Ask Ada** → she reads reports-index/CMS first (report-first
   ritual), then memory banks, then outside search. If the answer came
   from outside she writes it back to CMS — the second ask is cheaper.
4. **The board** → the only trustworthy list of pending work. If it's
   not on a card or in the inbox, it does not exist — by design.

## Rules that protect you from the human weakness

- **Capture is immediate**: ideas get carded/inboxed *the moment you say
  them* — not at session end, not "I'll remember".
- **Landing spot is announced**: the agent says where it went
  ("carded to MEM-0498", "inboxed", "page kk-ha/site-flow"). If you
  didn't hear where it went, ask — that's a process failure.
- **Session is not memory**: nothing survives except the board, inbox,
  SSOT, CMS, and card comms. Written down = durable; spoken = lost.
- **One index**: `ssot.procedures.yml` is the map of standard
  procedures; this file is the map of destinations. When in doubt,
  `find` beats browsing.
