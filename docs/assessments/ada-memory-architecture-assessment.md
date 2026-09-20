# Ada Memory Architecture Assessment

**Date:** 2026-09-20
**Scope:** The full Ada memory system as deployed — MDDB memory banks, NotebookLM deep tier, Obsidian vault authoring tier, sync/backup/drift machinery, and the recall path.
**Sources:** `docs/ssot/apps/ssot.apps.ada-memory*.yml`, `docs/ada-memory/`, `scripts/ada/`, `ada-pi` backend, live deployments on mn01 + tony-dell.

## Architecture (as built)

```
Voice/tools ──► MDDB banks (ada-ha-bank-*, fast, mutable, vector search)
                     │ miss / low confidence
                     ▼
              recall-summary collections (rollup mid-tier)
                     │ miss
                     ▼
              NotebookLM group notebooks (deep archive, ~20s)

Humans ──► docs/ada-memory/ vault (git) ──► sync-ada-memory-to-mddb.py ──► MDDB
                ▲                                                │
                └── inbox/ export (source=voice docs for review) ◄┘

mn01 live vault (apps/obsidian :8004) ◄──► hourly pull-vault.sh --commit --push
```

Ops loop: `ada-memory-sync` (hourly, mn01) · `ada-memory-pull` (hourly, tony-omen) · `ada-memory-backup` (nightly, tony-omen) · `ada-memory-rollup` (03:45, tony-omen) · `ada-memory-drift` (Sun, mn01 → chaba-events).

## Strengths

1. **Tiering matches access patterns.** MDDB serves voice-turn recall in milliseconds with mutable documents; summaries absorb mid-range questions; NotebookLM only handles deep/historical synthesis where its ~20s latency is acceptable. The "MDDB answers *what did I tell you*, NotebookLM answers *tell me the whole story*" split is clean and proven in practice.
2. **Declarative registry with real enforcement.** Bank definitions are SSOT → rendered JSON → instance-filtered at runtime, with fail-fast on unassigned/unresolvable banks and a degraded health flag. The `ada-ha-michael` isolation test (Tony-only banks absent, tool call errors correctly) was verified live — this is enforced isolation, not a naming convention.
3. **Write semantics are genuinely designed.** Correct/supersede/retract verbs, `status` lifecycle, `supersedes`/`superseded_by` linkage, MDDB revision history — memory corrections leave an audit trail instead of silently overwriting.
4. **The write-policy gate reuses a proven pattern.** `confirmed`/`direct` rides the same ToolRunner confirmation gate as dangerous HA entities — no new trust model to reason about.
5. **Self-measuring recall.** Miss logging + `recall-drift-report.py` + weekly timer + chaba-events tripwires (miss>50%, mean<0.55) means recall degradation produces a visible event instead of quietly rotting. Most memory systems have no feedback loop at all.
6. **Human curation tier with conflict safety.** `written_by`-aware sync reports CONFLICT on divergence, auto-resolves only uncurated voice exports (`--resolve-voice`), and hard-resolves explicitly via `--take-remote/--take-vault`. The vault is authoritative for humans; MDDB is authoritative for recall.
7. **Backup exists and was drilled.** `backup-mddb-banks.py` + `restore-mddb-banks.py` with a verified restore drill — not just a backup script that was never tested.

## Operational weaknesses

1. **MDDB is a single point of failure.** One instance on tony-dell; if it dies, fast-tier recall degrades to NotebookLM (slow) or fails. Backups mitigate data loss, not availability. No replica exists.
2. **Embedding dependency is external and quota-bound.** The Gemini-compatible Ollama proxy path already burned quota once (forced reindex incident). Recall quality silently degrades if the embedding path changes dimensionality or the proxy is down — there is no embedding-health canary.
3. **High timer/hook surface area.** Five timers across three hosts plus render-at-deploy. Each is individually simple, but the system now has many small failure points. The `deploy-ada.sh` ssh-arg-joining bug (michael silently never restarting) is exactly the class of failure this architecture invites — it was found by accident, not by a check.
4. **mn01 vault is an rsync copy, not a checkout.** Edits via `apps/obsidian` live on a copy that is reconciled hourly. A crash between edit and pull loses up to an hour of vault-side edits (MDDB-side writes survive). The "Commit" button's earlier git-on-non-repo bug is another symptom of the copy-not-checkout design.
5. **Registry says `status: planned/testing` while the runtime is live.** Doc debt — the banks registry's status fields lag reality, which matters because tools and people read SSOT as truth.
6. **Confidence is advisory only.** `confidence: 0.0–1.0` is stored and displayed, but enforcement (escalate-below-threshold) is prompt-level — nothing in code guarantees low-confidence facts aren't spoken as fact if the model ignores the instruction.

## Privacy

**Good:**
- `personal/*` is gitignored; chaba is public on GitHub — correct call.
- Personal banks have no `notebooklm_group` — private content can't leak into the Google-hosted tier by config.
- Personal-bank backups go to `~/.local/share/ada-backups/` outside the repo.
- MDDB is tailnet-only; `/api/memory/banks` requires `ADA_API_KEY`.

