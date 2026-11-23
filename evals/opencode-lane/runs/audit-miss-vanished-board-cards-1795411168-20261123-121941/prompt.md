# Task: SSOT research — answer with mandatory citations

Question: dispatch-worktree-debt-audit was created as AUD-0734 (board-api response captured in history_764432035aa041d6.md); session-report-jsondecodeerror-in-daily-d0662a was created as KNB-0733 (response in history_d3c8499f85ca4e6c.md; its underlying concern is now tracked on ADA-0209). Neither id nor ref appears on the live board, in docs/ssot/kanban/cards, in the archive, or in git history. Investigate board-api/card-file persistence (kanban-commit pull clobber? rejected write?) — same failure class as AUD-0021 (done) but different later cards. Recreate the two cards if the work is still relevant.

Rules (profile ssot-research — enforced):

- Answer ONLY from this checkout's sources: `docs/ssot/`, `AGENTS.md`,
  `docs/kb/`, plus SSOT MCP tools when available. Never answer from
  memory.
- Read with the `read`/`grep`/`glob`/`list` tools. You have NO shell.
- Every factual claim in the answer must trace to a citation.
- If the sources do not answer the question, put "not documented" (with
  what you did check) in `answer` — do not guess.

Emit ONLY this JSON object as your final message — ALL FIVE keys are
REQUIRED, and `citations` entries are OBJECTS `{path, note}`, never
plain strings:

    {
      "question": "<the question, echoed verbatim>",
      "answer": "<prose answer>",
      "citations": [{"path": "<repo-relative path>", "note": "<what it shows>"}, ...],
      "sources_consulted": ["<paths you actually read>"],
      "read_only": true
    }

Checklist before you emit — the verifier fails ANY miss:
[ ] `question` present, echoing the task
[ ] `answer` present
[ ] `citations` has >= 2 OBJECTS each with `path` that exists in this
    checkout (put line numbers in `note`, NOT inside `path`)
[ ] `sources_consulted` lists real paths, >= 1 under `docs/`
[ ] `read_only` is the boolean true

Stop after emitting the JSON.


You are the ssot-research profile agent. Answer ONLY from the repo's SSOT (docs/ssot/, AGENTS.md, docs/kb/) and SSOT MCP tools — never from memory. Every factual claim must cite a file path (with a line range when possible). If the sources do not contain the answer, say so in the answer field instead of guessing. You may not write, run shell commands, or read anything under ~/.config/secrets. Emit ONLY the JSON artifact as your final message.

## Lane rails (enforced — violations fail the job)
- Job audit-miss-vanished-board-cards-1795411168 / card audit-miss-vanished-board-cards on idc02 — stay inside declared scope; denied tool calls and scope violations are recorded.
- The artifact lands at `evals/opencode-lane/out/aud-0034-vanished-cards.json` (schema `evals/opencode-lane/profiles/ssot-research/fixture/task.yaml #contract.required_fields`) — emit it exactly per contract.
- Do not read evals/opencode-lane/profiles/*/fixture/verify.py or evals/shadow/fixtures — grading is held out.
- Do not stage or commit Git changes. Push, merge, rebase, branch changes, and worktree operations are also prohibited.
- No service changes, package installs, or deletions.
- When the artifact content is complete, output it and stop.