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

## Debugging

Enable debug logging to monitor job lifecycle:

```python
print(f"[DEBUG] Job status: {job.status}", flush=True)
```
