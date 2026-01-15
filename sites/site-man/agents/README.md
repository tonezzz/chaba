# Agent workspace

This directory hosts every LLM agent that can be mounted inside the site-man service. Each agent must live
under `agents/<agent-id>/` and keep the following layout:

```
<agent-id>/
  config.json            # identity, provider, default prompt, tool and memory bindings
  memory/
    short_term.jsonl     # rolling transcript snapshots
    long_term.meta.json  # pointer to embeddings/vector DB shards for durable memory
  knowledge/             # curated docs or ingestion scripts scoped to the agent
  state/                 # volatile run-state for orchestration
  logs/                  # execution traces (left empty in git)
  tools/                 # optional helper scripts or notebooks
```

Supporting files:

- `registry.json`: canonical list of registered agents and health metadata used by the orchestrator.
- `schema.config.json`: JSON schema describing the required fields in each `config.json`.

When adding a new agent:

1. Copy one of the sample folders (e.g., `navigator`) as a starting point.
2. Update `config.json` with unique IDs, model endpoints, and knowledge pointers.
3. Document any specialized tooling inside that agent's `README.md`.
4. Append the agent entry to `registry.json` so the API can expose it.
