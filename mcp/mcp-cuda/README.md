# Job Persistence and Cleanup

## Job Lifecycle

1. **Creation**: Jobs are created via `/invoke` endpoint with `imagen_job_create` tool
2. **Execution**: Jobs run asynchronously via ThreadPoolExecutor
3. **Persistence**: Completed jobs remain in `_imagen_jobs` dictionary
4. **Cleanup**: Old jobs are automatically cleaned up based on retention settings

## Configuration

Environment variables control persistence behavior:

- `MCP_CUDA_JOB_RETENTION_DAYS`: Days to keep completed jobs (default: 7)
- `MCP_CUDA_MAX_JOBS_TO_RETAIN`: Max jobs to keep (default: 100)

## API Endpoints

- `/invoke` (POST): Create jobs and check status
- `/imagen/jobs/{jobId}` (GET): Get job status
- `/imagen/jobs/{jobId}/events` (GET): Stream job events

## Checkpoint directory (SD1.5 single-file)

Store `.ckpt`/`.safetensors` files in:

- Host (Windows): `C:\chaba\.models\checkpoints\`
- Container: `/models/checkpoints`

`mcp-cuda` discovers models by scanning `/models/checkpoints`.

## Model selection

`mcp-cuda` supports selecting the active SD1.5 checkpoint at runtime. The selected model is persisted in `/data/mcp-cuda-state.json` (override with `MCP_CUDA_STATE_DIR`). Changing the model hot-reloads the SD1.5 pipeline.

### Tools

- `imagen_model_list`: list available `.ckpt`/`.safetensors` under `/models/checkpoints`
- `imagen_model_get`: show current selected checkpoint (or fallback env `MCP_CUDA_SD15_MODEL_FILE`)
- `imagen_model_set`: set by filename (recommended) or absolute container path

### Example (HTTP /invoke)

List models:

```json
{ "tool": "imagen_model_list", "arguments": {} }
```

Select a model:

```json
{ "tool": "imagen_model_set", "arguments": { "model": "Inkpunk-Diffusion-v2.ckpt" } }
```

## Debugging

Enable debug logging to monitor job lifecycle:

```python
print(f"[DEBUG] Job status: {job.status}", flush=True)
```
