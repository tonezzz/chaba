---
description: Hands-off Copilot delegation loop (issue -> assign -> PR -> merge)
---

# Hands-off Copilot delegation loop

Use this when you want to delegate an implementation task to Copilot via a GitHub Issue and keep your own involvement minimal.

## 1) Create a Copilot-ready GitHub issue

Requirements for good results:

- Clearly state the **Goal**
- Provide **Context** and exact **target files/paths**
- Provide **Constraints** (what must NOT change)
- Provide **Acceptance criteria**
- Provide **Verification** steps

If you want to create issues from the CLI:

- `gh issue create -R tonezzz/chaba -t "..." -b "..."`

## 2) Assign the issue to Copilot (UI)

Assigning Copilot via CLI/APIs can be flaky.

- Open the issue in GitHub UI
- Right sidebar -> **Assignees** -> select **Copilot**
- Paste an "Optional prompt" emphasizing:
  - no extra scaffolds
  - minimal changes
  - open a PR

## 3) Monitor Copilot progress

You should see:

- A Copilot comment with a plan
- A PR opened by Copilot (often within a few minutes)

## 4) Hands-off review checklist (PR triage)

Before merging:

- Confirm the PR only touches intended files
- Confirm no new unrelated services/scaffolds were introduced
- Confirm no secrets or env values are hardcoded
- Confirm CI passes

Useful CLI commands:

- `gh pr list -R tonezzz/chaba --limit 20`
- `gh pr view <num> -R tonezzz/chaba --json title,url,files`
- `gh pr diff <num> -R tonezzz/chaba --name-only`

## 5) Merge / close loop

If OK:

- Merge in GitHub UI, or via CLI:
  - `gh pr merge <num> -R tonezzz/chaba --squash --delete-branch`

If not OK:

- Request changes with a short, specific comment
- If the approach is fundamentally wrong, close the PR and open a new issue with tighter constraints

## 6) (Optional) Tag the merge to trigger deployment

If you need to trigger downstream image builds/redeploy:

- Empty commit to the target branch (example):
  - `git commit --allow-empty -m "chore(ci): force rebuild" && git push`
