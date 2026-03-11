# Imagen Projects (Ground Truth Spec)

## Objective
Build an **Imagen Project workflow** in Jarvis using the **Gemini Developer API key** (**server-side only**).

## Primary user flow
1. **Choose or create a project**
    - Select an existing template (e.g. *YouTube thumbnail*, *Brand mascot*, *Product hero*, *Sticker pack*), or create a new template.
2. **Parameter assistant**
    - Jarvis asks targeted questions and proposes defaults until required parameters are complete.
3. **Review + confirmation gate**
    - Before any paid generation call, Jarvis presents a final summarized job spec.
    - I must explicitly confirm (e.g. a “Generate now” action).
4. **Run + progress tracking**
    - Jarvis starts generation, tracks status, and reports progress in the UI until completion.
5. **Save for reuse**
    - Generated images and metadata are saved so I can reuse them later.

## Command-style interaction (intended)
- I can tell Jarvis: “Create an Imagen project for …”
- Jarvis creates a draft project/job and asks follow-ups to fill missing parameters.
- Once the project is `ready_for_review`, I can say: “Start generating.”
- Jarvis runs generation and persists the resulting assets + metadata.

## Required parameters (Jarvis should help fill)
- **Prompt**
- **Style** (photoreal / illustration / 3D / anime / minimal, etc.)
- **Aspect ratio** and **image size**
- **Number of variants**

## Optional parameters
- **Negative prompt** (if supported by the selected model)
- **References**
  - Reference images (upload base64)
  - Palette / brand notes
  - “Must include” / “Must avoid” constraints
- **Tags** (for future retrieval)

## Project status model
- `draft` → `ready_for_review` → `confirmed` → `generating` → `completed` / `failed`
- Jarvis should log events with timestamps (status transitions, retries, errors).

## Persistence + retrieval
- **Store generated images for later use** (original output + selected final).
- **Weaviate**
  - Store searchable metadata + embeddings:
    - project name / template
    - prompt (+ negative prompt)
    - tags
    - params (aspect ratio, size, variants, model)
    - derived caption/summary
  - Store a pointer to the image blob (not necessarily the blob itself).
- **Blob storage**
  - Store the actual image bytes (local disk or object storage).

Example retrieval queries:
- “Show me the last 5 thumbnails for Project X.”
- “Reuse the same style as image Y.”
- “Find images like ‘neon cyberpunk logo’.”

## Implementation constraints / preferences
- Use the **Developer API key** via backend env (`API_KEY` / `GEMINI_API_KEY`).
- Do **not** expose any key to the frontend bundle.
- Keep model selection controlled via **server allowlist** and env-driven defaults.

## Open questions (to decide during implementation)
- Where should image blobs be stored (local disk vs S3-compatible)?
- Should confirmation be a two-step API (plan → confirm), or a single call with `confirmed=true`?
- Which models are allowed for image generation/editing (and what defaults)?

## Acceptance criteria
- Creating a project returns a stable `project_id`.
- Jarvis can:
  - collect missing parameters via targeted questions
  - produce a complete, reviewable generation spec
- No generation request is executed without an explicit user confirmation.
- Project status transitions are persisted with timestamps (including failures).
- A completed project stores:
  - at least one generated image asset in blob storage
  - metadata in Weaviate for search/retrieval
- I can retrieve:
  - recent assets by project
  - assets by semantic search (prompt/tags/summary)
  - the exact parameters used to generate a chosen asset

## Draft API surface (backend)
### Implemented (current)
- `POST /imagen/generate`
- `GET /imagen/assets/{asset_id}`
- `GET /imagen/assets/{asset_id}/blob`

### Planned (next)
- `GET /imagen/templates`
- `POST /imagen/templates`
- `GET /imagen/projects?limit=...&status=...`
- `POST /imagen/projects`
- `GET /imagen/projects/{project_id}`
- `POST /imagen/projects/{project_id}/plan`
- `POST /imagen/projects/{project_id}/confirm`
- `POST /imagen/projects/{project_id}/run`
- `GET /imagen/projects/{project_id}/events`
- `GET /imagen/assets?project_id=...&limit=...`

## Current implementation status
- The backend currently supports **ad-hoc generation** via `POST /imagen/generate`.
- “Imagen Projects” (templates/projects/plan/confirm/run/events) are still **planned** and not yet implemented.

## Backend behavior notes (current)
- If the selected `model` starts with `imagen-` (e.g. `imagen-4.0-generate-001`), the backend uses the Imagen API surface (`generate_images` / `:predict`).
- Otherwise, the backend falls back to `generate_content` and extracts `inline_data`.
- Current request fields supported by `POST /imagen/generate`:
  - `prompt`
  - `model` (optional; must be in allowlist)
  - `aspect_ratio` (e.g. `"1:1"`, `"16:9"`)
  - `image_size` (e.g. `"1K"`, `"2K"` when supported)
  - `number_of_images` (1-4)
  - `person_generation` (e.g. `allow_adult`, `dont_allow`, `allow_all` where permitted)
  - `return_data_url` (default true)

