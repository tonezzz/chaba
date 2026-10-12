---
description: Independent QC audit of Devin sessions — for every session since the last audit, check that every produced artifact (report, analysis, job output) landed in a durable home. Files misses as kanban cards. Run on demand ("audit my sessions") or periodically as the QC layer over the artifact-landing rule.
---

# Devin Session Audit

The QC layer over the `artifact-landing` rule. **Never audit your own session** — the point is independent eyes: audit *previous* sessions from their saved summaries. The self-check is step 6c of `finish-and-close`; this skill is the second set of eyes that catches 6c being skipped or faked.

## Scope

"Recent" = **every session summary newer than the last audit marker**.
Marker: `~/.local/share/devin/session-audit-marker` — read it first; if absent, default to the last 24h.

Summaries live at `~/.local/share/devin/cli/summaries/history_*.md`
(mtime = session time). If on a host without Devin CLI sessions, audit the
summaries reachable locally or skip with a note.

## Steps

### 1. Resolve the window

```bash
MARKER=~/.local/share/devin/session-audit-marker
[ -f "$MARKER" ] && cat "$MARKER" || date -d "-24h" +%FT%T
```

### 2. List summaries in the window

```bash
ls -lt --time-style=+%FT%T ~/.local/share/devin/cli/summaries/history_*.md
```

Pick every file with mtime > marker.

### 3. Read each summary — extract the artifact ledger

For every session, list what it claims to have produced:

- reports / analyses / benchmarks / triage output
- job output (colab, batch, scripted runs)
- new docs, KB entries, procedures, dashboards
- card mutations (status changes, comms)
- artifacts left on ephemeral infra (colab runtimes, /tmp)

### 4. Verify each artifact's landing

| Claimed artifact | Durable home check |
|---|---|
| CMS report | `mddb get_document ada-cms-pages/<key>` returns the page |
| Repo file/doc | file exists AND is committed (`git log --oneline -- <path>`) |
| Card change | card file shows the mutation + `comms:` entry |
| Parked work | entry in `docs/ssot/focus-inbox/` |
| Job output | referenced in CMS/card/repo — not `/tmp` or chat-only |
| Colab output | CMS page or gdrive cache artifact exists |

Flag every produced artifact with **no verifiable durable home**.

### 5. Also flag process misses in the summary

- asks the user repeated (signals a missed procedure/duty)
- artifacts "published" but with no key/path recorded (unverifiable claim)
- sessions closed with uncommitted repo changes described as done

### 6. File findings as cards

Every miss → a kanban card via board-api (`board-write` procedure):
title `audit-miss-*`, column `backlog`, priority by blast radius, body =
what was produced, which session, what was never landed. One card per
miss — do not bundle.

### 7. Write the audit report + marker

- Findings list → user reply AND, if misses were found, a CMS leaf
  report (`ada-cms-pages/devin-session-audit-<date>`) — eat our own
  cooking: the audit's output lands durably too.
- Update the marker:

```bash
date +%FT%T > ~/.local/share/devin/session-audit-marker
```

## Output

Report: sessions audited, artifacts verified, misses found (with card IDs
filed), sessions that checked out clean. No misses = say so explicitly —
silent-clean is a valid finding.
