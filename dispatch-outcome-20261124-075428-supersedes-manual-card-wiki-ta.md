# Dispatch outcome — wiki-talk-watch auto-reply loop

Card: `wiki-talk-watch-auto-reply-to-wiki-talk-a9f107` (attempt 3; prior attempts
failed on rate limits / caps, never on real work). Branch
`dispatch/20261124-075428-supersedes-manual-card-wiki-ta`, commit `41f9a133e46`.

## What changed

- **`scripts/wiki/wiki-talk-watch.py`** (new, ~700 lines) — 15-min watcher that
  polls MediaWiki `action=query&list=recentchanges` on
  `wiki.surf-thailand.com` across all talk namespaces
  (`1|3|5|7|9|11|13|15|3001|3003|3005|3007`), `rctype=edit|new`, `rcend=<watermark>`,
  `rclimit=50`. Watermark = max rcid in `~/.local/state/wiki-talk-watch/`
  (`state.json` — idempotent reruns, `done`/`alerts`/`stats` records).
  Flags: `--dry-run`, `--seed`, `--max`, `--json`.
- **Classify v1** (JevTeam stand-in) — LiteLLM `gemini-3.5-flash-lite` via
  `scripts/ada/litellm_chat.py` gateway; outputs `{respond, lane:
  ada-code|no-response, reason}`. Skips own-bot edits (user=Ada), minor/system
  edits, and non-talk leaks.
- **Draft + post** — reply drafted via `opencode run --standalone --format json`
  headless (card-run.py pattern); falls back to LiteLLM
  generateContent via `scripts/ada/gemini_rest.py` when opencode is absent
  (live path on idc03 — opencode is tony-dell-only). Posted with
  `action=edit&section=new&appendtext`, signed `— Ada (<lane>) ~~~~~`, using
  Ada bot creds (`~/.config/secrets/wiki-h3-gizmo.env`, bot-password login
  flow reused from `board-api.py::_wiki_login`).
- **Visibility guard** — members-ns talk pages (3001/3003/3005/3007) get
  members-level replies only; public-ns drafts pass a leak scan (tailnet IPs,
  ts.net, hostnames, secret shapes) — hits route to focus-inbox, never posted.
- **Failures** — deduped board-api `POST /inbox` flags (report-watch
  dedupe-by-slug pattern); no blind retries.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — `wiki-talk-watch` entry on
  idc03, `on_calendar: '*-*-* *:07/15:00'` (offset from kanban-commit),
  `condition_path` on the script, TimeoutStartSec 30m.
- **`systemd/generated/idc03/wiki-talk-watch.{service,timer}`** — regenerated;
  oneshot service + `*:07/15:00` Persistent timer. NOT installed on idc03 —
  install path is post-merge `render-jobs.py --host idc03 --install` (no deploy
  without explicit instruction).
- **`docs/ssot/jobs/infrastructure/2026-11-24-wiki-talk-watch.yml`** — runbook:
  context, design, verify steps, install/rollback notes.

## Result

E2E-verified live on `Education talk:ZZ-Talk-Watch-Probe` (pageid 324):
posted test comment (rev 464) → ran watcher with `WIKI_TALK_SELF_USER=""` →
opencode draft → signed reply posted rev 465 ("— Ada (ada-code)").
`--dry-run` clean post-fix (`done: watermark=471 examined=0`). Anon parse on
protected namespaces still `permissiondenied`. Classifier sanity: real question
→ `respond:true, ada-code`; "lol nice" → `respond:false, no-response`.

## How to verify

1. `python3 scripts/wiki/wiki-talk-watch.py --dry-run` — prints candidates,
   writes nothing.
2. On the live wiki, fetch `Education talk:ZZ-Talk-Watch-Probe` — rev 465 is
   the signed watcher reply.
3. After merge: `python3 scripts/ops/render-jobs.py --host idc03 --install`
   (or equivalent) then `systemctl --user list-timers wiki-talk-watch.timer`.
4. Acceptance loop: comment on any talk page → next `:07/:22/...` tick drafts
   + posts a signed reply; anon still denied on protected ns.

## Notes / follow-ups

- Real JevTeam lanes still under construction — v1 classifier is the
  LiteLLM stand-in per card spec.
- First real tick on idc03 uses the LiteLLM generateContent fallback (opencode
  absent there); if opencode lands on idc03 the script auto-prefers it.
- `WIKI_TALK_SELF_USER` env override exists for testing own-bot skip.

lessons:
- opencode is NOT installed on idc03 — the LiteLLM generateContent fallback in `scripts/ada/gemini_rest.py` is the live draft path there; don't assume opencode presence on job hosts.
- Custom talk namespaces 3001/3003/3005/3007 are Lockdown-protected — anon recentchanges leaks titles only; replies there must stay members-level (leak scan on public drafts).
- `rcprop=comment` gives only the edit summary, not the talk-section text — the watcher must `action=parse` the page to extract the newest talk section for classification/drafting.
- Wiki bot login is bot-password via HTTPCookieProcessor + csrftoken (`board-api.py::_wiki_login`); reuse it rather than re-deriving the flow.
- `section=new&appendtext` on a talk page creates a new signed section — confirmed working for auto-replies (rev 465).
