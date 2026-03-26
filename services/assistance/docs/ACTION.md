# ACTION.md — Operator Entrypoint

> **Start here.** This is the single operator entry-point for the `services/assistance` stack.  
> All runbooks and reference docs are reachable from this page.

---

## Docs Index {#docs-index}

| Doc | Purpose |
|-----|---------|
| **[ACTION.md](ACTION.md)** ← _you are here_ | Operator entry-point, jump list, history |
| [CHAT_PROTOCOL.md](CHAT_PROTOCOL.md) | How to run chats without losing context |
| [CHECKLIST.md](CHECKLIST.md) | Operator checklists (deploy, resume, handoff) |
| [SYSTEM.md](SYSTEM.md) | System architecture + SSOT pointers |
| [BUILD.md](BUILD.md) | Build / deploy SSOT |
| [CONFIG.md](CONFIG.md) | Stack config + endpoints |
| [TOOLS.md](TOOLS.md) | WebSocket / tools protocol notes |

### Related top-level docs (repo-wide)

| Doc | Purpose |
|-----|---------|
| [`docs/README.md`](../../../docs/README.md) | Infrastructure notes, CI/CD policy |
| [`docs/stacks.md`](../../../docs/stacks.md) | Canonical stack index (pc1/pc2/idc1) |
| [`docs/pc1-runbook.md`](../../../docs/pc1-runbook.md) | PC1 stack runbook |
| [`docs/dev-host.md`](../../../docs/dev-host.md) | dev-host environment reference |

---

## What to do next {#what-to-do-next}

1. **Resume a session** → [CHECKLIST.md — Resume checklist](CHECKLIST.md#resume-checklist)
2. **Deploy a change** → [BUILD.md — Deploy procedure](BUILD.md#deploy-procedure)
3. **Start/stop stacks** → [docs/pc1-runbook.md](../../../docs/pc1-runbook.md)
4. **Check endpoints** → [CONFIG.md](CONFIG.md)
5. **Understand the system** → [SYSTEM.md](SYSTEM.md)
6. **Run a chat session** → [CHAT_PROTOCOL.md](CHAT_PROTOCOL.md)

---

## History / Drift Notes {#history}

Lightweight changelog for operator-facing doc changes. Newest first.

| Date | Change | Ref |
|------|--------|-----|
| 2026-03-23 | 2-computer workflow anti-drift guardrail added | [#114](https://github.com/tonezzz/chaba/issues/114) commit `35d5a70` |
| 2026-03-26 | Initial docs index created (`ACTION.md` + linked runbooks) | [#127](https://github.com/tonezzz/chaba/issues/127) |

---

## SSOT rule {#ssot-rule}

- **GitHub Issues** are the SSOT for doc-change intent, scope, acceptance criteria, and historical context.
- **Repo docs** (`ACTION.md` + linked runbooks) are the SSOT for the current operator procedure.
- When docs drift from reality, open an issue and update docs in the same PR.
