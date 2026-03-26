# CHECKLIST.md — Operator Checklists

→ Back to [ACTION.md](ACTION.md)

---

## Resume checklist {#resume-checklist}

Use this when picking up a session (new machine, new day, or new chat window).

- [ ] Pull latest `main`: `git pull origin main`
- [ ] Review open issues / TODO.md for pending work
- [ ] Open [ACTION.md](ACTION.md) → confirm current "what to do next"
- [ ] Check stack health (see [CONFIG.md](CONFIG.md) for endpoints)
- [ ] Paste ACTION.md link + goal into the new chat as first message (see [CHAT_PROTOCOL.md](CHAT_PROTOCOL.md))

---

## Deploy checklist {#deploy-checklist}

- [ ] Branch is pushed and PR is open (or work is merged to `main`)
- [ ] On deploy machine (`C:\chaba`): `git pull origin main`
- [ ] Run the relevant stack start script (see [BUILD.md](BUILD.md))
- [ ] Confirm health endpoints respond (see [CONFIG.md](CONFIG.md))
- [ ] Update [ACTION.md history](ACTION.md#history) if docs changed

---

## Handoff checklist {#handoff-checklist}

Use when handing off to another operator or computer mid-session.

- [ ] Ask assistant for a session summary (bullet list of done + remaining)
- [ ] Paste summary into a GitHub issue comment or `TODO.md`
- [ ] Commit + push all in-progress changes (or stash with a clear message)
- [ ] Confirm the receiving operator can see the issue / branch

---

## Docs audit checklist {#docs-audit-checklist}

Use periodically to keep docs from drifting.

- [ ] All links in ACTION.md resolve (click each one in GitHub renderer)
- [ ] Runbook steps match actual deployed stack configuration
- [ ] History table in ACTION.md has an entry for recent changes
- [ ] No duplicate/outdated entries (remove or mark deprecated with a pointer)
- [ ] SYSTEM.md SSOT pointers are accurate

---

## Reference

- [BUILD.md](BUILD.md) — build/deploy procedures
- [CONFIG.md](CONFIG.md) — endpoints + config
- [CHAT_PROTOCOL.md](CHAT_PROTOCOL.md) — chat session protocol
