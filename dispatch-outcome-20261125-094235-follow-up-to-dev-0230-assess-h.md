# Dispatch outcome — devnest-upstream-skills-review (attempt 2)

## What changed

Committed the deliverable the first attempt researched but never landed (its
checkpoint failed: worktree was 23 commits behind origin/master, "session
produced no commits — NOT verified"). This run re-verified the evidence with
fresh shallow clones and committed:

- `docs/reports/upstream-agent-skills-review-2026-11-25.md` — full assessment:
  ranked fit matrix, per-candidate file/script/license inspection, overlap map
  vs local `.agents/skills`, `.devin/skills`, AGENTS rules and DEV-0253, plus a
  recommended work order.
- `docs/ssot/jobs/devnest/2026-11-25-upstream-skills-review.yml` — trail/pointer
  record (SSOT-validated by pre-commit).

Commit `6d4a7797ea` on `dispatch/20261125-094235-follow-up-to-dev-0230-assess-h`.
Not pushed (dispatch rails); merge-sweep/checkpoint owns that.

## Result — ranked verdicts

1. **anthropics/skills `webapp-testing` — ADOPT (adapted).** Apache-2.0,
   active. `scripts/with_server.py` is stdlib-only and localhost-scoped;
   needs Python Playwright on the host. Fills the real UI-verification gap
   (`docs/kb/e2e-test-automation-patterns*` is prose for one project only).
2. **addyosmani/agent-skills `code-review-and-quality` — ADAPT.** MIT, ~120k★,
   pushed 2026-11-23. Pure-markdown 402-line five-axis review; must add Chaba
   gates (field ownership, single-writer, card-union) or it gives generic advice.
3. **anthropics/skills `skill-creator` — ADAPT process-only.** Apache-2.0.
   Eval/iterate/description-improver loop is the value for DEV-0230 lineage;
   all scripts shell out to `claude -p` and write `.claude/commands/` — do not port.
4. **vercel-labs/agent-skills `web-design-guidelines` — ADAPT (vendor).** MIT.
   51-line SKILL.md + 191-line pinned rule snapshot (SHA-256 recorded), zero
   deps, no runtime network.
5. **anthropics/skills `mcp-builder` — ADAPT as read-only reference.** Apache-2.0.
   `reference/*.md` design docs are durable; scripts need `pip install
   anthropic mcp` — shelf, don't install.
6. **bregman-arie/devops-sre-skills — REJECT.** Apache-2.0 but dormant since
   2026-03-20 (~30★), all 17 skills `maturity: draft`, empty manifest, custom
   frontmatter schema, k8s/aws/gcp/argocd-targeted vs Chaba's systemd/quadlet
   stack. Its read-only runbook *shape* is worth stealing for a future
   chaba-sre skill.

No third-party installers run; nothing imported — shallow clones in `/tmp` only.
Every adopt/adapt carries a small pre-integration test in the report.

## How to verify

- `git show 6d4a7797ea --stat` — two files added.
- Read `docs/reports/upstream-agent-skills-review-2026-11-25.md`.
- Card comms on `devnest-upstream-skills-review` has the summary.

lessons:
- `reports/*` at repo root is gitignored (`.gitignore:22`) — committed reports belong in `docs/reports/`; a deliverable written to `reports/` silently fails the "produced commits" gate.
- Prior attempt failed purely on logistics (23-commits-behind worktree → checkpoint commit refused), not on research quality — the comms already contained the verdicts; re-doing the assessment cheaply and committing is the fix.
- anthropics/skills has no repo-level LICENSE — each skill dir carries its own LICENSE.txt (Apache-2.0); check per-skill, not per-repo.
- vercel-labs/skills is the `skills` CLI installer repo, NOT a skill collection — the collection is vercel-labs/agent-skills; easy to clone the wrong one (both basename `skills`).
- bregman-arie/devops-sre-skills uses a custom frontmatter schema (`tools_allowed`, `safety.default_mode`) incompatible with SKILL.md name/description convention — reject on format grounds alone.