## Persistence model (draft)
- **Template**
  - `template_id`, `name`, `description`, `defaults_json`, `questions_json`, `created_at`, `updated_at`
- **Project**
  - `project_id`, `template_id`, `name`, `status`, `spec_json`, `created_at`, `updated_at`
- **Event log**
  - `event_id`, `project_id`, `type`, `payload_json`, `created_at`
- **Asset**
  - `asset_id`, `project_id`, `status`, `prompt`, `negative_prompt`, `tags`, `model`, `params_json`, `blob_uri`, `mime_type`, `sha256`, `created_at`

## Weaviate (draft schema notes)
- Store text fields suitable for embedding:
  - `project_id`, `asset_id`
  - `template_name`, `project_name`
  - `prompt`, `negative_prompt`
  - `tags`
  - `summary` (derived caption/description)
- Store non-embedded metadata:
  - `model`, `aspect_ratio`, `image_size`, `variants`, `created_at`
  - `blob_uri`, `sha256`, `mime_type`
- Store the actual image bytes outside Weaviate (blob storage) and reference via `blob_uri`.

## Limits, cost controls, and safety
- Enforce server-side limits:
  - max prompt length
  - max reference image bytes and count
  - max variants per run
  - max runs per project within a time window
- Only allow model selection via a server allowlist (env/config).
- Require explicit confirmation to execute generation.
- Log request ids and errors for auditing.

## Security and observability
- API key must only exist in backend env (`API_KEY` / `GEMINI_API_KEY`).
- Frontend never calls GenAI APIs directly.
- Persist enough structured data to reproduce a generated asset later.

## Runtime configuration (current)
- **Auth**
  - `API_KEY` or `GEMINI_API_KEY`
- **Model policy**
  - `JARVIS_IMAGEN_MODEL` (default model)
  - `JARVIS_IMAGEN_ALLOWED_MODELS` (comma-separated allowlist)
- **Local asset storage**
  - `JARVIS_IMAGEN_ASSETS_DIR` (default `/app/imagen_assets`)

Related: MCP image pipeline (separate service)

The `idc1-assistance` stack also includes `mcp-image-pipeline`, which exposes image generation tools via a 1MCP HTTP gateway.

Runtime configuration (stack / compose):
- `IMAGE_PIPELINE_MODEL`
  - Default model used by `mcp-image-pipeline` when tool callers omit `model`.
- `IMAGE_PIPELINE_ALLOWED_MODELS`
  - Comma-separated allowlist. The tool call will fail with `model_not_allowed` if the requested model is not in this list.
- `IMAGE_PIPELINE_ASSETS_DIR`
  - Blob storage directory for generated images (should be volume-mounted for persistence).

## Deployment note (local disk storage)
- If `JARVIS_IMAGEN_ASSETS_DIR` is inside a container filesystem and not backed by a volume mount, assets will be lost on container rebuild/redeploy.
- Production should mount a persistent volume to the assets directory.

## Model IDs (Gemini API / Developer API)
- Imagen 4 (text-to-image):
  - `imagen-4.0-generate-001`
  - `imagen-4.0-ultra-generate-001`
  - `imagen-4.0-fast-generate-001`

## Troubleshooting
- **HTTP 429 / RESOURCE_EXHAUSTED** from upstream usually indicates quota/billing limits for the selected model.
  - Prefer switching `JARVIS_IMAGEN_MODEL` to an Imagen model with available quota (e.g. `imagen-4.0-generate-001`).
  - Ensure the selected model is included in `JARVIS_IMAGEN_ALLOWED_MODELS`.

### MCP image pipeline: model selection trial-and-error

Common errors you may see when calling `image-pipeline_1mcp_image_generate` (via 1MCP):

- `model_not_allowed`
  - Meaning: the `model` argument (or the default `IMAGE_PIPELINE_MODEL`) is not present in `IMAGE_PIPELINE_ALLOWED_MODELS`.
  - Fix: update `IMAGE_PIPELINE_ALLOWED_MODELS` in the stack and redeploy `mcp-image-pipeline`.

- `RESOURCE_EXHAUSTED` / quota exceeded (HTTP 429)
  - Meaning: the API key/project has no quota for the upstream model.
  - Note: errors may reference a slightly different model name than you requested (e.g. requesting `gemini-3.1-flash-image-preview` can return quota errors that mention `gemini-3.1-flash-image`). Treat this as a quota issue, not a local allowlist issue.
  - Fix: use a key/project with quota enabled for the relevant image model(s), or switch to a different allowed model.

- Imagen model not supported by the JS SDK
  - If the server is configured to use an `imagen-*` model but the JS SDK does not expose `generateImages`, generation will fail with `imagen_generate_images_not_supported_in_js_sdk`.
  - Fix: either use a Gemini-native image model path (generateContent + inline image extraction) or update dependencies to a version that supports the Imagen API surface.
- **HTTP 404 NOT_FOUND** mentioning “not supported for generateContent” typically indicates the backend is calling `generate_content` against an Imagen model.
  - Ensure the backend is using the Imagen-specific API (`generate_images` / `:predict`) for `imagen-*` models.