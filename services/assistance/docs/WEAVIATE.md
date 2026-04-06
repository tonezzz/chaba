# Weaviate Memory Store (Ground Truth Spec)

Operator SSOT:

- `services/assistance/docs/ACTION.md`

API SSOT:

- Prefer the live backend OpenAPI: `GET /openapi.json`

 See also:
 - `WINDSURF_PLAYBOOK.md` (repo working conventions, diagnostics, workflows)

## Objective
Run Weaviate as an internal-only service and use it as the **authoritative** long-lived memory store for Jarvis (todos, notes, future memory kinds), with embeddings generated externally (Gemini embeddings).

## Role in the system
- **Authoritative store**: Weaviate
  - Stores memory items with stable IDs and searchable fields.
  - Supports structured queries (filters) and optional semantic retrieval (vector search).


## Primary user flows

### Store memory (write-through)
1. User says something that creates memory.
2. Backend upserts the authoritative memory item into Weaviate.

### Retrieve memory
- Structured retrieval:
  - time-window queries
  - history
- Semantic retrieval (optional / future): vector search across items.



## Memory item model (current)
A memory item represents a single durable fact/task/note.

Recommended fields:
- `external_key` (string)
  - Stable, application-level key.
- `kind` (string)
  - e.g. `todo`, `note`
- `title` (string)
- `body` (string)
- `status` (string)
  - e.g. `pending`, `fired`, `done`, `cancelled`
- `due_at` (number)
- `notify_at` (number)
- `timezone` (string)
- `source` (string)
  - e.g. `jarvis`
- `created_at` (number)
- `updated_at` (number)

Vector policy:
- Weaviate runs with `DEFAULT_VECTORIZER_MODULE=none`.
- The backend generates vectors via Gemini embeddings and sends them as `vector` with the object.

## Notes

Weaviate is not exposed publicly; it is internal-only.

## Current Weaviate API usage (backend)

### Readiness
- `GET /v1/.well-known/ready`

### Schema
- `GET /v1/schema`
- `GET /v1/schema/JarvisMemoryItem`
- `POST /v1/schema` (create class)

### Upsert object
- `PUT /v1/objects/{id}`
  - Payload includes:
    - `class`: `JarvisMemoryItem`
    - `id`: deterministic UUID derived from `external_key`
    - `properties`: memory item properties
    - `vector`: embedding vector

### Query (GraphQL)
- `POST /v1/graphql`
  - Used for listing items by structured filters.

## Runtime configuration

### Weaviate container (stack)
- `WEAVIATE_URL`
  - Jarvis uses this to reach Weaviate over the internal Docker network.
  - Default: `http://weaviate:8080`

Weaviate container env (current stack direction):
- `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true`
- `DEFAULT_VECTORIZER_MODULE=none`
- `ENABLE_MODULES=` (empty)
- `PERSISTENCE_DATA_PATH=/var/lib/weaviate`

### Embeddings (backend)
- `GEMINI_API_KEY` (or `API_KEY`)
- `GEMINI_EMBEDDING_MODEL`
  - Default: `text-embedding-004`

## Persistence model

### Weaviate
- Use a named volume mounted at Weaviate data dir:
  - `/var/lib/weaviate`

### Jarvis backend
- SQLite file set by `JARVIS_SESSION_DB`.
- If SQLite is not persisted, local history/state may be incomplete.

## Troubleshooting

### Weaviate readiness fails
- Check container healthcheck and logs.
- Confirm internal networking DNS works (`weaviate` hostname resolves from backend container).

Note: `GET /v1/.well-known/ready` returns HTTP 200 with an empty body. Healthchecks should only validate the HTTP status code (do not grep the response body for `true`).

### Disk usage warnings

Weaviate periodically logs disk usage warnings when the underlying filesystem is above its internal threshold (default 80%) at `PERSISTENCE_DATA_PATH` (`/var/lib/weaviate`).
If this triggers:
- Free disk on the host volume backing `/var/lib/weaviate`.
- Avoid raising thresholds unless you have strong operational reasons.

### Schema missing / query failures
- Confirm the backend schema bootstrap ran.
- Check `GET /v1/schema/JarvisMemoryItem`.

### Upsert failures
- Confirm Weaviate is reachable from backend using `WEAVIATE_URL`.
- Confirm embedding config is valid (`GEMINI_API_KEY`/`API_KEY`).
- Confirm Weaviate object path is correct:
  - `PUT /v1/objects/{id}`

## Deployment note
Weaviate should remain internal-only. If it must be exposed, add explicit auth and document the ingress, threat model, and operational guardrails.
