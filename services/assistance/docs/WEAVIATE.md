# Weaviate Memory Store (Ground Truth Spec)

## Objective
Run Weaviate as an internal-only service and use it as the **authoritative** long-lived memory store for Jarvis (reminders, todos, notes, future memory kinds), with embeddings generated externally (Gemini embeddings).

## Role in the system
- **Authoritative store**: Weaviate
  - Stores memory items with stable IDs and searchable fields.
  - Supports structured queries (filters) and optional semantic retrieval (vector search).
- **Operational cache / scheduler**: Jarvis backend SQLite
  - Stores machine-readable reminder scheduling state for reliable notification delivery.
  - Rebuilt from Weaviate on backend startup (resync) for upcoming reminders.

## Primary user flows

### Store memory (write-through)
1. User says something that creates memory (e.g. reminder setup).
2. Backend writes local operational state first (if applicable; reminders).
3. Backend upserts the authoritative memory item into Weaviate.

### Startup resync (Weaviate → local scheduler)
1. Backend starts.
2. Backend queries Weaviate for upcoming pending reminders.
3. Backend upserts those into SQLite so the scheduler loop can fire reliably.

### Retrieve memory
- Structured retrieval:
  - upcoming reminders (time-window queries)
  - history (all reminders)
- Semantic retrieval (optional / future): vector search across items.

Reminder retrieval should be Weaviate-authoritative for cross-device consistency:
- When `WEAVIATE_URL` is configured and Weaviate is healthy, reminder list endpoints should read from Weaviate.
- SQLite remains a scheduler cache; it should be hydrated from Weaviate on startup/reconnect so reminders still fire during transient outages.

## Memory item model (current)
A memory item represents a single durable fact/task/reminder/note.

Recommended fields:
- `external_key` (string)
  - Stable, application-level key (e.g. `reminder::<local_reminder_id>`)
- `kind` (string)
  - e.g. `reminder`, `todo`, `note`
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

## Current backend API surface
The Jarvis backend provides reminder endpoints:
- `GET /reminders`
- `GET /reminders/upcoming`
- `POST /reminders/{reminder_id}/done`

When Weaviate is enabled, these reads should prefer Weaviate.
SQLite remains a cache used by the local reminder scheduler loop.

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
  - Used for listing upcoming reminders by structured filters.

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
- If SQLite is not persisted, reminders can still be recovered via startup resync, but local history/state will be incomplete.

## Troubleshooting

### Weaviate readiness fails
- Check container healthcheck and logs.
- Confirm internal networking DNS works (`weaviate` hostname resolves from backend container).

### Schema missing / query failures
- Confirm the backend schema bootstrap ran.
- Check `GET /v1/schema/JarvisMemoryItem`.

### Upsert failures
- Confirm Weaviate is reachable from backend using `WEAVIATE_URL`.
- Confirm embedding config is valid (`GEMINI_API_KEY`/`API_KEY`).
- Confirm Weaviate object path is correct:
  - `PUT /v1/objects/{id}`

### Reminders missing after restart
- Confirm backend startup resync ran (check backend logs for resync warnings).
- Confirm Weaviate contains pending reminder items and that `notify_at` is set.
- Confirm local SQLite persistence if you expect long history.

## Deployment note
Weaviate should remain internal-only. If it must be exposed, add explicit auth and document the ingress, threat model, and operational guardrails.
