# Dispatch outcome — audit-oc-mutating-command-0b3n5bce

Card: `audit-oc-mutating-command-0b3n5bce` (AUD-1121) — auto-filed by
`opencode_session_audit.py` for opencode session
`ses_e73e952dfffeHO5pQF0B3N5BcE` ("Supervised OpenCode lane pilot
ops-readonly on idc02", 2026-10-30T09:14Z). Evidence: `mutations:
net_writes`.

## Verdict: verified, contained, already fixed — recommend close

**What the session actually did.** Pulled the raw session from
`~/.local/share/opencode/opencode.db` on idc02 (read-only). The agent's
first tool call was `bash python3 -c` running `urllib.request` to POST
`{"id":"devnest-fl-pilot-health","from":"devin","text":"Starting
ops-readonly host health assessment on idc02"}` to
`https://idc03.taila0626a.ts.net:10000/comment`. The ops-readonly
profile's bash allowlist (`'*': deny` + read-only verbs) rejected it —
`state.status = "error"`, the call never executed, zero bytes left the
host. The agent then completed the read-only fixture with allowlisted
calls (glob/read). The audit's `net_writes` entry is an **attempted**
mutation, not a landed one.

**Root cause.** The session prompt carried the devin-executor `RAILS`
block verbatim — including "Post progress so the board stays live:
curl -X POST {api}/comment". `_start_opencode_lane` formatted
`spec + RAILS` for every opencode profile session, so the model was
explicitly instructed to do something the profile forbids. The small
model (or-gemini-3.5-flash-lite) obeyed the rails first, hit the deny,
then proceeded.

**Fix already landed.** Commit `cb2d2f2c2d` (2026-10-30 10:09 UTC —
~2h after this session, ~2min after sibling `aahmnvt5`) switched opencode
lanes to `RAILS_OPENCODE`, which tells profile agents the runner records
progress itself and forbids board-api/network calls. Verified current:

- installed `~/.local/bin/runner-agent` on idc02 is md5-identical to the
  repo copy and contains `RAILS_OPENCODE`;
- every profile-agent prompt path (`_start_opencode_lane`, staged
  `opencode:profile-run`) now avoids devin `RAILS`;
- post-fix scan: 1346 ops-readonly tool parts in opencode.db since
  2026-10-30T10:09Z contain **zero** board-api/comment attempts — no
  recurrence.

Sibling card `audit-oc-mutating-command-aahmnvt5` is the same class
(curl `/comment` attempt, denied) and resolves identically.

## Deliverables

- `docs/ssot/jobs/devnest/2026-11-24-audit-oc-mutating-command-0b3n5bce.yml`
  — full verdict trail (evidence, root cause, fix commit, verification).
- This outcome file.
- Card comms posted via board-api `/comment`.

## How to verify

```
# raw session parts (denied call + status:error)
python3 - <<'EOF'
import sqlite3, json
db = sqlite3.connect("file:$HOME/.local/share/opencode/opencode.db?mode=ro", uri=True)
for r in db.execute("select data from part where session_id=? order by time_created",
                    ("ses_e73e952dfffeHO5pQF0B3N5BcE",)):
    d = json.loads(r[0])
    if d.get("type")=="tool": print(d["tool"], d["state"].get("status"),
        (d["state"].get("input") or {}).get("command","")[:120])
EOF
# fix commit + rails selection
git show cb2d2f2c2d -- scripts/board/runner-agent.py
grep -n "RAILS_OPENCODE" scripts/board/runner-agent.py
```

## Notes / optional follow-ups (not blocking)

- `opencode_session_audit.py` stores per-mutation `status` in JSON but the
  MD finding summary doesn't mark attempted-denied vs completed — a
  one-line annotation would make these cards self-explanatory.
- Unrelated: one post-fix ops-readonly session
  (`ses_e4b563209ffe1QFAmNvQG8VkyD`) attempted `python3 -c` reading
  `/proc/uptime` — denied; belongs to that session's own audit trail.

lessons:
- OpenCode profile sessions must never receive the devin-executor RAILS block — it instructs curl/python board-api posts that read-only profiles deny by design; RAILS_OPENCODE exists for exactly this.
- "mutations: net_writes" in the session audit can be an attempted-and-denied call (status:"error" in JSON) — check raw opencode.db part state before treating it as a landed write.
- When auditing runner-agent prompt assembly, check ALL rails injection points (lane path, staged profile-run path, devin fallback) — the fix for one path doesn't cover the others.
