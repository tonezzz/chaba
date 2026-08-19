# Prompt / command preprocessor

## Purpose
A read-only preprocessing step that grounds user requests in active focus, backlog, jobs, and command patterns before the assistant acts.

## Script

- `scripts/prompt_preprocessor.py`
- Called by `scripts/mcp_debug/preprocess.py` (MCP `mcp_preprocess`) and directly from the shell.

## Input / output contract

### Input
A single request string, either from the shell or via the `mcp_preprocess` MCP tool.

```bash
python3 scripts/prompt_preprocessor.py "promt preprocessor"
```

### Output (JSON)

| Field | Type | Meaning |
|---|---|---|
| `ok` | bool | Whether preprocessing succeeded |
| `request` | string | Original request |
| `canonical_request` | string | Expanded, unambiguous prompt |
| `confidence` | float | Match score (0-1) |
| `suggested_action` | string | `continue_focus`, `quick_win`, `backlog`, `inbox`, `continue_job`, or `direct` |
| `grounding` | object | Matched SSOT / focus / job source, label, status, priority, branch |
| `command` | object? | If the input is a shell / mcp command, tool and canonical form |
| `similar_items` | array | Runner-up matches for disambiguation |

## Supported features (v1)

- Alias expansion for common typos (`promt` → `prompt`, `preproc` → `preprocessor`).
- Keyword and fuzzy matching against:
  - Active shared / branch focus
  - Quick wins
  - Backlog
  - Inbox drafts
  - Job lifecycle artifacts
- Command detection and canonicalization for `mcp_raw`, `mcp_debug`, `git`, `ssh`, `docker`, `systemctl`, `journalctl`, `curl`, `python`, `node`.

## Example

```bash
$ python3 scripts/prompt_preprocessor.py "promt preprocessor"
```

Resolves to the `Prompt / command preprocessor for context and precision` job with 0.955 confidence and `suggested_action: continue_job`.

## Integration with `mcp_focus`

`mcp_focus` now calls `_preprocess_request` internally for `mode="recommend"`.

```text
mcp_focus(request="promt preprocessor", mode="recommend")
  │
  ▼
preprocess("promt preprocessor")
  │
  ▼
_use canonical_request for matching if confidence > 0.8_
  │
  ▼
return recommendation + preprocessed metadata
```

The `mcp_focus` output now includes a `preprocessed` field with:

- `canonical_request`
- `suggested_action`
- `grounding`
- `command` (for direct command dispatch)
- `similar_items`

If the request is a bare command (e.g. `mcp_raw tony-omen systemctl status web`),
`mcp_focus` also sets `recommendation.command` and `recommendation.canonical_request`
so the assistant can dispatch it without treating it as a focus request.

## Future work

- Use `preprocessed.suggested_action` to short-circuit focus routing for high-confidence matches.
- Add MDDB semantic search for richer grounding.
- Allow the assistant to register the preprocessor as an MCP tool once the contract is stable.
