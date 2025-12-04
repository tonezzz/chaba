# Researcher agent

Surface relevant facts, code references, and knowledge-base excerpts to enrich other agents' reasoning.
This agent should have read-only access to curated docs, embeddings, and optionally web search connectors.

Resources:
- `knowledge/` mirrors indexed documents and ingestion scripts.
- `memory/` tracks recent retrieval history.
- `tools/` can host search adapters (e.g., doc search, Git grep wrappers).
