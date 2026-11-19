# Task: info-find research — multi-source answer with mandatory citations

Question: {{TASK}}

Rules (profile info-find — enforced):

- Your only shell command is the shared adapter:

  ```bash
  python3 scripts/devnest/info_find.py run --query "<the question>" --format json
  ```

  `--query` takes ONE plain-text argument — never include `>`, `<`, `|`,
  `;`, `&`, `$`, or backticks. Useful flags: `--quick` (local sources
  only), `--collection <name>` (pick MDDB collections), `--session <id>`.
- Read the JSON: `results[]` are ranked with `source`/`ref`/`excerpt`;
  `sources{}` shows which rungs ran, which were `unavailable`, and which
  were `deferred` (e.g. web search — record it, do not emulate it).
- You may also use the `read`/`grep`/`glob`/`list` tools on the
  checkout and the allowlisted SSOT MCP tools.
- Every factual claim in `answer` must trace to a citation `ref`.

Emit ONLY this JSON object as your final message — ALL SEVEN keys are
REQUIRED, and `citations` entries are OBJECTS `{source, ref, note}`,
never plain strings:

```json
{
  "question": "<the question, echoed>",
  "answer": "<prose answer; 'not found' plus what you checked is valid>",
  "citations": [
    {"source": "ssot", "ref": "docs/ssot/<file>.yml:<line>", "note": "…"},
    {"source": "mddb", "ref": "mddb://<collection>/<key>", "note": "…"}
  ],
  "sources_consulted": ["mddb", "ssot", "code"],
  "unavailable_sources": [],
  "deferred_rungs": ["web"],
  "read_only": true
}
```
