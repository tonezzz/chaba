# CHAT_PROTOCOL.md — Chat Session Protocol

> How to run assistant chats without losing context across sessions or computers.

→ Back to [ACTION.md](ACTION.md)

---

## Goals {#goals}

- Never lose work-in-progress context between sessions.
- Make it easy for a second operator (or computer) to pick up where the first left off.
- Avoid drift between what the assistant "knows" and what is actually deployed.

---

## Session start checklist {#session-start}

1. **Pull latest main** on the working machine before opening a new chat.
2. **Paste the current ACTION.md URL** (or the relevant runbook) into the chat as the first message so the assistant has the doc map.
3. **State the goal** clearly in the first message: what you are trying to accomplish this session.
4. **Attach any relevant context files** (e.g. `.env.example`, stack JSON) if the assistant will need them.

---

## Mid-session handoff {#mid-session-handoff}

If you need to hand off to another machine or operator mid-session:

1. Ask the assistant: *"Summarise what we've done and what's left, in a short bullet list."*
2. Copy the summary into a GitHub issue comment or a `TODO.md` entry.
3. On the receiving machine: start a new chat, paste the summary + ACTION.md link as the first message.

---

## Session end checklist {#session-end}

1. Commit and push all changes (or open a PR).
2. Update [CHECKLIST.md](CHECKLIST.md) if any steps changed.
3. If docs drifted, open an issue and update the relevant runbook.
4. Add a row to the [ACTION.md history table](ACTION.md#history) for any doc changes.

---

## 2-computer anti-drift guardrail {#two-computer-guardrail}

> Originally introduced in [#114](https://github.com/tonezzz/chaba/issues/114) (commit `35d5a70`).

When working across PC1 and PC2:

- **Deploy only from `C:\chaba`** (the single deploy working copy).
- Worktrees (`C:\chaba_wt\...`) are for development only — never deploy from a worktree.
- After finishing work on one machine, push and pull on the other before continuing.
- Use `scripts/deploy-branch.ps1 -Branch <branch>` for branch smoke deploys.

---

## Reference

- [CHECKLIST.md](CHECKLIST.md) — operator checklists
- [docs/README.md](../../../docs/README.md) — CI/CD policy and deploy flow
