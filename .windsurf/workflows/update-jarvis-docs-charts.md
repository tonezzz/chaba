---
description: Update / verify Jarvis docs + Mermaid charts after contract changes
---

Run this after changing Jarvis contracts (WS message types, endpoints, status lines) in:

- `services/assistance/jarvis-backend/main.py`
- `services/assistance/jarvis-frontend/App.tsx`
- `services/assistance/jarvis-frontend/services/liveService.ts`

1) Identify what changed

```bash
git diff --stat
git diff
```

2) Update the “known coupled” docs (don’t skip these)

- `services/assistance/docs/SYSTEM.md`
  - reload flow diagram
  - fail-closed / startup prewarm behavior
  - memory/knowledge status line formats
- `services/assistance/docs/TOOLS.md`
  - WS inbound/outbound message types
  - deterministic tools charts
- `services/assistance/docs/CHARTS.md`
  - WebSocket contract diagram
  - deploy/runtime boundaries if ports/endpoints changed
- `services/assistance/docs/UI.md`
  - UI structure diagram if panels/tabs/logging changed

3) Mermaid safety check (GitHub renderer)

GitHub Mermaid often fails if node labels contain raw newlines inside `[...]` or `{...}`.

```bash
# Find Mermaid blocks quickly
rg -n "```mermaid" services/assistance/docs

# Detect multi-line node labels in docs (common parse error source)
rg -n "\\[[^\\]]*\\n\\s*[^\\]]*\\]" services/assistance/docs
rg -n "\\{[^}]*\\n\\s*[^}]*\\}" services/assistance/docs
```

Fix pattern by replacing:

- `Node[Line1\nLine2]`

with one of:

- `Node["Line1<br/>Line2"]`
- or a single-line label.

4) Contract string grep (ensure docs reflect reality)

```bash
# WS types / key strings that often drift
rg -n "get_active_trip|set_active_trip|active_trip" services/assistance/docs services/assistance/jarvis-frontend services/assistance/jarvis-backend
rg -n "system_sheet_unavailable|reload_system_failed" services/assistance/docs services/assistance/jarvis-backend
rg -n "Sheets are not auto-loaded" services/assistance/docs services/assistance/jarvis-backend
```

5) Final review

```bash
git status --porcelain
git diff --stat
```

6) Commit

```bash
# Example message (adjust as needed)
# git add -A
# git commit -m "docs: sync charts with jarvis contract"
# git push
```
