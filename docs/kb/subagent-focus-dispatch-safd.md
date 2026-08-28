---
category: operations
---

# Sub-Agent Focus Dispatch (SAFD)

## Overview

SAFD is the convention for delegating focus items to background or foreground sub-agents. It is used when a focus is self-contained, does not need real-time user interaction, and is safe to run independently of the main assistant session.

## When to dispatch

- **Do dispatch** when the focus is bounded, all information is available, no mid-task user approval is needed, and the risk is low or medium.
- **Do not dispatch** for high-interaction, high-risk, or ambiguous work. Keep that in the main session.

## Focus subagent fields

```yaml
subagent:
  runnable: true                  # can this be delegated?
  profile: subagent_general       # or subagent_explore for read-only
  parallel: false                 # can it run alongside other subagents?
  requires_approval: false        # must the user approve before it starts?
  can_change_host: false          # can it run on a different host?
  notes: <human-readable notes>
  estimated_duration: "1 session" # optional
  output_format: "summary"        # expected artifact
```

## Execution modes

- **Foreground subagent**: manual, same session, user can monitor
- **Background subagent**: triggered by the dispatcher or the overnight job, runs independently
- **Automatic dispatch**: future enhancement; not enabled until safety guards are mature

## Contract and output

When a focus is delegated, the dispatcher writes a `SUBAGENT_CONTRACT.md` with:
- Scope and boundaries
- Allowed operations and risk level
- Communication rules (no clarifying questions, stop on destructive changes)
- Output requirements (diff, report, summary)
- Safety checks

The sub-agent should append a `subagent_summary` to each subtask it touches, including `actions_taken`, `blockers`, and `next_steps`. It should not commit or push.

## Decision rules

```
Is focus self-contained?
├─ No  → Main agent
└─ Yes → Is user interaction required?
    ├─ Yes → Main agent
    └─ No  → Is risk high?
        ├─ Yes → Main agent (or subagent with approval)
        └─ No  → Is approval required?
            ├─ Yes → Get approval, then subagent
            └─ No  → Dispatch subagent
```

## Integration

- Intake: `mcp_focus` or `focus-dispatcher --intake`
- Dispatch: `focus-dispatcher --sub-agent`
- Overnight: `overnight-focus-review.py` can run `focus-dispatcher --sub-agent`

## Canonical sources

- `docs/ssot/infrastructure/ssot.subagent-focus-triage.yml`
- `docs/ssot/infrastructure/ssot.focus.triage.yml`
- `docs/ssot/infrastructure/ssot.focus-dispatcher.yml`
- `scripts/focus_dispatcher/prompts.py`
