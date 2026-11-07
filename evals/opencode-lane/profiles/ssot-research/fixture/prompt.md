# Task: SSOT research — answer with mandatory citations

Question: {{TASK}}

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
