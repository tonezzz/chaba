---
description: Full audit of Ada voice transcripts — every session since the last check, every failed tool call, every flagged ops event. Default behavior when the user says "check my (recent) transcript".
---

# Ada Transcript Audit

**This is the standing default** for any request like "check my recent transcript", "check my last session", "how did that go", or any complaint about something Ada did or said. Do NOT spot-check a single turn — run the full audit.

## Scope

"Recent" = **every transcript newer than the last audit marker**, not just the newest file. The marker lives at `~/.local/share/devin/ada-audit-marker` on this host — read it first; if absent, default to the last 24h of transcripts.

## Steps

### 1. Resolve the window

```bash
MARKER=~/.local/share/devin/ada-audit-marker
[ -f "$MARKER" ] && cat "$MARKER" || date -d "-24h" +%FT%T
```

If the user names a specific session or time range, use that instead.

### 2. List every transcript in the window

```bash
ssh idc01 'ls -lt --time-style=+%F\ %T ~/.local/share/ada/transcripts/2026-*.md | head -20'
```

Pick all files with mtime > marker. If ambiguous which one the user means (e.g. they just ran a tour), grep for topic keywords to identify the right session — but still audit all files in the window, not just the matching one.

### 3. Read each transcript fully

Do not skim. For every user→Ada turn, note:
- claims of action vs no tool call (phantom-write)
- reported failures and what Ada said next
- asks the user had to repeat or rephrase
- friction turns (confirm-gate round trips, reset prompts)

### 4. Pull every tool call for those sessions

```bash
ssh idc01 'journalctl --user -u ada-ha-tony --since "<window_start>" --no-pager |
  grep "session=<id>" | grep -E "function_call (received|result)"'
```

For each `result`, flag:
- `ok: False` / top-level `error`
- `err` in the payload (cast-browser locator timeouts, etc.)
- `needs_confirm` round trips
- arg-shape anomalies (nested `{name, args}` envelopes, wrong types)
- `delivered: 0` on casts

### 5. Pull flagged ada-ops events for the window

phantom_write_claim, confirm_strip, jev_advisory divergences, voiceprint_drift — via the mddb `ada-ha-ops` collection or the rendered `ada-ops` digest.

### 6. Measure turn latency

From journal timestamps: gap between a user utterance ending and the first `function_call result` / Ada reply. Report anything > ~8s.

### 7. Write the marker + report

```bash
date -u +%FT%TZ > ~/.local/share/devin/ada-audit-marker
```

Report per-session: what worked, what failed (with the raw tool result as evidence), what was awkward-but-correct, and per-failure whether it's a tool bug, schema/desc issue, display-side problem, or correct-by-design friction.

## Output format

Per session:

```
### <session_id> — <topic>, <HH:MM–HH:MM>
- turns: N | tool calls: N | failures: N | flags: N
- FAIL <tool> — <what> — evidence: <raw result line>
- SLOW turn <N> — <latency>s — <cause if known>
- FRICTION — <description>
```

Then a summary: total turns, total failures, top root cause, what was fixed, what needs a card/follow-up.

## Do not

- Do not infer success from `delivered: 1` alone — dig into `responses[].response.ok`.
- Do not trust Ada's narrated claims — verify against `function_call result`.
- Do not skip the marker write — that's what makes "since last check" work.
- Do not file every friction turn as a bug — confirm gates and acl denials are often correct behavior; report them as friction, not failures.