**Gaps:**
- Gitignore is policy-by-convention — no pre-commit or CI check fails on `docs/ada-memory/personal/**` staging. One `git add -f` or a gitignore typo publishes private notes to a public repo permanently.
- Voice `source` docs routed to shared banks are still human speech — a mis-heard or sensitive utterance lands in `ada-ha-bank-general` and, via the memory group, potentially NotebookLM. The `confirmed` write policy mitigates this on shared banks, but `personal` and `note` are `direct`.
- `apps/obsidian` on mn01 has `_check_write_auth` for writes; verify read paths don't expose `personal/` to anyone who reaches `:8004` on the tailnet (Tailscale ACLs help, but the app shouldn't rely on them alone).

## Recall quality

- **Fast tier:** vector search works (live hits at 0.70/0.47 observed); `>=0.85` dedupe threshold for in-place correction is sensible.
- **Mid tier:** rollup summaries with `source_keys` provenance — the right shape, but rollups are lossy; a wrong or stale rollup can outrank the underlying session summary. Worth watching via drift report.
- **Deep tier:** NotebookLM synthesis quality is high but operationally fragile — cookie expiry has been a recurring incident, and NLM failure currently degrades recall silently (miss → no answer). NLM auth health should emit to chaba-events like the drift report does.
- **Ranking risk:** `last_verified` bumping on confirmation is good; nothing yet demotes frequently-missed docs or surfaces conflicts between vault-curated and voice-written versions of the same fact.

## Auditability

- **Strong:** MDDB revisions per write, status lifecycle, provenance fields, git history on vault + SSOT, this very trail of `ssot.apps.ada-memory-progress.yml`.
- **Gap (known):** no actor/session write log — `written_by`/`session_id` meta fields (Option A) were chosen but verify they're actually populated on every write path, including `sync` and `obsidian` edits, not just `ada_remember`.
- **Blind spot:** NotebookLM tier is append-only and un-audited — accepted, but means a bad "Correction:" source can't be reliably removed (source-delete has failed with 401 before).

## Human workflow

- The voice → `inbox/` → review → promote → consolidate loop is well-shaped: Ada's writes never silently become curated fact.
- `apps/obsidian` gives a real editing surface without installing Obsidian.
- **Friction:** inbox review and `consolidate-memory.py` are manual. If voice notes accumulate faster than they're reviewed, the inbox becomes a second junk drawer. Consider a weekly "inbox has N unreviewed notes" event.

## Synchronization & conflict risks

- `pull-vault.sh --commit --push` hourly is bidirectional reconcile: pull remote→local, then push local→remote. On divergence the remote edit wins (pulled before push) — acceptable, but means a same-hour edit on both sides resolves silently toward mn01's version in the *file*, while MDDB keeps its own copy. The CONFLICT path in sync is the real guardrail; keep it noisy.
- `--push` deliberately has no `--delete` — remote-only files survive. Correct for safety; means mn01 accumulates files deleted in git until manually pruned.
- Rendered `memory-banks.json` can drift from SSOT if someone edits SSOT without re-rendering — the runtime warn-on-drift check covers this; make sure it actually fires in `/api/health`.

## Scalability & maintenance

- Document counts are tiny (tens of docs); file-based vault + MDDB scale to thousands easily. No near-term concern.
- Real scaling risk is **operational**: 5 timers, 3 hosts, 2 vault copies, rendered config, SSH-based event emission. Each piece is cheap; the sum needs the audit SSOT to list every timer/service or failures become invisible. (Check `ssot.audit.hosts.yml` covers all five timers — if not, add them.)

## Recommendations (priority order)

1. **Flip registry statuses to `active`** — banks are live; `planned`/`testing` is now misleading. Also mark the `note` bank's role as the permanent sandbox.
2. **Add a pre-commit/CI guard** rejecting staged files under `docs/ada-memory/personal/**` — belt-and-suspenders on top of gitignore for a public repo.
3. **NLM auth health → chaba-events producer** — cookie expiry is the most fragile dependency and currently fails silently for recall.
4. **List all five memory timers in `ssot.audit.hosts.yml`** so the audit watchdog reports a dead timer instead of silence.
5. **Verify `written_by`/`session_id` on every write path** — close the audit gap now while write volume is small; retrofitting provenance is harder.
6. **MDDB availability plan** — at minimum document restore-RTO; consider a weekly replicated dump on mn01 so fast-tier recall can be pointed at a warm copy in an emergency.
7. **Wire remaining producers into chaba-events** (audit watchdog results, cast lifecycle) so the Events tab is the single pane it was designed to be.
8. **Inbox-age tripwire** — emit an event when `inbox/` holds unreviewed voice notes >7 days.

## Verdict

The architecture is sound and, unusually for a personal-AI memory system, actually deployed end-to-end with verification at each layer. The main risks are not design flaws but operational: a single MDDB point of failure, an external embedding dependency, silent-failure modes (NLM auth, dead timers), and privacy guardrails that rely on convention rather than enforcement. Recommendations 1–5 are all cheap and close the biggest silent-failure gaps.
