# Plan-route checklist — docs-only feature rollout

> Artifact class: **checklist/template**, not a record of an executed
> rollout. Originally the nominal destination of the opencode-lane
> `plan-route-docs-only` eval case (`evals/opencode-lane/jobs/
> plan-route-docs-only.yml`, profile `plan-route-only`): "draft a
> docs-only checklist for a proposed feature rollout — no deployment or
> code changes." Landed 2026-11-25 under `audit-miss-claimed-docs-never-landed`
> after the audit found the path referenced but never written.
>
> Use this when a proposal needs a written plan before anyone touches a
> host. Fill every section; an unanswered section is an open question,
> not a default.

## 1. Scope

- [ ] One-sentence objective (what changes for whom).
- [ ] In scope / explicitly out of scope.
- [ ] Named surfaces: hosts, services, URLs, cards, SSOT files touched.

## 2. Classification (plan-route fields)

- [ ] `task_class`: `report` | `read_only` | `artifact_write` | `manual` | `human_only`.
- [ ] `risk_level`: low | medium | high — justify in one line.
- [ ] `target_host`: named host, or `null` with reason (docs-only work
      has no execution host).
- [ ] `allowed_paths`: narrowest file set that satisfies the task.
- [ ] `mcp_allowlist`: tools the executor may call; `[]` for plan-only.
- [ ] `human_gate_required`: yes/no — which step needs Tony.

## 3. Options

- [ ] Exactly two options, each with `label`, `benefit`, `tradeoff`.
- [ ] Recommendation + why the tradeoff is acceptable.

## 4. Preconditions

- [ ] Repo/host state verified live (not assumed): branch, commit,
      service status, disk, load.
- [ ] Secrets/access confirmed present on the executing host.
- [ ] Rollback path stated before any irreversible step.

## 5. Execution plan (only if a gate approves)

- [ ] Ordered steps, each independently verifiable.
- [ ] Per-step verify command (producer proof AND consumer proof —
      open the surface a user touches, don't just check the unit).
- [ ] Stop conditions: what aborts the run and who decides.

## 6. Done condition + verification

- [ ] `done_condition`: observable end state, not "code written".
- [ ] `verification`: the command/check that proves it, runnable by a
      cold session.
- [ ] Artifact home: durable path (repo doc, card comms, CMS page) —
      never chat-only or `/tmp`-only.

## 7. Assumptions, open questions, existing work

- [ ] `assumptions`: listed, each falsifiable.
- [ ] `open_questions`: each with a proposed default and owner.
- [ ] `matching_existing_work`: checked board/SSOT/KB before proposing;
      extend an existing artifact rather than forking (status:
      `not_evaluated` is honest when not checked).

## 8. Viewpoints (four, ≥ one sentence each)

- [ ] `user_value` — what the requester actually gets.
- [ ] `technical` — fit with current architecture/conventions.
- [ ] `operations_safety` — blast radius, failure modes, monitoring.
- [ ] `cost_effort` — time/spend vs. value; cheaper alternative?

---

*Contract this checklist mirrors: `evals/opencode-lane/profiles/
plan-route-only/fixture/verify.py` required fields and
`task.yaml#contract.required_fields`.*
